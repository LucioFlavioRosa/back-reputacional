--: A TRILHA DA MENÇÃO DEIXA DE IMPEDIR QUE A MENÇÃO SEJA APAGADA.
--:
--: O DEFEITO, E ELE ESTÁ NO AR. A `0101` criou `mencao_auditoria.mencao_id`
--: com `references mencao(id)` e SEM `on delete cascade`, e pôs um gatilho
--: `after update on mencao FOR EACH ROW` que audita TODA coluna que muda
--: (genérico "campo a campo", só ignorando `id` e `criado_em`).
--:
--: As duas coisas juntas fecham a porta: qualquer UPDATE numa menção cria linha
--: de trilha, e a partir daí aquela menção NÃO PODE MAIS SER APAGADA.
--:
--:     ForeignKeyViolation: update or delete on table "mencao" violates
--:     foreign key constraint "mencao_auditoria_mencao_id_fkey"
--:
--: E QUEM APAGA MENÇÃO É A SUBIDA MENSAL. `ingerir_mencoes.regravar` substitui
--: o mês: apaga as menções daquele mês e grava as novas. Então basta alguém ter
--: tocado uma menção para a PRÓXIMA SUBIDA DAQUELE MÊS falhar inteira.
--:
--: QUEM TOCA MENÇÃO HOJE, e nenhum deles é hipótese:
--:   * `atores_duplicados.fundir` — a fila de duplicados move as menções do
--:     cadastro que sai (`update mencao set instituicao_id = ...`). Está no ar
--:     desde 11/10;
--:   * `ligar_mencoes_a_concessionaria` e `ligar_mencoes_a_taxonomia`, os
--:     backfills, que atualizam dezenas de milhares de linhas;
--:   * a edição do jornalista, que é o motivo de a `0101` existir.
--:
--: MEDIDO: um `update` numa menção cria 1 linha de trilha, e o `delete` seguinte
--: volta `ForeignKeyViolation`. A suíte não pegava porque nenhum teste
--: ATUALIZAVA e depois APAGAVA a mesma menção.
--:
--: A ESCOLHA: TIRAR A CHAVE ESTRANGEIRA, e não trocá-la por `on delete cascade`.
--:
--: As duas destravam o `delete`. A diferença é o que acontece com a história:
--: com `cascade`, a trilha de uma menção some na próxima subida do mês — e uma
--: trilha que se apaga sozinha numa operação de rotina não é trilha. Sem a
--: chave, a linha fica: ela registra que ALGUÉM mudou aquele campo naquele dia,
--: com o `id` servindo de chave histórica, mesmo depois de a menção ter sido
--: substituída.
--:
--: `mencao` É EFÊMERA POR DESENHO — toda subida troca o mês inteiro, com `id`
--: novo —, e chave estrangeira para uma linha efêmera é a forma errada para uma
--: trilha. A `interacao_auditoria` da `0005` não tem este problema porque
--: interação some por `arquivado_em`, e não por `delete`.
--:
--: O QUE ISTO NÃO CONSERTA, e é assunto de produto: a edição manual do
--: jornalista é perdida na próxima subida do mês, porque as linhas são
--: substituídas. A trilha passa a sobreviver ao que ela registra; a EDIÇÃO, não.
--:
--: Idempotente.

begin;

alter table mencao_auditoria
  drop constraint if exists mencao_auditoria_mencao_id_fkey;

comment on column mencao_auditoria.mencao_id is
  'A menção que mudou, SEM chave estrangeira: `mencao` é substituída inteira a '
  'cada subida do mês, e uma trilha que some junto não é trilha. Ver 0103.';

do $$
begin
    if exists (
        select 1
          from pg_constraint
         where conname = 'mencao_auditoria_mencao_id_fkey'
    ) then
        raise exception 'a chave estrangeira da trilha continua de pé';
    end if;
end $$;

commit;
