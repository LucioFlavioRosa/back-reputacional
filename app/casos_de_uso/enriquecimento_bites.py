"""Preenche o que a Bites manda em branco, ANTES da planilha chegar no
motor genérico de ingestão (`ingerir_mencoes.py`).

POR QUE ISTO EXISTE. A Bites manda `Cargo` vazio em ~95-100% das linhas de
todo export mensal já conferido (Julho a Novembro/2026), e nunca manda `N3`
— só `Atributo`/`Categoria`, que sozinhos não bastam pra achar um subtema
(ver `temas_da_mencao.py`, que já tenta e cai pro N1 quando não acha nada
melhor). O sistema já aceita qualquer valor nessas duas colunas sem
vocabulário fechado (`ingestao_score.rotulo_do_cargo`,
`temas_da_mencao.Arvore.resolver`) — o problema nunca foi o motor recusar,
é a planilha não trazer.

A DECISÃO DE PRODUTO (26/11/2026): o que dá pra resolver com CONFIANÇA, só
com o que a própria Bites manda (sem leitura humana linha a linha), fica
resolvido automaticamente; o resto fica em branco até a Bites mandar mais
dado ou alguém complementar o catálogo. Não existe aprovação manual no
meio — ver `CargoDeConta`/`migrations/0122` e o histórico local em
`ferramentas-painel-reputacional/enriquecer_bites.py`, de onde esta
hierarquia e este classificador foram portados.

POR QUE ENRIQUECER O ARQUIVO, E NÃO O MOTOR. `ler_linha`/`ArquivoLido` são
genéricos — servem as cinco fontes, com um caminho rápido e um lento
(ver o cabeçalho de `ArquivoLido`), e mexer ali arrisca as outras quatro
fontes por um problema que é só da Bites. Em vez disso, esta função reescreve
a PLANILHA em memória — preenche as células de `Cargo` e `N3` que vierem
vazias, igual a Bites faria se mandasse o dado — e o resto da ingestão
continua sem saber que isto aconteceu. Zero mudança no motor genérico.

NUNCA SOBRESCREVE O QUE A BITES MANDOU: só age em célula vazia. Um mês em
que a Bites comece a mandar `N3`/`Cargo` preenchido passa a valer o dado
dela, sem precisar desligar nada aqui.
"""

from __future__ import annotations

import io
from typing import Mapping

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.tabelas_score import CargoDeConta
from app.dominio.texto import normalizar

#: AS COLUNAS DO EXPORT MENSAL, pelo nome que a Bites usa. Lidas por nome
#: fixo, igual a `COLUNA_DA_ABRANGENCIA` em `ingerir_mencoes.py`: são sinais
#: só desta fonte, sem campo correspondente em `mencao` nem em
#: `mapeamento_colunas` — o que entra em produção é só o resultado
#: (`Cargo`/`N3`), não estas colunas cruas.
COLUNA_DO_AUTOR = "Autor"
COLUNA_DO_CARGO = "Cargo"
COLUNA_DO_ATRIBUTO = "Atributo"
COLUNA_DA_CATEGORIA = "Categoria"
COLUNA_DO_TEXTO = "Texto"
#: O NOME QUE `migrations/0079` ESCOLHEU pra fonte ler o subtema. Se a
#: planilha não trouxer esta coluna (o caso de todo export mensal até hoje),
#: ela nasce vazia — nunca derruba a subida, porque `tema` é opcional no
#: mapeamento da fonte.
COLUNA_DO_TEMA = "N3"


# =============================================================================
# A HIERARQUIA (igual à migration 0058): pilar -> tema estratégico (N2) -> [N3]
# Portada de `ferramentas-painel-reputacional/enriquecer_bites.py`, que já
# estava conferida contra o cadastro (104 temas ativos, zero sem macro_tema).
# =============================================================================
HIERARQUIA: dict[str, dict[str, list[str]]] = {
    "Governança": {
        "Governança corporativa": [
            "Estrutura de governança / Conselho e comitês",
            "Acionistas",
        ],
        "Contratos e Regulação": [
            "Cumprimento contratual",
            "Revisão e renovação de contratos",
            "Reequilíbrio econômico-financeiro",
            "Segurança jurídica",
            "Fiscalização regulatória",
            "Multa e processos",
            "Agências reguladoras",
        ],
        "Integridade": [
            "Ética e conduta",
            "Investigações e Acordo",
            "Controles internos / Prevenção à fraude e corrupção",
            "Demonstrações de resultados e auditoria",
        ],
        "Modelo de negócio": [
            "Modelo Operacional Aegea",
        ],
        "Político-institucional": [
            "Políticas públicas e setoriais",
            "Patrocínios institucionais",
            "Debate público versus privado",
            "Judicialização e CPIs",
            "Marco Legal do Saneamento",
            "Agenda Associações (Políticas setoriais)",
        ],
    },
    "Eficiência Operacional e Qualidade": {
        "Abastecimento de água": [
            "Frequência, Continuidade",
            "Perdas, fraudes, furtos e ligações irregulares",
            "Rompimento de adutora",
            "Plano de contingência e redundância",
        ],
        "Qualidade da água": [
            "Gestão da qualidade da água",
            "Monitoramento e controle de qualidade da água",
            "Potabilidade",
        ],
        "Esgoto": [
            "Rede e Coleta de esgoto",
            "Tratamento de esgoto",
            "Lançamento irregular e extravasamento",
            "Balneabilidade",
            "Odor e incômodo",
        ],
        "Obras e intervenções": [
            "Custos e eficiência",
            "Acidentes e danos a terceiros",
            "Expansão da rede",
            "Pavimentação e recomposição",
            "Manutenção, interdições e transtornos urbanos",
        ],
        "Atendimento ao cliente": [
            "Canais de atendimento",
            "Atendimento ao cliente",
            "Órgãos de defesa ao cliente (Ouvidoria, Procon, Reclame Aqui)",
        ],
        "Faturamento e cobrança": [
            "Medição e leitura",
            "Conta errada, Tarifa abusiva",
            "Inadimplência, Corte e religação",
        ],
        "Segurança operacional e patrimonial": [
            "Segurança, ameaças e invasões",
        ],
    },
    "Crescimento e Solidez Financeira": {
        "Tarifa": [
            "Reajuste/ Revisão tarifária",
            "Estrutura e composição tarifária",
        ],
        "Desempenho financeiro": [
            "Resultados financeiros e operacionais",
            "Projeções e guidance",
        ],
        "Estrutura de capital": [
            "Endividamento e alavancagem",
            "Aportes dos acionistas",
            "Dividendos e distribuição de capital",
            "Emissão de dívida / Debêntures e bonds",
            "IPO e acesso ao mercado de ações",
        ],
        "Crédito e rating": [
            "Percepção de risco de crédito / Rating corporativo",
            "Covenants",
        ],
        "Crescimento e portfólio": [
            "Novos Negócios e Leilões",
            "M&A e parcerias",
            "Venda de ativo",
            "Entrada em novos mercados",
        ],
        "Novos negócios": [
            "Coleta de resíduos / Tratamento e Destinação",
            "Taxa de lixo",
            "Reúso de água",
        ],
    },
    "Responsabilidade Social": {
        "Ações Sociais": [
            "Programas sociais e comunidade",
        ],
        "Inclusão sanitária / Acessibilidade econômica": [
            "Tarifa social",
            "Cadastro e elegibilidade",
            "Renegociação e apoio ao cliente",
        ],
        "Relacionamento comunitário": [
            "Prêmios, Projetos e incentivos à comunidade",
        ],
        "Educação e conscientização": [
            "Educação ambiental / Engajamento em saneamento e saúde / Uso consciente da água",
        ],
        "Pessoas": [
            "Contratação",
            "Atração e desenvolvimento",
            "Equidade, Diversidade e inclusão",
            "Segurança, condições e relações de trabalho",
            "Cultura organizacional",
        ],
        "Saúde e segurança": [
            "Segurança dos trabalhadores / Acidentes de trabalho",
        ],
        "Relações de trabalho": [
            "Relações sindicais",
            "Relacionamento com terceiros",
        ],
    },
    "Responsabilidade Ambiental": {
        "Proteção ambiental": [
            "Proteção de mananciais / Recuperação ambiental",
            "Oceanos",
            "Biodiversidade",
        ],
        "Meio ambiente e clima": [
            "Resiliência hídrica e novas fontes",
        ],
        "Energia": [
            "Eficiência energética / Energia renovável / Autoprodução e geração distribuída",
        ],
        "Mudanças climáticas": [
            "Emissão gases efeito estufa",
            "Eventos Climáticos",
            "Adaptação e resiliência",
        ],
        "Licenciamento ambiental": [
            "Licenças e autorizações / Condicionantes ambientais / Fiscalização e autuações",
        ],
        "Economia circular e reúso": [
            "Aproveitamento de subprodutos",
            "Gestão de lodo",
            "Redução e valorização de resíduos",
        ],
    },
    "Inovação e Tecnologia": {
        "Tecnologia operação": [
            "Monitoramento em tempo real",
            "Gestão de ativos",
            "Sensoriamento e telemetria",
        ],
        "Automação e inteligência artificial": [
            "Automação de processos",
            "Inteligência artificial / Eficiência baseada em dados / Análise preditiva",
        ],
        "Experiência digital do cliente": [
            "Canais digitais / Autoatendimento",
            "Medição e fatura digital",
        ],
        "Pesquisa e desenvolvimento": [
            "Novas tecnologias",
            "Parcerias com universidades e startups",
        ],
        "Segurança da informação": [
            "Proteção de dados / Privacidade / Cybersegurança / Continuidade",
        ],
    },
    "Prosperidade Compartilhada": {
        "Universalização": [
            "Universalização e metas de cobertura",
        ],
        "Investimento em infraestrutura": [
            "Volume de investimentos",
        ],
        "Legado e impacto": [
            "Benefícios do saneamento (saúde, educação, imóveis, socioeconômico)",
        ],
        "Emprego e renda": [
            "Geração de empregos / Contratação local / Capacitação profissional",
        ],
        "Cadeia de valor": [
            "Desenvolvimento de fornecedores / Fornecedores locais / Compras responsáveis",
            "Drenagem urbana e águas pluviais",
        ],
    },
}

_N3_PARA_PILAR_N2: dict[str, tuple[str, str]] = {}
for _pilar, _n2s in HIERARQUIA.items():
    for _n2, _n3s in _n2s.items():
        for _n3 in _n3s:
            _N3_PARA_PILAR_N2[_n3] = (_pilar, _n2)

PALAVRAS_CHAVE: dict[str, list[str]] = {
    "Cumprimento contratual": ["descumpr", "cumprimento do contrato", "cumprir o contrato", "obrigacao contratual"],
    "Revisão e renovação de contratos": ["aditivo", "renovacao de contrato", "revisao do contrato", "renovar o contrato"],
    "Reequilíbrio econômico-financeiro": ["reequilibrio economico", "reequilibrio financeiro", "readequacao financeira"],
    "Segurança jurídica": ["seguranca juridica"],
    "Fiscalização regulatória": ["fiscalizacao da agergs", "fiscalizacao da agesan", "fiscalizacao regulatoria"],
    "Multa e processos": ["multa", "autuacao", "processo judicial", "acao civil publica", "indenizacao", "liminar", "tribunal", "desembargador", "recurso judicial", "provimento", "representacao interposta"],
    "Agências reguladoras": ["agergs", "agesan", "agencia reguladora", "agencia de regulacao", "ana (", "agencia nacional de aguas"],
    "Ética e conduta": ["etica e conduta", "codigo de etica", "compliance"],
    "Investigações e Acordo": ["propina", "corrupcao", "delacao", "leniencia", "colaboracao premiada", "operacao sevandija", "caixa 2", "caixa dois"],
    "Controles internos / Prevenção à fraude e corrupção": ["controles internos", "prevencao a fraude", "prevencao a corrupcao", "auditoria interna"],
    "Demonstrações de resultados e auditoria": ["balanco", "demonstracoes financeiras", "demonstracao de resultado", "auditoria externa", "revisao contabil"],
    "Modelo Operacional Aegea": ["modelo operacional aegea", "modelo de negocio"],
    "Políticas públicas e setoriais": ["politica publica", "politica setorial", "marco regulatorio do saneamento"],
    "Patrocínios institucionais": ["patrocinio", "patrocinador", "apoio institucional"],
    "Debate público versus privado": ["privatizacao", "privatizar", "estatizacao", "reestatizacao", "publica versus privada", "publico x privado", "propaganda", "publicidade"],
    "Judicialização e CPIs": ["cpi ", "comissao parlamentar de inquerito", "comissao especial de fiscalizacao", "judicializacao"],
    "Marco Legal do Saneamento": ["marco legal do saneamento", "universalizacao ate 2033", "meta de 90%"],
    "Agenda Associações (Políticas setoriais)": ["abcon", "aesbe", "associacao do setor"],
    "Frequência, Continuidade": ["falta de agua", "falta dagua", "desabastecimento", "sem agua", "interrupcao no abastecimento", "racionamento"],
    "Perdas, fraudes, furtos e ligações irregulares": ["ligacao irregular", "ligacao clandestina", "furto de agua", "perdas de agua", "furto de cabo"],
    "Rompimento de adutora": ["rompimento de adutora", "adutora rompida", "vazamento", "cano estourado", "tubulacao rompida", "rompimento da rede"],
    "Plano de contingência e redundância": ["plano de contingencia", "gerador", "caminhao-pipa", "caminhao pipa", "poco artesiano", "poco profundo"],
    "Gestão da qualidade da água": ["qualidade da agua", "agua suja", "agua turva", "agua com gosto", "agua com cheiro", "agua barrenta"],
    "Monitoramento e controle de qualidade da água": ["laudo", "amostra de agua", "analise da agua", "vigiagua", "sisagua"],
    "Potabilidade": ["impropria para consumo", "potavel", "coliformes fecais", "agua contaminada"],
    "Rede e Coleta de esgoto": ["rede de esgoto", "coleta de esgoto", "ligacao de esgoto", "ligacao de agua e esgoto"],
    "Tratamento de esgoto": ["estacao de tratamento de esgoto", "ete ", "tratamento de esgoto"],
    "Lançamento irregular e extravasamento": ["esgoto a ceu aberto", "esgoto na rua", "extravasamento", "lancamento irregular", "esgoto no rio", "despejo de esgoto", "despejo", "efluente", "lancamento de efluente"],
    "Balneabilidade": ["balneabilidade", "praia impropria", "praia propria para banho"],
    "Odor e incômodo": ["mau cheiro", "fedor", "odor"],
    "Custos e eficiência": ["custo da obra", "eficiencia da obra"],
    "Acidentes e danos a terceiros": ["acidente", "atropelamento", "danos a terceiro"],
    "Expansão da rede": ["expansao da rede", "ampliacao da rede", "nova rede", "extensao de rede"],
    "Pavimentação e recomposição": ["pavimentacao", "recomposicao do asfalto", "buraco na rua", "asfalto destruido", "cratera"],
    "Manutenção, interdições e transtornos urbanos": ["obra interditou", "transtorno", "interdicao de via", "manutencao na rede"],
    "Canais de atendimento": ["canal de atendimento", "0800", "whatsapp da", "central de atendimento", "totem de autoatendimento"],
    "Atendimento ao cliente": ["atendimento ao cliente", "mau atendimento", "atendimento precario", "fila de atendimento", "loja da corsan", "loja da aegea"],
    "Órgãos de defesa ao cliente (Ouvidoria, Procon, Reclame Aqui)": ["procon", "ouvidoria", "reclame aqui", "defensoria publica"],
    "Medição e leitura": ["leitura do hidrometro", "hidrometro", "leitura por media", "rota de leitura"],
    "Conta errada, Tarifa abusiva": ["cobranca abusiva", "conta errada", "conta absurda", "cobranca indevida", "tarifa abusiva", "conta alta", "cobranca"],
    "Inadimplência, Corte e religação": ["corte de agua", "religacao", "inadimplencia", "negativado", "serasa", "spc"],
    "Segurança, ameaças e invasões": ["invasao", "ameaca", "assalto", "roubo de equipamento"],
    "Reajuste/ Revisão tarifária": ["reajuste tarifario", "reajuste de", "revisao tarifaria", "aumento na tarifa", "aumento da tarifa"],
    "Estrutura e composição tarifária": ["estrutura tarifaria", "tarifa por quarto", "cobranca por unidade habitacional", "tarifa social"],
    "Resultados financeiros e operacionais": ["lucro liquido", "receita liquida", "ebitda", "resultado financeiro", "lucro de r$"],
    "Projeções e guidance": ["guidance", "projecao de resultado", "perspectiva financeira"],
    "Endividamento e alavancagem": ["divida liquida", "alavancagem", "endividamento"],
    "Aportes dos acionistas": ["aporte de capital", "aumento de capital", "capitalizacao"],
    "Dividendos e distribuição de capital": ["dividendo", "jcp ", "juros sobre capital proprio"],
    "Emissão de dívida / Debêntures e bonds": ["debenture", "bond ", "bonds", "emissao de divida"],
    "IPO e acesso ao mercado de ações": ["ipo", "abertura de capital", "oferta de acoes", "bolsa de valores"],
    "Percepção de risco de crédito / Rating corporativo": ["rating", "fitch", "moody's", "moodys", "s&p", "nota de credito", "rebaixamento"],
    "Covenants": ["covenant"],
    "Novos Negócios e Leilões": ["leilao", "licitacao", "concessao de saneamento em", "edital de concessao"],
    "M&A e parcerias": ["fusao", "aquisicao", "parceria estrategica", "m&a"],
    "Venda de ativo": ["venda de ativo", "desinvestimento", "desistiu da", "desistencia da oferta"],
    "Entrada em novos mercados": ["entrada em", "nova concessao em", "disputa pela copasa", "disputa pela caerd"],
    "Coleta de resíduos / Tratamento e Destinação": ["coleta de residuos", "residuos solidos", "aterro sanitario", "lixao"],
    "Taxa de lixo": ["taxa de lixo", "taxa do lixo"],
    "Reúso de água": ["reuso de agua", "reaproveitamento de agua"],
    "Programas sociais e comunidade": ["projeto social", "acao social", "programa social", "doacao de sangue", "voluntariado"],
    "Tarifa social": ["tarifa social", "cadastro unico", "cadunico", "bpc"],
    "Cadastro e elegibilidade": ["cadastro unico", "elegibilidade", "nis "],
    "Renegociação e apoio ao cliente": ["renegociacao de divida", "parcelamento da conta", "acordo de pagamento"],
    "Prêmios, Projetos e incentivos à comunidade": ["premio", "reconhecimento", "ranking de inovacao", "lei de incentivo a cultura", "patrocinado por", "patrocinador", "patrocinio", "ministerio da cultura"],
    "Educação ambiental / Engajamento em saneamento e saúde / Uso consciente da água": ["educacao ambiental", "conscientizacao", "uso consciente da agua", "saneamento salva"],
    "Contratação": ["vaga de emprego", "processo seletivo", "contratacao", "trainee", "banco de talentos"],
    "Atração e desenvolvimento": ["desenvolvimento profissional", "capacitacao", "treinamento"],
    "Equidade, Diversidade e inclusão": ["diversidade", "equidade", "inclusao racial", "mulheres na lideranca", "pcd"],
    "Segurança, condições e relações de trabalho": ["condicoes de trabalho", "epi", "equipamento de protecao"],
    "Cultura organizacional": ["cultura organizacional", "clima organizacional"],
    "Segurança dos trabalhadores / Acidentes de trabalho": ["acidente de trabalho", "seguranca do trabalho", "sipat"],
    "Relações sindicais": ["sindicato", "acordo coletivo", "act ", "greve", "negociacao coletiva"],
    "Relacionamento com terceiros": ["terceirizada", "terceirizados", "empresa terceira"],
    "Proteção de mananciais / Recuperação ambiental": ["manancial", "recuperacao ambiental", "reflorestamento", "area de preservacao"],
    "Oceanos": ["oceano", "baia de guanabara", "mar "],
    "Biodiversidade": ["biodiversidade", "fauna", "especie ameacada", "mico-leao"],
    "Resiliência hídrica e novas fontes": ["resiliencia hidrica", "nova fonte de agua", "seguranca hidrica", "estiagem"],
    "Eficiência energética / Energia renovável / Autoprodução e geração distribuída": ["energia renovavel", "energia solar", "eficiencia energetica", "autoproducao de energia"],
    "Emissão gases efeito estufa": ["gases do efeito estufa", "emissao de carbono", "pegada de carbono"],
    "Eventos Climáticos": ["enchente", "temporal", "vendaval", "chuva intensa", "inundacao"],
    "Adaptação e resiliência": ["adaptacao climatica", "resiliencia climatica"],
    "Licenças e autorizações / Condicionantes ambientais / Fiscalização e autuações": ["licenca ambiental", "licenciamento ambiental", "fepam", "condicionante ambiental", "autuacao ambiental"],
    "Aproveitamento de subprodutos": ["subproduto", "reaproveitamento de residuo"],
    "Gestão de lodo": ["lodo"],
    "Redução e valorização de resíduos": ["reducao de residuos", "valorizacao de residuos", "economia circular"],
    "Monitoramento em tempo real": ["monitoramento em tempo real", "centro de operacoes"],
    "Gestão de ativos": ["gestao de ativos"],
    "Sensoriamento e telemetria": ["telemetria", "sensor", "geofone"],
    "Automação de processos": ["automacao de processos", "automacao"],
    "Inteligência artificial / Eficiência baseada em dados / Análise preditiva": ["inteligencia artificial", " ia ", "analise preditiva", "dados preditivos"],
    "Canais digitais / Autoatendimento": ["aplicativo", "app ", "autoatendimento", "canal digital"],
    "Medição e fatura digital": ["fatura digital", "conta digital", "nota fiscal eletronica"],
    "Novas tecnologias": ["nova tecnologia", "inovacao tecnologica"],
    "Parcerias com universidades e startups": ["universidade", "startup", "parceria academica"],
    "Proteção de dados / Privacidade / Cybersegurança / Continuidade": ["protecao de dados", "lgpd", "ciberseguranca", "cybersegurança", "privacidade"],
    "Universalização e metas de cobertura": ["universalizacao", "meta de cobertura", "ate 2033"],
    "Volume de investimentos": ["investimento de r$", "investiu r$", "bilhoes em investimentos", "milhoes em investimentos"],
    "Benefícios do saneamento (saúde, educação, imóveis, socioeconômico)": ["beneficio do saneamento", "saude publica", "valorizacao de imoveis"],
    "Geração de empregos / Contratação local / Capacitação profissional": ["geracao de emprego", "emprego local", "capacitacao profissional", "mao de obra local", "responsabilidades e atribuicoes", "processo seletivo", "vaga de emprego", "envie seu curriculo", "banco de talentos"],
    "Desenvolvimento de fornecedores / Fornecedores locais / Compras responsáveis": ["fornecedor local", "compra responsavel", "desenvolvimento de fornecedores"],
    "Drenagem urbana e águas pluviais": ["drenagem urbana", "aguas pluviais", "galeria pluvial"],
}

CATEGORIA_PARA_N3: dict[str, list[str]] = {
    "abastecimento": ["Frequência, Continuidade", "Perdas, fraudes, furtos e ligações irregulares", "Rompimento de adutora", "Plano de contingência e redundância"],
    "qualidade da agua": ["Gestão da qualidade da água", "Monitoramento e controle de qualidade da água", "Potabilidade"],
    "esgoto": ["Rede e Coleta de esgoto", "Tratamento de esgoto", "Lançamento irregular e extravasamento", "Balneabilidade", "Odor e incômodo"],
    "fatura": ["Conta errada, Tarifa abusiva", "Medição e leitura", "Inadimplência, Corte e religação"],
    "tarifa": ["Reajuste/ Revisão tarifária", "Estrutura e composição tarifária", "Conta errada, Tarifa abusiva"],
    "contrato de concessao": ["Cumprimento contratual", "Revisão e renovação de contratos", "Reequilíbrio econômico-financeiro", "Segurança jurídica"],
    "agencia de regulacao": ["Agências reguladoras", "Fiscalização regulatória"],
    "atendimento": ["Atendimento ao cliente", "Canais de atendimento", "Órgãos de defesa ao cliente (Ouvidoria, Procon, Reclame Aqui)"],
    "obras e melhorias": ["Expansão da rede", "Manutenção, interdições e transtornos urbanos", "Custos e eficiência", "Acidentes e danos a terceiros"],
    "pavimentacao": ["Pavimentação e recomposição"],
    "projetos sociais": ["Programas sociais e comunidade", "Prêmios, Projetos e incentivos à comunidade"],
    "reconhecimento": ["Prêmios, Projetos e incentivos à comunidade"],
    "publicidade": ["Debate público versus privado", "Patrocínios institucionais"],
    "residuos solidos": ["Coleta de resíduos / Tratamento e Destinação", "Taxa de lixo"],
    "responsabilidade ambiental": ["Proteção de mananciais / Recuperação ambiental", "Licenças e autorizações / Condicionantes ambientais / Fiscalização e autuações"],
    "comunicados": [],
    "servicos": [],
    "outros": [],
    "holding": ["Acionistas", "Resultados financeiros e operacionais"],
}

#: Os métodos que PROVAM confiança suficiente pra entrar direto na coluna
#: final `N3` — nunca "ambiguo_*"/"sem_match": esses ficam em branco de
#: propósito, igual à regra que já vale pro script local.
METODOS_CONFIAVEIS = frozenset({"categoria+texto", "categoria", "texto"})


def _sem_acento(texto: object) -> str:
    """Minúsculas e sem acento, pela chave canônica (`dominio/texto.normalizar`).

    NÃO REIMPLEMENTA NFKD: a regra de tirar acento mora num lugar só — ver o
    cabeçalho de `dominio/texto.py` pelo defeito que a duplicação já causou
    antes (a busca que não achava o que a carga tinha unido).
    """
    if not isinstance(texto, str):
        return ""
    return normalizar(texto)


def _candidatos_do_pilar(pilar: str | None) -> list[str]:
    pilar = (pilar or "").strip()
    n2s = HIERARQUIA.get(pilar)
    if not n2s:
        return list(_N3_PARA_PILAR_N2.keys())
    candidatos: list[str] = []
    for n3s in n2s.values():
        candidatos.extend(n3s)
    return candidatos


def classificar_linha(
    atributo: object, categoria: object, texto: object
) -> tuple[str, str, str]:
    """(N2, N3, método) pro que der pra resolver só com Atributo+Categoria+Texto.

    SÓ TENTA COM `atributo` PREENCHIDO: é o filtro rígido de pilar, e tentar
    com os ~92 N3 inteiros sem ele derruba a precisão (medido no histórico
    local: nenhuma linha sem Atributo tem sugestão não-vazia).

    `metodo` vazio ou em `sem_match`/`ambiguo_*` significa "não dá pra
    confiar" — quem chama decide se promove pra coluna final ou deixa em
    branco (`METODOS_CONFIAVEIS`).
    """
    if not atributo:
        return "", "", ""

    candidatos = _candidatos_do_pilar(str(atributo))
    candidatos_set = set(candidatos)

    pontos_categoria = {n3: 0.0 for n3 in candidatos}
    pontos_texto = {n3: 0.0 for n3 in candidatos}

    if isinstance(categoria, str):
        for tag in (_sem_acento(t.strip()) for t in categoria.split(",")):
            for n3 in CATEGORIA_PARA_N3.get(tag, []):
                if n3 in candidatos_set:
                    pontos_categoria[n3] += 1.0

    texto_normalizado = _sem_acento(texto)
    if texto_normalizado:
        for n3 in candidatos:
            termos = PALAVRAS_CHAVE.get(n3, [])
            achados = sum(1 for termo in termos if termo in texto_normalizado)
            if achados:
                pontos_texto[n3] += min(achados, 3)

    total = {n3: pontos_categoria[n3] * 2 + pontos_texto[n3] for n3 in candidatos}
    maior = max(total.values()) if total else 0.0
    if maior <= 0:
        return "", "", "sem_match"

    empatados = [n3 for n3, pontuacao in total.items() if pontuacao == maior]
    if len(empatados) > 1:
        maior_texto = max(pontos_texto[n3] for n3 in empatados)
        if maior_texto > 0:
            empatados = [n3 for n3 in empatados if pontos_texto[n3] == maior_texto]

    if len(empatados) > 1:
        pilares_n2 = {_N3_PARA_PILAR_N2[n3] for n3 in empatados}
        if len(pilares_n2) == 1:
            _pilar_unico, n2_unico = next(iter(pilares_n2))
            return n2_unico, "", "ambiguo_entre_subtemas_do_mesmo_n2"
        return "", "", "ambiguo_sem_match"

    melhor_n3 = empatados[0]
    _pilar_n3, n2 = _N3_PARA_PILAR_N2[melhor_n3]
    if pontos_categoria[melhor_n3] > 0 and pontos_texto[melhor_n3] > 0:
        metodo = "categoria+texto"
    elif pontos_categoria[melhor_n3] > 0:
        metodo = "categoria"
    else:
        metodo = "texto"
    return n2, melhor_n3, metodo


def cargo_conhecido(sessao: Session) -> dict[str, str]:
    """`autor_normalizado` → cargo, do catálogo (`CargoDeConta`/0122)."""
    return dict(
        sessao.execute(
            select(CargoDeConta.autor_normalizado, CargoDeConta.cargo)
        ).all()
    )


def _normalizar_autor(valor: object) -> str:
    if not isinstance(valor, str):
        return ""
    return _sem_acento(valor.lstrip("@").strip())


def enriquecer_planilha_bites(sessao: Session, conteudo: bytes) -> bytes:
    """A planilha mensal da Bites, com `Cargo` e `N3` preenchidos onde dava.

    NUNCA SOBRESCREVE CÉLULA PREENCHIDA — só entra em branco. Lê a PRIMEIRA
    aba, igual ao resto da ingestão (`veiculos_da_imprensa`/memória do
    time: "a plataforma lê a primeira aba, não exige nome").
    """
    catalogo = cargo_conhecido(sessao)

    pasta = openpyxl.load_workbook(io.BytesIO(conteudo), data_only=True)
    aba = pasta.worksheets[0]

    cabecalho = [celula.value for celula in aba[1]]
    indice: dict[str, int] = {
        nome: posicao + 1 for posicao, nome in enumerate(cabecalho) if nome
    }

    #: SEM `Autor`/`Atributo`/`Texto` NÃO HÁ O QUE ENRIQUECER — a planilha
    #: volta intacta, e quem valida colunas obrigatórias decide o resto.
    if COLUNA_DO_AUTOR not in indice and COLUNA_DO_ATRIBUTO not in indice:
        saida = io.BytesIO()
        pasta.save(saida)
        return saida.getvalue()

    coluna_cargo = indice.get(COLUNA_DO_CARGO)
    coluna_tema = indice.get(COLUNA_DO_TEMA)
    if coluna_tema is None:
        #: A COLUNA NASCE AQUI quando a Bites não a manda — é o caso de todo
        #: export mensal até hoje. `tema` é opcional no mapeamento da fonte
        #: (`migrations/0079`), então uma coluna vazia não impede a subida.
        coluna_tema = len(cabecalho) + 1
        aba.cell(row=1, column=coluna_tema, value=COLUNA_DO_TEMA)
        cabecalho.append(COLUNA_DO_TEMA)

    coluna_autor = indice.get(COLUNA_DO_AUTOR)
    coluna_atributo = indice.get(COLUNA_DO_ATRIBUTO)
    coluna_categoria = indice.get(COLUNA_DA_CATEGORIA)
    coluna_texto = indice.get(COLUNA_DO_TEXTO)

    for linha in range(2, aba.max_row + 1):
        if coluna_cargo is not None and coluna_autor is not None:
            celula_cargo = aba.cell(row=linha, column=coluna_cargo)
            if not celula_cargo.value:
                chave = _normalizar_autor(aba.cell(row=linha, column=coluna_autor).value)
                conhecido = catalogo.get(chave) if chave else None
                if conhecido:
                    celula_cargo.value = conhecido

        celula_tema = aba.cell(row=linha, column=coluna_tema)
        if not celula_tema.value and coluna_atributo is not None:
            atributo = aba.cell(row=linha, column=coluna_atributo).value
            categoria = (
                aba.cell(row=linha, column=coluna_categoria).value
                if coluna_categoria is not None
                else None
            )
            texto = (
                aba.cell(row=linha, column=coluna_texto).value
                if coluna_texto is not None
                else None
            )
            _n2, n3, metodo = classificar_linha(atributo, categoria, texto)
            if metodo in METODOS_CONFIAVEIS and n3:
                celula_tema.value = n3

    saida = io.BytesIO()
    pasta.save(saida)
    return saida.getvalue()
