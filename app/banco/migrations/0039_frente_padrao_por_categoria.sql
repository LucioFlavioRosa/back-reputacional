--: FRENTE PADRÃO POR CATEGORIA DE PÚBLICO.
--:
--: A tela deixa de perguntar Frente diretamente: quem registra escolhe o
--: Formato da interação (Mídia, Reunião...) e a instituição, e o backend
--: DERIVA a Frente sozinho — ver `app/casos_de_uso/derivar_frente.py`.
--:
--: A REGRA, EM ORDEM:
--:   1. Instituição do tipo `area_interna` → sempre Interna.
--:   2. Formato "Evento" → sempre Eventos (bate 1 pra 1 com o que a frente já
--:      significa hoje; não depende de quem é a contraparte).
--:   3. Senão, esta coluna: a categoria de público da instituição decide.
--:
--: POR QUE NÃO É COLUNA EM `interacao`: a mesma razão de `area_dona_id` (ver
--: `0036_categoria_de_publico.sql`) — é metadado da CATEGORIA, não do
--: encontro. Uma reunião com o Ministério da Fazenda deriva pra "Entidades"
--: hoje e continuaria derivando pra "Entidades" amanhã, sem essa tabela
--: precisar saber de agenda nenhuma.
--:
--: "PODER LEGISLATIVO" APONTA PARA ENTIDADES, NÃO PARA A FRENTE
--: `legislativo`: essa frente é mais estreita do que "instituição do
--: Legislativo" — tem campos próprios de ACOMPANHAMENTO DE PROPOSIÇÃO (Casa,
--: Tramitação, Ementa). Uma reunião comum com um parlamentar não é isso;
--: vira Entidades como qualquer outro órgão público. Acompanhar uma
--: proposição continua existindo, só não é algo que se derive
--: automaticamente daqui — decisão confirmada com o usuário.
--:
--: "MERCADO FINANCEIRO E DE CAPITAIS" SEMPRE VIRA INVESTIDORES, mesmo a
--: subcategoria "Dívida, crédito, equity e acionistas" (que em tese também
--: cobre bancos credores). Simplificação deliberada: a distinção fina entre
--: Investidores e Bancos/Credores continua existindo só por escolha manual,
--: fora desta derivação — refinar isso depende de olhar a subcategoria, não
--: só a categoria, e fica para depois se um dia importar.
--:
--: NULA SÓ EM QUEM AINDA NÃO FOI MAPEADO (não deveria acontecer, com as 10
--: linhas de `0036` todas cobertas aqui) — `derivar_frente` recusa com erro
--: claro em vez de adivinhar.
--:
--: Idempotente.

begin;

alter table categoria_publico add column if not exists frente_padrao_id smallint references frente(id);

update categoria_publico set frente_padrao_id = (select id from frente where codigo = 'governo')
  where codigo in (
    'poder_executivo', 'poder_legislativo', 'poder_judiciario',
    'controle_fiscalizacao', 'reguladores'
  );

update categoria_publico set frente_padrao_id = (select id from frente where codigo = 'investidores')
  where codigo = 'mercado_financeiro_capitais';

update categoria_publico set frente_padrao_id = (select id from frente where codigo = 'imprensa')
  where codigo = 'imprensa_formadores_opiniao';

update categoria_publico set frente_padrao_id = (select id from frente where codigo = 'parceiros')
  where codigo in (
    'entidades_setoriais_representativas', 'sociedade_civil_comunidade',
    'parceiros_cadeia_valor'
  );

comment on column categoria_publico.frente_padrao_id is
  'A Frente derivada para interações com instituições desta categoria, quando o Formato não decide sozinho (Evento sempre vira Eventos, direto). "Poder Legislativo" aponta para Entidades — a frente legislativo é só para acompanhamento de proposição, não deriva daqui.';

commit;
