--: Cada carga de fonte deixa uma linha: qual fonte, de que arquivo, quem mandou,
--: quantas menções entraram e quais meses foram substituídos.
--:
--: POR QUE NÃO DAVA PARA RESPONDER ANTES. "Quando esta base foi atualizada"
--: parecia estar em `max(score_mes_fonte.atualizado_em)`, e não está: `regravar`
--: APAGA os meses do arquivo e insere um agregado por (mês, sentimento, tier) —
--: uma carga legítima de ZERO menção apaga e não insere nada, então o `max` não
--: anda e a tela diria "atualizado há 40 dias" depois de uma carga feita hoje.
--: É o caso do recorte por lista que não acha veículo nenhum, exercitado por
--: `tests/test_conferencia_da_planilha_do_score.py`. E "quem atualizou" não
--: estava em lugar nenhum: `planilha_recebida` tem `criado_por`, mas a linha é
--: apagada na confirmação (`planilha_do_score.descartar`).
--:
--: POR QUE NÃO SE CHAMA `*_auditoria`. `test_nenhuma_trilha_e_gravavel_pela_
--: aplicacao` varre toda tabela com esse sufixo e exige que `painel_app` não
--: tenha `insert`. Aqui quem escreve É a aplicação, e tem de ser: um gatilho vê
--: linhas mudando, não "este arquivo, mandado por esta pessoa, alimentou estas
--: fontes irmãs" — e não distingue carga de reconciliação. Então o nome fica
--: fora do sufixo e a imutabilidade vem do `revoke` explícito lá embaixo, mais
--: `test_carga_de_fonte_nao_e_alteravel_pela_aplicacao`.
--:
--: SEM `check` EM `origem` de propósito: origem nova é chamador novo, não
--: migration nova. A lista vivida está em `ingerir_mencoes.ORIGENS`.
--:
--: Idempotente.

begin;

create table if not exists carga_de_fonte (
  id           uuid        primary key default gen_random_uuid(),
  fonte_id     smallint    not null references score_fonte(id),
  --: O nome que a pessoa reconhece. Nulo onde o chamador não tem nome de
  --: arquivo para dar — `ingerir` recebe bytes, não arquivo.
  arquivo      text,
  --: Nulo é o normal no comando de linha. Nulo COM `origem` preenchida é a
  --: assinatura de carga feita fora da aplicação — mesma convenção da `0005`.
  usuario_id   uuid        references usuario(id),
  --: A rota ou o comando que mandou gravar.
  origem       text        not null,
  --: JUNTA AS FONTES IRMÃS do mesmo arquivo, sem tabela-pai: a carga já é por
  --: fonte (é assim que `planilha_recebida.fonte_id` também é), e um pai só
  --: guardaria o nome do arquivo de novo. Uma subida da Clipei alimenta
  --: Imprensa e Mercado e rende duas linhas com o mesmo `lote_id`.
  lote_id      uuid        not null,
  --: ZERO É RESULTADO VÁLIDO, e é a razão de esta tabela existir.
  mencoes      integer     not null,
  --: Os meses SUBSTITUÍDOS, inclusive os que ficaram zerados.
  meses        date[]      not null,
  concluida_em timestamptz not null default now()
);

comment on table carga_de_fonte is
  'Uma linha por (carga, fonte). Append-only pela aplicação: ver os revokes na '
  '0115. A existência da linha é o sucesso — carga que estourou faz rollback e '
  'não deixa linha, e tentativa/falha é observabilidade, não linhagem.';

comment on column carga_de_fonte.mencoes is
  'Quantas menções a carga gravou. ZERO é válido e é o caso que torna esta '
  'tabela necessária: o agregado do mês é apagado e nada é inserido.';

--: A última carga de cada fonte, que é a pergunta da tela.
create index if not exists carga_de_fonte_fonte_concluida_idx
  on carga_de_fonte (fonte_id, concluida_em desc);
--: A lista cronológica da aba da plataforma.
create index if not exists carga_de_fonte_concluida_idx
  on carga_de_fonte (concluida_em desc);

--: A tabela NASCE GRAVÁVEL por causa do `alter default privileges` da `0009`,
--: que concede `select, insert, update` em toda tabela futura a `painel_app`.
--: `insert` é o que queremos; `update` não. `delete` nunca é concedido por
--: default, e o revoke está aqui para dizer que é intencional, não esquecimento.
revoke update, delete on carga_de_fonte from painel_app;
grant  select, insert  on carga_de_fonte to painel_app;

do $$
declare
    indevidos text;
begin
    select string_agg(p, ', ' order by p) into indevidos
      from unnest(array['UPDATE', 'DELETE']) as p
     where has_table_privilege('painel_app', 'carga_de_fonte', p);

    if indevidos is not null then
        raise exception
            'painel_app ainda pode % em carga_de_fonte: a trilha nao e append-only',
            indevidos;
    end if;

    if not has_table_privilege('painel_app', 'carga_de_fonte', 'INSERT') then
        raise exception
            'painel_app nao pode inserir em carga_de_fonte: quem escreve a '
            'trilha e a aplicacao, nao um gatilho';
    end if;

    raise notice 'carga_de_fonte criada, gravavel so por insert';
end $$;

commit;
