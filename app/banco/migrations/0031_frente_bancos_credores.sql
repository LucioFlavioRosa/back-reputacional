--: OITAVA FRENTE: BANCOS/CREDORES. E dois rótulos renomeados.
--:
--: `codigo` de 'governo' e 'legislativo' NÃO mudam — são o que `app/dominio/
--: frentes.py` (`Frente` StrEnum), as regras de extensão e o front usam para
--: reconhecer cada frente. Só o `nome` (o rótulo que a tela mostra) muda,
--: mesmo padrão de `0030_clima_proativo_reativo.sql`.
--:
--: A frente nova precisa TAMBÉM de `app/dominio/frentes.py` atualizado
--: (`Frente.BANCOS_CREDORES`, `TIPO_DE_INSTITUICAO`, `EXTENSAO_POR_FRENTE`) —
--: a linha no dicionário sozinha não basta, porque `frente` é validada como
--: enum Python na entrada da API. Ver o commit que trouxe esta migration.
--:
--: NOVO TIPO DE INSTITUIÇÃO: 'credor', para as próprias instituições
--: (bancos, credores) com quem esta frente conversa — não é 'investidor'
--: porque a relação é de crédito/dívida, não de mercado de capitais, e
--: misturar as duas confundiria o filtro de instituições de cada frente
--: (`instituicoesDaFrente`, no front). Por isso a CHECK de `instituicao.tipo`
--: também precisa alargar.
--:
--: Idempotente: `insert ... on conflict do nothing`, `update` que já fixa o
--: mesmo valor não muda nada, e o `drop constraint if exists` antes de
--: recriar a CHECK tolera rodar de novo.

begin;

insert into frente (codigo, nome, cor_hex, ordem) values
  ('bancos_credores', 'Bancos/Credores', '#FF8FE1', 8)
on conflict (codigo) do nothing;

update frente set nome = 'Entidades'        where codigo = 'governo';
update frente set nome = 'Agentes Públicos' where codigo = 'legislativo';

alter table instituicao drop constraint if exists instituicao_tipo_check;
alter table instituicao add constraint instituicao_tipo_check check (tipo in (
  'veiculo', 'orgao', 'entidade', 'escritorio',
  'investidor', 'proposicao', 'area_interna', 'credor'
));

commit;
