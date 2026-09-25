# Painel Reputacional Aegea

O CRM das relações institucionais da Aegea: registra cada interação com a
imprensa, o poder público, investidores, parceiros e entidades, e lê o
conjunto delas como reputação. Este glossário vale para o back e para o
front (`front-reputacional`), que usam os mesmos nomes de propósito.

## Language

### O registro

**Interação**:
Um encontro registrado entre a Aegea e uma contraparte: reunião, entrevista,
evento, visita, manifestação formal. É a linha da Base e a unidade de todo
gráfico.
_Avoid_: agenda (fica só nos nomes internos do código), reunião (é um dos
tipos), registro

**Tipo de interação**:
Que espécie de encontro foi — Mídia, Agenda de mercado, Agenda pública,
Manifestação formal, Evento, Visita, Reunião, Consulta recebida. Escolhido por
quem registra.
_Avoid_: formato (é outra coisa, ver abaixo), modalidade (essa é
presencial/online/híbrida)

**Frente**:
Quem é a contraparte, em oito famílias: Imprensa, Entidades (governo),
Parceiros, Eventos, Investidores, Agentes Públicos (legislativo), Interna,
Bancos/Credores. É DERIVADA pelo servidor do tipo da instituição (e do tipo
de interação, para Parceiros × Eventos); ninguém a escolhe.
_Avoid_: área (é a área da Aegea), público

**Formato**:
O detalhe de frente de Imprensa (entrevista, release, podcast…) e de
Investidores (roadshow, call de resultados…). Só existe dentro dessas duas
frentes.
_Avoid_: tipo de interação, tipo

**Área**:
A área da Aegea que conduziu a interação — Comunicação, Relações
Institucionais, Operações Financeiras, Relações com Investidores. Uma
interação pode ter mais de uma.
_Avoid_: frente, departamento

**Tema**:
O assunto de que a interação tratou (Tarifa, Biometano, Saneamento…). Uma
interação tem vários; é o que se filtra ao preparar uma agenda.
_Avoid_: tag (só no nome do parâmetro `tags`), assunto (nome antigo)

**Clima**:
Como a conversa foi — Proativo, Neutro ou Reativo. Há o clima esperado
(antes) e o clima registrado (depois).
_Avoid_: postura, sentimento, propositivo/tenso (códigos internos)

**Desfecho**:
Como a interação terminou — Avançou, Mantido, Recuou ou Sem definição.
_Avoid_: resultado (só no nome interno), status

**Situação**:
Onde a interação está no fluxo — Solicitado, Aceito ou Negado. Agrupa-se em
Resolvidos, Em aberto e Declinados para a taxa de resolutividade.
_Avoid_: status (só no nome interno)

**Relevância**:
O tier (1 a 4) da INSTITUIÇÃO, que a interação herda ao ser registrada.
_Avoid_: tier (só no nome interno), prioridade (é campo do legislativo)

⚠ NÃO CONFUNDIR COM **Tier do veículo**, do Score (ver abaixo). São dois
números diferentes, com o mesmo nome no banco: `instituicao.tier` e
`interacao.tier` são `smallint` com FK para `relevancia` e valem para o CRM;
`mencao.tier` e `score_mes_fonte.tier` são texto (`muito_relevante` |
`relevante` | `menos_relevante`) e valem para o índice. Um `join` entre os dois
casaria uma capa do Valor com um nível de relevância de instituição.

**Consulta recebida**:
Um questionário que chegou de fora — de um banco, de um investidor, de uma
plataforma de rating — perguntando sobre assunto que a companhia não
comunicou. É um tipo de interação como os outros: tem contraparte, data e
tema, o questionário é material dela, e a frente sai do tipo da instituição.
_Avoid_: e-mail (é o canal), sondagem, questionário (é o documento)

**Alegação**:
O que uma pergunta recebida dá como fato, em uma frase, na voz de quem alega —
"o Banco X não renegociaria a dívida". Vive solta da consulta porque se
repete: a mesma alegação chega de instituições diferentes, e é isso que se
conta.
_Avoid_: boato, rumor (afirmam má-fé que o registro não prova), fake news

**Convergência**:
Quantas INSTITUIÇÕES DISTINTAS trouxeram a mesma alegação, e em quanto tempo.
É a leitura da aba: um banco perguntando é diligência; quatro perguntando o
mesmo em duas semanas é um movimento. Convergência não é prova de combinação.
_Avoid_: coordenação, conluio, campanha

**Apuração**:
O que a companhia verificou sobre uma alegação — Em apuração, Sem fundamento,
Procede em parte, Procede. Uma alegação é apurada uma vez, e não uma vez por
consulta.
_Avoid_: status, desmentido

### Com quem se fala

**Instituição**:
A contraparte institucional — órgão, veículo, entidade, investidor,
proposição, credor. Tem um tipo (derivado da categoria de público), uma
categoria de público, uma relevância e pessoas.
_Avoid_: entidade (é um dos tipos), stakeholder (aposentado), empresa

**Público**:
A categoria de público da instituição — as dez da taxonomia (Poder
Executivo, Imprensa e Formadores de Opinião, Mercado Financeiro…), com
subcategoria. É atributo da instituição, não da interação; é dele que nasce o
tipo.
_Avoid_: stakeholder, natureza do órgão (ambos aposentados pela taxonomia)

**Contato**:
Quem fala por uma instituição: nome, cargo, e-mail. Pertence a uma
instituição só.
_Avoid_: interlocutor (só no nome interno), pessoa, representante

**Representante Aegea**:
Quem fala pela Aegea numa interação; porta-voz quando conduz, equipe quando
acompanha. Tem uma área e os temas de que pode falar.
_Avoid_: pessoa Aegea (só no nome interno), porta-voz (é um dos papéis)

### O ciclo de vida de um cadastro

**Desativar / Reativar**:
Tirar de (ou devolver a) toda lista onde se escolhe — formulário de
interação, cadastro de contato — mantendo o histórico intacto. Vale para
instituição, contato, tema, referência e valores de dicionário. Uma
instituição desativada leva os contatos dela consigo, sem reescrevê-los.
_Avoid_: desligar (nome antigo de contato), arquivar, apagar

**Excluir**:
Apagar de vez o que entrou por engano. Só é permitido para quem nunca esteve
numa interação; para quem esteve, o gesto é Desativar.
_Avoid_: remover (nome antigo de contato), deletar

**Disponível**:
O contato que pode ser oferecido numa interação nova: ele ativo E a
instituição dele ativa.

### O que se lê

**Recorte**:
O conjunto de filtros em vigor — período, frente, área, tipo de interação,
público, instituição, tema, clima esperado, clima registrado, desfecho,
situação, relevância, esfera, unidade, UF, busca. Mora no endereço; todo número, tabela e gráfico obedece
ao mesmo recorte, e o servidor é quem o aplica.
_Avoid_: filtro (é um campo do recorte), query, seleção

**Dicionário**:
Um vocabulário fechado que filtros e formulários oferecem (esferas, unidades
de negócio, climas…). Os ABERTOS a coordenação edita na Administração; os
FECHADOS são estrutura do modelo e mudam por código.
_Avoid_: enum, lista fixa, catálogo (o catálogo é o conjunto que o front
carrega)

### O Score Executivo

A segunda leitura do painel: enquanto a Base conta interações, o Score lê o que
se fala da companhia e devolve uma nota por mês. Vocabulário próprio, e alguns
nomes colidem com os de cima — onde colidem, está dito.

**Índice de Saúde Reputacional (ISR)**:
A nota de 0 a 100 da companhia no mês: a média das cinco lentes, ponderada
pelos pesos da calibração. É o número que a diretoria cita, e por isso não se
recalcula no navegador — ele vem pronto do servidor, com a régua gravada.
_Avoid_: score (é a nota de UMA lente), índice de reputação, nota geral

**Lente**:
Uma das cinco famílias de stakeholder pelas quais a reputação é lida —
Imprensa, Mercado, Sociedade digital, Clientes, Institucional. É fechada: uma
lente nova é mudança de modelo, não de cadastro.
_Avoid_: dimensão, eixo, pilar, categoria

**Fonte**:
De onde as menções de uma lente vêm — um fornecedor (Clipei, Approach, Bites)
ou o próprio CRM, que é a fonte INTERNA da lente Institucional. Desligar uma
fonte tira o dado dela do cálculo sem apagar o histórico.
_Avoid_: fornecedor (é quem entrega, e uma entrega pode virar duas fontes),
provedor, origem (origem é da ficha de procedência)

**Menção**:
Uma publicação, post ou mensagem individual que a ingestão gravou, com
sentimento, tema e — quando a fonte classifica — tier do veículo. É a linha
que o Score conta, como a interação é a linha da Base.
_Avoid_: matéria (é só de imprensa), post, citação

**Tier do veículo**:
Quanto uma matéria vale pelo porte de quem a publicou: `muito_relevante`,
`relevante`, `menos_relevante`. Hoje só as duas fontes de clipping o
classificam (Imprensa e Mercado); onde não há tier, a menção vale 1. A coluna
existe em TODA menção — a limitação é de dado, não de modelo.
_Avoid_: relevância (essa é a da instituição, no CRM — ver acima), peso (peso é
da lente), importância

**Régua**:
Como cada menção é convertida em número: a régua de TIER (quanto vale a
matéria pelo veículo) e a de ENGAJAMENTO (o que se soma de cada menção de
rede). Mudar uma régua recalcula todos os meses — é o que mantém a curva
comparável. Onde a fonte não tem o dado que a régua pede — clipping não tem
curtida, interação de CRM menos ainda — cada menção vale 1, e a fonte continua
na conta: régua nenhuma tira uma lente do índice por falta de dado. A exceção é
"só tier 1", que descarta o que não é tier 1 porque é isso que ela pede.
_Avoid_: fórmula (a fórmula é o NS), critério, modelo

**Peso**, **Peso efetivo**:
Quanto uma lente vale no ISR. O peso é o número gravado na calibração; o
EFETIVO é o que ele valeu de fato depois de as lentes sem dado saírem do
denominador — com uma lente fora, 30 de 70 valem 43%. A tela mostra os dois.
_Avoid_: participação, share

**Faixa**:
Em que território a nota caiu: Crítico (<40), Atenção (40–54), Estável
(55–69), Sólido (70–84), Referência (≥85). Vale para o ISR e para a nota de
cada lente.
_Avoid_: nível, status, classificação

**Calibração**:
A régua em vigor, versionada com autor e data: pesos, réguas, fontes
desligadas, os limites dos detectores e o desenho do radial. É configuração da
ORGANIZAÇÃO, e não preferência de quem olha — mudar ali muda o número que todo
mundo lê. A tabela só cresce; nada se apaga.
_Avoid_: configuração, ajustes, preferências

**Sinal**:
Uma frase que um detector escreveu a partir dos dados da lente — "o negativo
subiu de 10% em julho para 23% em agosto". NÃO é texto salvo: recalcula-se a
cada leitura, por regra determinística, sem LLM.
_Avoid_: insight, destaque, análise, comentário

**Lacuna de dado**:
Um sinal que diz o que FALTA, e não o que aconteceu: mês sem base, mês sem
sentimento integrado, lente sem série. Vai sempre no fim da lista e não disputa
as vagas dos sinais reais.
_Avoid_: gap, pendência, alerta

**Mês parcial**:
Um mês medido por menos de quatro lentes. O ISR dele é legítimo pela fórmula e
ENGANOSO na curva — é o score de uma lente desenhado como se fosse o da
companhia. Ele aparece no gráfico, marcado, mas não rege a escala do eixo.
_Avoid_: mês incompleto (o nome interno), mês vazio (esse não tem dado nenhum)
