--: AJUSTES NA TAXONOMIA DE PÚBLICOS (0036), a partir da planilha de
--: referência que só chegou depois daquela migration já estar aplicada
--: (inclusive no banco de dev do Azure).
--:
--: NÃO EDITA A 0036 — só corrige o que ela deixou incompleto, com
--: `insert`/`update`, o mesmo padrão de correção que `0033`/`0035` já usaram
--: neste banco.
--:
--: DUAS MUDANÇAS:
--:
--: 1. "Imprensa e Formadores de Opinião" ganha a subcategoria que faltava —
--:    "Municipal / local" — entre "Regional das concessões" e "Setorial e
--:    formadores de opinião", que é a ordem da planilha. A antiga posição 4
--:    (setorial) sobe pra 5.
--:
--: 2. "Entidades Setoriais e Representativas" deixa de ser "sem_quebra": a
--:    planilha mostra que ela SE SUBDIVIDE, em "Institutos e Associações"
--:    (ABCON, AESBE, CNI, FIESP...) e "Academias". Muda o `padrao_de_quebra`
--:    para `logica_de_relacao` — mesmo padrão de "Controle e Fiscalização" e
--:    "Sociedade Civil e Comunidade", que também quebram por tipo de
--:    relação, não por esfera geográfica nem por posição de capital.
--:
--: "Parceiros e Cadeia de Valor" FICA COMO ESTÁ (sem_quebra): a planilha
--: lista uma única subcategoria ali ("Parceiros e fornecedores
--: estratégicos"), e uma subcategoria sem alternativa nenhuma não dá opção
--: real pra quem cadastra — decisão confirmada, não é omissão.
--:
--: Idempotente.

begin;

update categoria_publico
  set padrao_de_quebra = 'logica_de_relacao'
  where codigo = 'entidades_setoriais_representativas';

update subcategoria_publico
  set ordem = 5
  where categoria_publico_id = (select id from categoria_publico where codigo = 'imprensa_formadores_opiniao')
    and codigo = 'setorial_formadores_opiniao';

insert into subcategoria_publico (categoria_publico_id, codigo, nome, ordem) values
  ((select id from categoria_publico where codigo = 'imprensa_formadores_opiniao'),
    'municipal_local', 'Municipal / local', 4),

  ((select id from categoria_publico where codigo = 'entidades_setoriais_representativas'),
    'institutos_e_associacoes', 'Institutos e Associações', 1),
  ((select id from categoria_publico where codigo = 'entidades_setoriais_representativas'),
    'academias', 'Academias', 2)
on conflict (categoria_publico_id, codigo) do nothing;

commit;
