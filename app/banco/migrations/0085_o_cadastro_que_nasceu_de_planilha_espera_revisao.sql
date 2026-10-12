--: O CADASTRO QUE NASCEU DE PLANILHA ESPERA REVISÃO.
--:
--: PEDIDO DO DONO DO PRODUTO (11/10/2026):
--:
--:   "Quando subirmos uma base que tenha algum ponto de conferência de cadastro,
--:   pode subir sem problemas. Porém, dentro de cada uma das 3 abas de Cadastro
--:   compartilhado, deve existir uma aba específica para cadastros que precisam
--:   ser revisados para serem consolidados na base de instituições/contatos,
--:   temas e representantes da Aegea. Assim o profissional consegue subir a
--:   planilha sem problemas e pode revisar depois — e inclusive pode ser trabalho
--:   de outra pessoa. Queremos dar padronização, mas com menor impacto."
--:
--: QUATRO TABELAS PARA TRÊS ABAS, e o mapa é exato: "Instituições e Contatos" é
--: `instituicao` + `interlocutor`, "Temas" é `tema`, "Representantes Aegea" é
--: `pessoa_aegea`. São também, e não por coincidência, os QUATRO cadastros que a
--: importação de agendas sabe criar (`VOCABULARIOS_QUE_A_IMPORTACAO_CRIA`).
--:
--: POR QUE UMA COLUNA E NÃO UMA DERIVAÇÃO. Eu tentei derivar "precisa de revisão"
--: da incompletude do cadastro, que teria a virtude de se apagar sozinho. A medida
--: matou a ideia: das 99 instituições que aparecem em agendas, só 58 têm categoria
--: de público — a ausência é o ESTADO NORMAL do CRM, e a fila nasceria com 250 das
--: 544 agendas dentro. Uma fila que nasce cheia de registro antigo não é fila, é
--: ruído, e ruído é o que faz ninguém olhar (é o argumento da `0078`).
--:
--: O QUE DISTINGUE NÃO É A INCOMPLETUDE, É A PROCEDÊNCIA: este registro nasceu de
--: uma planilha e ninguém o consolidou ainda. Isso não se deriva de campo nenhum;
--: é um fato sobre a vida do registro.
--:
--: `default false` E A FILA NASCE VAZIA. Os 3.785 cadastros de instituição, 129 de
--: interlocutor, 149 de tema e 12 de pessoa da Aegea que já existem não entram:
--: eles foram feitos por gente, ou já foram conferidos na tela de ingestão. A fila
--: só cresce com o que entrar de agora em diante — que é o "menor impacto" do
--: pedido.
--:
--: SAI POR AÇÃO DE QUEM REVISA, e não por um campo ficar preenchido. "Consolidar"
--: é uma decisão: a pessoa olhou o registro e disse que ele está bom para a base.
--: Ligar a saída a um campo faria a fila esvaziar sozinha com um preenchimento
--: parcial, e ninguém teria dito nada.
--:
--: NÃO É `ativo`, e a diferença importa: `ativo=false` é "este cadastro saiu de
--: circulação", decisão de quem administra, e ele desaparece das listas e das
--: lentes. O que nasce de planilha está EM circulação — a menção aponta para ele,
--: a agenda existe — e só falta alguém conferir o enquadramento. Usar `ativo`
--: esconderia o dado que acabou de entrar.
--:
--: Idempotente.

begin;

alter table instituicao
    add column if not exists pendente_de_revisao boolean not null default false;

alter table interlocutor
    add column if not exists pendente_de_revisao boolean not null default false;

alter table tema
    add column if not exists pendente_de_revisao boolean not null default false;

alter table pessoa_aegea
    add column if not exists pendente_de_revisao boolean not null default false;

--: ÍNDICE PARCIAL, e só do lado `true`: a fila é sempre "mostre os pendentes", e
--: num cadastro de 3.785 linhas com (hoje) zero pendentes, um índice cheio seria
--: 3.785 entradas para responder nada. O parcial custa o tamanho da fila.
create index if not exists instituicao_pendente_de_revisao_idx
    on instituicao (pendente_de_revisao) where pendente_de_revisao;

create index if not exists interlocutor_pendente_de_revisao_idx
    on interlocutor (pendente_de_revisao) where pendente_de_revisao;

create index if not exists tema_pendente_de_revisao_idx
    on tema (pendente_de_revisao) where pendente_de_revisao;

create index if not exists pessoa_aegea_pendente_de_revisao_idx
    on pessoa_aegea (pendente_de_revisao) where pendente_de_revisao;

do $$
declare
    pendentes int;
begin
    select (select count(*) from instituicao where pendente_de_revisao)
         + (select count(*) from interlocutor where pendente_de_revisao)
         + (select count(*) from tema where pendente_de_revisao)
         + (select count(*) from pessoa_aegea where pendente_de_revisao)
      into pendentes;

    --: DEVE SER ZERO na primeira subida: a coluna nasce `false` para todo mundo, e
    --: é isso que faz a fila começar vazia em vez de pedir revisão de tudo.
    raise notice 'cadastros pendentes de revisao: % (esperado 0 na primeira subida)',
        pendentes;
end $$;

commit;
