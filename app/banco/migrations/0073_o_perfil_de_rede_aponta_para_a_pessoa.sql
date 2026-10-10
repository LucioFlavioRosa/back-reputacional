--: O PERFIL DE REDE APONTA PARA A PESSOA DO CRM.
--:
--: O QUE ISTO HABILITA. A lente de redes sociais sabe que `stelafariasrs`
--: falou 27 vezes, e o CRM sabe que a deputada Stela Farias tem agendas — e as
--: duas metades não se falam. Com o vínculo, "o que este ator disse e fez em
--: todos os canais" passa a ser uma pergunta respondível.
--:
--: A CARDINALIDADE DECIDIU ONDE A COLUNA MORA. Um perfil é de no máximo UMA
--: pessoa; uma pessoa tem VÁRIOS perfis — medido no arquivo de 01–09/2026, 54
--: dos 1.173 autores aparecem em mais de uma rede. Então a chave estrangeira
--: fica no PERFIL apontando para a pessoa, e não o contrário.
--:
--: POR QUE NÃO PELO `interlocutor.redes_sociais`. Era o plano, e eu mudei: o
--: array de texto existe e está vazio nos 129 interlocutores, e ligar por
--: casamento de string repetiria o erro que esta base já mostrou duas vezes —
--: `mencao.tema_texto` com 25.909 textos e ZERO vínculos, e `unidade_texto`
--: com 58% dos nomes fora do cadastro. Texto como ligação apodrece; id, não.
--: `redes_sociais` continua sendo o que é: dado de contato, livre.
--:
--: E NÃO PELO `interlocutor.instituicao_id`. Esse campo diz DE QUEM a pessoa
--: fala — para a deputada, a Assembleia — e é o que a faz aparecer em "Pela
--: outra parte" nas agendas. Apontá-lo para o perfil de Instagram trocaria a
--: instituição dela por uma rede social, e ela sairia dos filtros do CRM.
--:
--: SÓ PERFIL DE REDE TEM PESSOA, e o CHECK garante: um jornal não é "de" uma
--: pessoa, e sem a trava alguém poria o editor da Folha como dono da Folha.
--:
--: `on delete set null`: apagar a pessoa do CRM não pode apagar o perfil nem
--: as 2.626 menções que apontam para ele. O perfil volta a ser anônimo, que é
--: o estado dele hoje.
--:
--: NASCE VAZIO, de propósito. São 1.108 perfis, e dizer de quem é cada um é
--: julgamento humano: `@casadevovodede` pode ser pessoa física, página de
--: bairro ou comércio. A curadoria vale nos 56 perfis com mais de cinco
--: menções, que é onde o volume está.
--:
--: Idempotente.

begin;

alter table instituicao
  add column if not exists interlocutor_id uuid references interlocutor (id) on delete set null;

alter table instituicao drop constraint if exists instituicao_pessoa_so_de_perfil;
alter table instituicao add constraint instituicao_pessoa_so_de_perfil check (
  interlocutor_id is null or tipo = 'perfil_rede'
);

--: PARCIAL, porque a esmagadora maioria das 2.731 instituições não tem pessoa:
--: índice cheio guardaria 2.731 nulos para servir a busca dos que têm.
create index if not exists instituicao_por_interlocutor
  on instituicao (interlocutor_id)
  where interlocutor_id is not null;

do $$
begin
    if not exists (
        select 1 from information_schema.columns
         where table_name = 'instituicao' and column_name = 'interlocutor_id'
    ) then
        raise exception 'a coluna interlocutor_id não entrou';
    end if;
    raise notice 'o perfil de rede pode apontar para a pessoa do CRM';
end $$;

commit;
