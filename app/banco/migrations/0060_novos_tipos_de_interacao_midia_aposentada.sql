--: NOVOS TIPOS DE INTERAÇÃO + "MÍDIA" APOSENTADO.
--:
--: Dois tipos novos em `formato_interacao`: "Encontro de relacionamento"
--: (contato informal de manutenção de relacionamento, sem pauta formal) e
--: "Solicitação de Posicionamento/Entrevista" (pedido direto de jornalista
--: ou veículo por posicionamento ou entrevista). O segundo também vira o
--: NOVO PADRÃO da frente Imprensa em `formato_das_interacoes_pela_frente`
--: (`app/dominio/frentes.py`, `FORMATO_PADRAO_DA_FRENTE`), substituindo
--: "Mídia" — e a 0044 foi atualizada para continuar espelhando o mapa.
--:
--: "MÍDIA" APOSENTADO, NÃO APAGADO: `ativo = false`, mesmo padrão de `0058`
--: para os temas antigos — preserva o histórico de toda interação já
--: classificada como Mídia (FK intacta), só tira do formulário de cadastro.
--:
--: Idempotente.

begin;

insert into formato_interacao (codigo, nome, ordem) values
  ('encontro_relacionamento', 'Encontro de relacionamento', 10),
  ('solicitacao_posicionamento_entrevista', 'Solicitação de Posicionamento/Entrevista', 11)
on conflict (codigo) do nothing;

update formato_interacao set ativo = false where codigo = 'midia';

commit;
