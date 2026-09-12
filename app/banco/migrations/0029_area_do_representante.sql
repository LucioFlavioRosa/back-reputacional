--: A ÁREA DE QUEM REPRESENTA A AEGEA.
--:
--: `pessoa_aegea` já distinguia porta-voz de equipe — quem fala pela
--: companhia e quem acompanha. Faltava dizer DE ONDE essa pessoa fala:
--: Comunicação, Relações Institucionais, Operações Financeiras, Performance
--: e Dados, Relações com Investidores.
--:
--: UM DICIONÁRIO, e não uma coluna de texto livre — é o mesmo padrão de
--: `esfera`/`relevancia` em `tabelas_catalogo.py` (ver `0001_fundacao.sql`):
--: a coordenação muda os valores por `insert`/`update`, sem migration, e o
--: front não precisa de lista fixa nenhuma — sai de `GET /api/dicionarios`
--: como qualquer outro vocabulário.
--:
--: Anulável, e sem preenchimento retroativo: quem já está cadastrado não tem
--: área até alguém editar.
--:
--: Idempotente.

begin;

create table if not exists area_pessoa (
  id smallserial primary key, codigo text not null unique, nome text not null,
  ordem smallint not null, ativo boolean not null default true
);

insert into area_pessoa (codigo, nome, ordem) values
  ('comunicacao',             'Comunicação',               1),
  ('relacoes_institucionais', 'Relações Institucionais',   2),
  ('operacoes_financeiras',   'Operações Financeiras',     3),
  ('performance_e_dados',     'Performance e Dados',       4),
  ('relacoes_investidores',   'Relações com Investidores', 5)
on conflict (codigo) do nothing;

alter table pessoa_aegea add column if not exists area_id smallint references area_pessoa(id);

comment on column pessoa_aegea.area_id is
  'A área de quem representa a Aegea. Nula em quem foi cadastrado antes desta coluna existir.';

commit;
