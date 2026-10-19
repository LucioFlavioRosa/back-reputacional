--: O NOME QUE SAI NUMA FUSÃO VIRA APELIDO DO CADASTRO QUE FICA.
--:
--: O DEFEITO, achado na revisão da fusão com escolha de direção (PR #110): a
--: ingestão casa menção com cadastro por `nome_normalizado` EXATO
--: (`veiculos_da_imprensa.reconhecer`). Quando dois cadastros se fundem, o nome
--: de quem sai desaparece do banco — e o fornecedor continua mandando aquele
--: nome. Na subida seguinte ele não casa com nada, vira "veículo novo" e, se
--: alguém confirmar, NASCE DE NOVO: a duplicata que a pessoa acabou de resolver
--: volta, com as menções do mês indo para o cadastro recém-criado.
--:
--: NÃO É DEFEITO NOVO. Ele existe desde que a fusão existe — o que mudou é o
--: alcance: antes quem saía era quase sempre o perfil de rede (o handle
--: `valoreconomico`, que só a Bites manda), e agora quem decide a direção é
--: gente, então pode sair o nome que o clipping manda todo mês.
--:
--: O MESMO DESENHO DA 0099, de propósito: `unidade_negocio_apelido` resolveu
--: exatamente este problema para a concessionária ("Corsan" e "Companhia
--: Riograndense de Saneamento (Corsan)" são a mesma empresa em duas grafias).
--: Repetir o desenho é mais barato do que inventar um segundo jeito de dizer
--: "este nome também é aquele cadastro" — e quem já entendeu um entende o outro.
--:
--: A ORDEM DA BUSCA CONTINUA SENDO: cadastro exato primeiro, apelido depois. O
--: apelido nunca tira o nome de um cadastro VIVO, porque a busca exata responde
--: antes dele. Isso importa: dois cadastros podem ter o mesmo `nome_normalizado`
--: (a coluna não é única em `instituicao` — ALMG existe como entidade e como
--: órgão), e um apelido que vencesse a busca exata trocaria o ator.
--:
--: `on delete cascade` E NÃO `restrict`: o apelido é uma seta para o cadastro, e
--: seta para cadastro que não existe mais não é dado, é lixo. A fusão REAPONTA os
--: apelidos antes de apagar (`atores_duplicados.fundir`), então o cascade só
--: alcança o caminho que apaga instituição por outro motivo — e ali apagar é o
--: certo. O cascade roda com o privilégio do dono da tabela referenciada, então
--: ele não depende de `grant delete` para `painel_app`.
--:
--: PERMISSÃO: `select`, `insert` e `update` vêm do default ACL do schema, como
--: em toda tabela nova. `delete` é concedido EXPLICITAMENTE, e tem uma razão
--: estreita: quando o mesmo nome normalizado seria apelido de DOIS sobreviventes
--: diferentes, a fusão APAGA o apelido existente em vez de redirecioná-lo — nome
--: ambíguo não aponta para ninguém, e o conserto é a conferência da próxima
--: subida perguntar a gente. Sem este `grant`, essa fusão passaria em
--: desenvolvimento (superusuário) e quebraria só no ambiente implantado, que é a
--: armadilha registrada na memória deste projeto. `tests/test_papel_restrito.py`
--: conecta como `painel_app` de verdade e exercita os TRÊS verbos por isso.
--:
--: Idempotente.

begin;

create table if not exists instituicao_apelido (
    --: A CHAVE É O NOME JÁ NORMALIZADO (`dominio/texto.normalizar`: minúscula,
    --: sem acento, espaço colapsado) — a MESMA com que `reconhecer` procura o
    --: cadastro. Chave diferente da busca seria um apelido que nunca casa.
    nome_normalizado   text  primary key,
    --: A grafia como ela existia no cadastro que saiu, para a tela poder dizer
    --: "«Valor Econômico» agora é «valoreconomico»" em vez de mostrar a chave.
    nome               text  not null,
    --: O cadastro que FICOU.
    instituicao_id     uuid  not null
        references instituicao (id) on delete cascade,
    criado_em          timestamptz not null default now()
);

--: A BUSCA DE QUEM APONTA PARA UM CADASTRO acontece em toda fusão, para
--: reapontar os apelidos de quem sai. Sem índice, é varredura a cada fusão.
create index if not exists instituicao_apelido_por_instituicao
    on instituicao_apelido (instituicao_id);

--: Ver o cabeçalho: a fusão apaga o apelido que ficaria ambíguo.
grant delete on instituicao_apelido to painel_app;

comment on table instituicao_apelido is
    'Nome que já foi de um cadastro e hoje aponta para o que o absorveu. '
    'A ingestão o consulta DEPOIS da busca exata em instituicao.';

commit;
