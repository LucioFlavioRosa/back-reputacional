-- =============================================================================
-- O TEMA TAMBÉM TEM APELIDO, DO JEITO QUE A UNIDADE JÁ TINHA (0099)
-- =============================================================================
--
-- O QUE ESTAVA ACONTECENDO. `temas_da_mencao.Arvore.resolver` já tenta ligar
-- `mencao.tema_texto` (onde a Clipei grava a coluna `Subcategoria` do export,
-- via `mapeamento_colunas`) contra o cadastro oficial de temas, por NOME
-- IDÊNTICO normalizado — e só cai pro N1 (via `mencao.atributo`) quando não
-- acha. O vocabulário da Clipei é próprio, não o do cadastro: "Regularidade
-- no fornecimento de água", "Cobertura da rede de esgoto" não existem como
-- nome de N3/N2 oficial, embora signifiquem um subtema que já existe
-- ("Frequência, Continuidade", "Rede e Coleta de esgoto").
--
-- A MEDIÇÃO, 24/11/2026, sobre um export real da Clipei (13.263 linhas):
--
--     Categoria ........... 17 valores distintos (bate com o nível N2)
--     Subcategoria ........ 180 valores distintos (bate com o nível N3)
--     combinações Categoria+Subcategoria ... 186, das quais só 6 subcategorias
--       se repetem sob mais de uma Categoria — e nas 6, ambas concordam no
--       mesmo N2/N3, então a Subcategoria sozinha já desambigua.
--
--     por confiança do mapeamento manual (Categoria+Subcategoria -> N2/N3):
--         alta (nome quase idêntico ao oficial)  .....  55,7% das linhas
--         média (julgamento semântico sólido)    .....  24,1% das linhas
--         baixa (chute, pendente de validação)   .....  18,0% das linhas
--         sem mapeamento possível a partir do rótulo .   2,2% das linhas
--
-- ESTA MIGRATION SÓ CADASTRA OS DE CONFIANÇA ALTA + MÉDIA (131 apelidos,
-- cobrindo 79,8% das linhas medidas) — os de confiança baixa ficam de fora
-- até o Jones validar caso a caso; entram numa migration futura.
--
-- POR QUE UMA TABELA DE APELIDO, E NÃO MAIS UM TEMA: o cadastro continua a
-- autoridade (`temas_da_mencao.py`, cabeçalho) — aqui não se cria tema, só se
-- registra que um rótulo do fornecedor SIGNIFICA um tema que já existe. Mesmo
-- raciocínio de `unidade_negocio_apelido` (0099), aqui para Tema/MacroTema no
-- lugar de UnidadeNegocio — ver `tabelas_catalogo.TemaApelido`.
--
-- APONTA PRA Tema (N3) OU MacroTema (N2), NUNCA OS DOIS: quando o rótulo da
-- Clipei só permite confirmar o nível do meio (nenhum caso nesta leva), o N3
-- fica de propósito sem palpite — `CheckConstraint` barra as duas colunas
-- preenchidas na mesma linha.
--
-- O QUE ESTA MIGRATION NÃO FAZ
-- ----------------------------
--
-- NÃO LIGA AS MENÇÕES QUE JÁ ESTÃO NA BASE. Isso é o comando
-- `app/comandos/ligar_mencoes_a_taxonomia.py` (modo `--recalcular`, que esta
-- leva também adiciona) — mesma razão da `0098`/`0099`: resolver aqui exigiria
-- reimplementar `normalizar` e a precedência de `Arvore.resolver` em SQL.
--
-- NÃO MUDA `temas_da_mencao.arvore()`. A leitura dos apelidos por essa função
-- é código, não SQL — ver o diff em `app/casos_de_uso/temas_da_mencao.py`.
-- =============================================================================

begin;

create table if not exists tema_apelido (
    nome_normalizado text primary key,
    nome             text not null,
    tema_id          integer references tema (id),
    macro_tema_id    smallint references macro_tema (id),
    constraint tema_apelido_exatamente_um_nivel
        check ((tema_id is not null) <> (macro_tema_id is not null))
);

--: OS 131 APELIDOS DE CONFIANÇA ALTA/MÉDIA, medidos em 24/11/2026 contra um
--: export real da Clipei. `on conflict do nothing`: a migration roda em
--: ambiente que já pode ter a linha, e repetir não é erro.
insert into tema_apelido (nome_normalizado, nome, tema_id)
select v.chave, v.nome, t.id
  from (values
    ('abertura de capital', 'Abertura de capital', 'IPO e acesso ao mercado de ações'),
    ('academia aegea', 'Academia Aegea', 'Atração e desenvolvimento'),
    ('acao civil publica (acp)', 'Ação Civil Pública (ACP)', 'Judicialização e CPIs'),
    ('acesso ao hidrometro', 'Acesso ao hidrômetro', 'Medição e leitura'),
    ('acidente em obras', 'Acidente em obras', 'Acidentes e danos a terceiros'),
    ('acidente ocasionado por asfalto danificado', 'Acidente ocasionado por asfalto danificado', 'Acidentes e danos a terceiros'),
    ('acidente ocasionado por tampa de pv danificada', 'Acidente ocasionado por tampa de PV danificada', 'Acidentes e danos a terceiros'),
    ('acoes de limpeza de praias', 'Ações de limpeza de praias', 'Oceanos'),
    ('acoes de voluntariado', 'Ações de voluntariado', 'Programas sociais e comunidade'),
    ('acordo coletivo de trabalho', 'Acordo Coletivo de Trabalho', 'Relações sindicais'),
    ('acusacoes de irregularidades', 'Acusações de irregularidades', 'Investigações e Acordo'),
    ('agua com cloro', 'Água com cloro', 'Potabilidade'),
    ('agua com coloracao', 'Água com coloração', 'Potabilidade'),
    ('agua com gosto ruim', 'Água com gosto ruim', 'Potabilidade'),
    ('aguas app', 'Águas APP', 'Canais digitais / Autoatendimento'),
    ('ampliacao da cobertura para zona rural', 'Ampliação da cobertura para zona rural', 'Universalização e metas de cobertura'),
    ('ampliacao das redes de agua e esgoto', 'Ampliação das redes de água e esgoto', 'Expansão da rede'),
    ('ampliacoes da rede de agua', 'Ampliações da rede de água', 'Expansão da rede'),
    ('ampliacoes da rede de esgoto', 'Ampliações da rede de esgoto', 'Expansão da rede'),
    ('aplicacao de multas', 'Aplicação de multas', 'Multa e processos'),
    ('asfalto danificado apos obras', 'Asfalto danificado após obras', 'Pavimentação e recomposição'),
    ('atendimento de caminhao-pipa', 'Atendimento de caminhão-pipa', 'Plano de contingência e redundância'),
    ('atendimento itinerante', 'Atendimento itinerante', 'Canais de atendimento'),
    ('atendimento no ganha tempo', 'Atendimento no Ganha Tempo', 'Canais de atendimento'),
    ('atraso na recomposicao asfaltica', 'Atraso na recomposição asfáltica', 'Pavimentação e recomposição'),
    ('baixa pressao', 'Baixa pressão', 'Frequência, Continuidade'),
    ('balneabilidade de praias', 'Balneabilidade de praias', 'Balneabilidade'),
    ('calcada danificada', 'Calçada danificada', 'Pavimentação e recomposição'),
    ('campanha de doacao de sangue', 'Campanha de doação de sangue', 'Programas sociais e comunidade'),
    ('campanha de renegociacao de debitos', 'Campanha de Renegociação de Débitos', 'Renegociação e apoio ao cliente'),
    ('canais digitais de atendimento', 'Canais digitais de atendimento', 'Canais digitais / Autoatendimento'),
    ('centro de controle operacional (cco)', 'Centro de Controle Operacional (CCO)', 'Monitoramento em tempo real'),
    ('cobertura da rede de esgoto', 'Cobertura da rede de esgoto', 'Rede e Coleta de esgoto'),
    ('cobranca indevida', 'Cobrança Indevida', 'Conta errada, Tarifa abusiva'),
    ('combate a fraudes', 'Combate a fraudes', 'Perdas, fraudes, furtos e ligações irregulares'),
    ('combate a perdas de agua', 'Combate a perdas de água', 'Perdas, fraudes, furtos e ligações irregulares'),
    ('comissao parlamentar de inquerito (cpi)', 'Comissão Parlamentar de Inquérito (CPI)', 'Judicialização e CPIs'),
    ('comunicado de abastecimento', 'Comunicado de Abastecimento', 'Frequência, Continuidade'),
    ('comunicado de corte', 'Comunicado de corte', 'Inadimplência, Corte e religação'),
    ('condenacao judicial', 'Condenação judicial', 'Judicialização e CPIs'),
    ('conserto de extravasamento de esgoto', 'Conserto de extravasamento de esgoto', 'Lançamento irregular e extravasamento'),
    ('conserto de vazamentos', 'Conserto de vazamentos', 'Perdas, fraudes, furtos e ligações irregulares'),
    ('construcao de eta', 'Construção de ETA', 'Gestão da qualidade da água'),
    ('construcao de ete', 'Construção de ETE', 'Tratamento de esgoto'),
    ('construcao de reservatorios', 'Construção de reservatórios', 'Plano de contingência e redundância'),
    ('contratacao de executivos', 'Contratação de executivos', 'Estrutura de governança / Conselho e comitês'),
    ('cooperacao tecnica', 'Cooperação técnica', 'Parcerias com universidades e startups'),
    ('criticas a privatizacao dos servicos', 'Críticas à privatização dos serviços', 'Debate público versus privado'),
    ('cursos profissionalizantes para a comunidade', 'Cursos profissionalizantes para a comunidade', 'Geração de empregos / Contratação local / Capacitação profissional'),
    ('de olho no oleo', 'De Olho no Óleo', 'Redução e valorização de resíduos'),
    ('demonstracoes financeiras', 'Demonstrações financeiras', 'Demonstrações de resultados e auditoria'),
    ('descarte irregular na rede de esgoto', 'Descarte irregular na rede de esgoto', 'Lançamento irregular e extravasamento'),
    ('desejos de natal', 'Desejos de Natal', 'Programas sociais e comunidade'),
    ('dicas de preservacao ambiental', 'Dicas de preservação ambiental', 'Educação ambiental / Engajamento em saneamento e saúde / Uso consciente da água'),
    ('doacao de mudas', 'Doação de mudas', 'Proteção de mananciais / Recuperação ambiental'),
    ('eficiencia energetica', 'Eficiência energética', 'Eficiência energética / Energia renovável / Autoprodução e geração distribuída'),
    ('elogio a equipe de atendimento', 'Elogio à Equipe de Atendimento', 'Atendimento ao cliente'),
    ('emissao de debentures', 'Emissão de debêntures', 'Emissão de dívida / Debêntures e bonds'),
    ('emissao do debentures', 'Emissão do debêntures', 'Emissão de dívida / Debêntures e bonds'),
    ('extravasamento de esgoto', 'Extravasamento de esgoto', 'Lançamento irregular e extravasamento'),
    ('falecimento de colaborador', 'Falecimento de colaborador', 'Segurança dos trabalhadores / Acidentes de trabalho'),
    ('falta de agua', 'Falta de água', 'Frequência, Continuidade'),
    ('fato relevante', 'Fato relevante', 'Demonstrações de resultados e auditoria'),
    ('fatura alta', 'Fatura Alta', 'Conta errada, Tarifa abusiva'),
    ('fiscalizacao de ligacoes clandestinas', 'Fiscalização de ligações clandestinas', 'Lançamento irregular e extravasamento'),
    ('fiscalizacao de metas contratuais', 'Fiscalização de metas contratuais', 'Fiscalização regulatória'),
    ('fiscalizacao de servicos', 'Fiscalização de serviços', 'Fiscalização regulatória'),
    ('furto de cabos', 'Furto de cabos', 'Perdas, fraudes, furtos e ligações irregulares'),
    ('horario de atendimento', 'Horário de atendimento', 'Canais de atendimento'),
    ('inicio da operacao dos servicos', 'Início da operação dos serviços', 'Modelo Operacional Aegea'),
    ('instalacao de hidrometros', 'Instalação de hidrômetros', 'Medição e leitura'),
    ('instalacao de pontos de controle de qualidade', 'Instalação de pontos de controle de qualidade', 'Monitoramento e controle de qualidade da água'),
    ('investimentos', 'Investimentos', 'Volume de investimentos'),
    ('lancamento de agua servida', 'Lançamento de água servida', 'Lançamento irregular e extravasamento'),
    ('lancamento de esgoto sem tratamento', 'Lançamento de esgoto sem tratamento', 'Lançamento irregular e extravasamento'),
    ('licencas ambientais', 'Licenças ambientais', 'Licenças e autorizações / Condicionantes ambientais / Fiscalização e autuações'),
    ('ligacao indevida na rede de esgoto', 'Ligação indevida na rede de esgoto', 'Lançamento irregular e extravasamento'),
    ('limpeza de rios', 'Limpeza de rios', 'Proteção de mananciais / Recuperação ambiental'),
    ('manutencao da rede de esgoto', 'Manutenção da rede de esgoto', 'Manutenção, interdições e transtornos urbanos'),
    ('manutencao de reservatorios', 'Manutenção de reservatórios', 'Plano de contingência e redundância'),
    ('mau atendimento na central', 'Mau atendimento na central', 'Atendimento ao cliente'),
    ('mau atendimento telefonico', 'Mau atendimento telefônico', 'Canais de atendimento'),
    ('mau cheiro na ete', 'Mau cheiro na ETE', 'Odor e incômodo'),
    ('modernizacao de equipamentos', 'Modernização de equipamentos', 'Gestão de ativos'),
    ('modernizacao do parque de hidrometros', 'Modernização do parque de hidrômetros', 'Medição e leitura'),
    ('monitoramento dos niveis de rios', 'Monitoramento dos níveis de rios', 'Plano de contingência e redundância'),
    ('movimento prospera', 'Movimento Prospera', 'Programas sociais e comunidade'),
    ('novos negocios', 'Novos negócios', 'Novos Negócios e Leilões'),
    ('obras de terceiros', 'Obras de terceiros', 'Acidentes e danos a terceiros'),
    ('oferta de vagas de trabalho', 'Oferta de vagas de trabalho', 'Geração de empregos / Contratação local / Capacitação profissional'),
    ('palestras educativas', 'Palestras educativas', 'Educação ambiental / Engajamento em saneamento e saúde / Uso consciente da água'),
    ('parceria com universidades', 'Parceria com universidades', 'Parcerias com universidades e startups'),
    ('participacao de acionistas', 'Participação de acionistas', 'Acionistas'),
    ('pedido de apoio social', 'Pedido de apoio social', 'Programas sociais e comunidade'),
    ('pedido de consumo consciente', 'Pedido de consumo consciente', 'Educação ambiental / Engajamento em saneamento e saúde / Uso consciente da água'),
    ('pedido de revisao contratual', 'Pedido de revisão contratual', 'Revisão e renovação de contratos'),
    ('plano verao', 'Plano Verão', 'Plano de contingência e redundância'),
    ('plantio de mudas', 'Plantio de Mudas', 'Proteção de mananciais / Recuperação ambiental'),
    ('premio de jornalismo ambiental', 'Prêmio de Jornalismo Ambiental', 'Prêmios, Projetos e incentivos à comunidade'),
    ('premio nacional de qualidade em saneamento', 'Prêmio Nacional de Qualidade em Saneamento', 'Prêmios, Projetos e incentivos à comunidade'),
    ('programa jovem aprendiz', 'Programa Jovem Aprendiz', 'Geração de empregos / Contratação local / Capacitação profissional'),
    ('programa portas abertas', 'Programa Portas Abertas', 'Programas sociais e comunidade'),
    ('programa respeito da o tom', 'Programa Respeito dá o Tom', 'Equidade, Diversidade e inclusão'),
    ('projeto pioneiros', 'Projeto Pioneiros', 'Programas sociais e comunidade'),
    ('projeto respeito as diferencas', 'Projeto Respeito às Diferenças', 'Equidade, Diversidade e inclusão'),
    ('prorrogacao no corte de agua', 'Prorrogação no Corte de Água', 'Inadimplência, Corte e religação'),
    ('ranking de reclamacoes no procon', 'Ranking de reclamações no Procon', 'Órgãos de defesa ao cliente (Ouvidoria, Procon, Reclame Aqui)'),
    ('reabertura de loja de atendimento', 'Reabertura de loja de atendimento', 'Canais de atendimento'),
    ('reajuste tarifario', 'Reajuste tarifário', 'Reajuste/ Revisão tarifária'),
    ('recomposicao asfaltica', 'Recomposição asfáltica', 'Pavimentação e recomposição'),
    ('regularidade no fornecimento de agua', 'Regularidade no fornecimento de água', 'Frequência, Continuidade'),
    ('relatorio anual de qualidade da agua', 'Relatório Anual de Qualidade da Água', 'Monitoramento e controle de qualidade da água'),
    ('religacao de agua', 'Religação de água', 'Inadimplência, Corte e religação'),
    ('repactuacao de contrato', 'Repactuação de Contrato', 'Reequilíbrio econômico-financeiro'),
    ('reparo de adutora', 'Reparo de adutora', 'Rompimento de adutora'),
    ('repasse de valores de leilao', 'Repasse de valores de leilão', 'Novos Negócios e Leilões'),
    ('reuniao com vereadores', 'Reunião com vereadores', 'Debate público versus privado'),
    ('rompimento de adutora', 'Rompimento de adutora', 'Rompimento de adutora'),
    ('roubo de hidrometros', 'Roubo de hidrômetros', 'Perdas, fraudes, furtos e ligações irregulares'),
    ('selo amiga do saneamento', 'Selo Amiga do Saneamento', 'Prêmios, Projetos e incentivos à comunidade'),
    ('tarifa de esgoto', 'Tarifa de esgoto', 'Estrutura e composição tarifária'),
    ('tarifa minima', 'Tarifa mínima', 'Estrutura e composição tarifária'),
    ('tarifa social', 'Tarifa Social', 'Tarifa social'),
    ('taxa de religacao de agua', 'Taxa de religação de água', 'Inadimplência, Corte e religação'),
    ('termo de ajustamento de conduta (tac)', 'Termo de Ajustamento de Conduta (TAC)', 'Investigações e Acordo'),
    ('treinamento de equipes', 'Treinamento de equipes', 'Atração e desenvolvimento'),
    ('universalizacao do saneamento', 'Universalização do saneamento', 'Universalização e metas de cobertura'),
    ('vazamento de agua', 'Vazamento de água', 'Perdas, fraudes, furtos e ligações irregulares'),
    ('visita tecnica', 'Visita técnica', 'Fiscalização regulatória'),
    ('vistoria tecnica em mananciais', 'Vistoria técnica em mananciais', 'Proteção de mananciais / Recuperação ambiental'),
    ('viveiro de mudas', 'Viveiro de Mudas', 'Proteção de mananciais / Recuperação ambiental')
  ) as v (chave, nome, tema_nome)
  join tema t on t.nome = v.tema_nome
    on conflict (nome_normalizado) do nothing;

commit;
