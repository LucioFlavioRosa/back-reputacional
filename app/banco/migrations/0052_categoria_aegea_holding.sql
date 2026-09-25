--: "AEGEA HOLDING" — 11ª CATEGORIA DE PÚBLICO, a partir da planilha de
--: referência (mesma fonte da 0037). Cobre reunião interna de alto nível —
--: conselho, comitê executivo, alinhamento estratégico — que hoje não tinha
--: onde entrar na taxonomia.
--:
--: `sem_quebra`, mesmo padrão de "Poder Judiciário" e "Parceiros e Cadeia de
--: Valor": a planilha repete o nome da categoria na coluna de subdivisão, o
--: mesmo formato que ela usa pra dizer "isto não quebra".
--:
--: `area_dona_id` nulo, mesmo motivo de "Parceiros e Cadeia de Valor":
--: nenhuma das cinco áreas cadastradas (Comunicação, Relações
--: Institucionais, Operações Financeiras, Performance e Dados, Relações com
--: Investidores) é dona natural de reunião de conselho/comitê — decisão
--: confirmada com o usuário, não omissão.
--:
--: Idempotente.

begin;

insert into categoria_publico (codigo, nome, padrao_de_quebra, area_dona_id, ordem) values
  ('aegea_holding', 'Aegea Holding', 'sem_quebra', null, 11)
on conflict (codigo) do nothing;

commit;
