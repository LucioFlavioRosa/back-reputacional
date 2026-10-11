--: A PENDÊNCIA DE REVISÃO DIZ POR QUÊ.
--:
--: PEDIDO DO DONO DO PRODUTO (11/10/2026), depois de subir a planilha real de
--: relações com investidores e receber uma recusa:
--:
--:   "Artur Santa, Michelle Nasser Vaz Lauande, Nikolau Muller, Paulo Hanaoka
--:   aparece em agendas de instituições diferentes, e um interlocutor pertence a
--:   uma só. Cadastre-o pela tela de Administração e aponte para ele na
--:   conferência."
--:
--:   "Nesse caso a mensagem está correta, mas não era para impedir subir: era
--:   transformar isso em um alerta para revisão na aba correspondente de
--:   cadastro."
--:
--: MEDIDO NA PLANILHA DELE: 304 linhas, 321 pessoas distintas, e EXATAMENTE
--: QUATRO aparecem em duas instituições cada. O arquivo inteiro era recusado por
--: causa delas — 300 agendas barradas por 4 nomes.
--:
--: E OS QUATRO CASOS SÃO DADO REAL, não erro de digitação:
--:
--:     Artur Santa ................ Banco XP (114) e XP Asset (245)
--:     Nikolau Muller ............. JGP Gestão (56) e Leto Capital (289)
--:     Michelle Nasser Vaz Lauande  Itaú International PB (252) e Santander (255)
--:     Paulo Hanaoka .............. Itaú International PB (252) e Santander (255)
--:
--: O primeiro é o mesmo grupo (XP) em dois braços; o segundo parece mudança de
--: casa; os dois últimos estão nas MESMAS duas linhas, que é a assinatura de uma
--: reunião conjunta ou de uma linha copiada.
--:
--: `motivo_da_revisao`, E NÃO SÓ O BOOLEANO. A `0085` criou
--: `pendente_de_revisao`, e com ele a aba lista o registro — mas quem abre a aba
--: não sabe POR QUE aquele cadastro está lá. "Apareceu em duas instituições na
--: planilha" é a informação que torna a revisão possível em vez de um convite a
--: adivinhar.
--:
--: TEXTO E NÃO CÓDIGO, de propósito. Um enum obrigaria a prever os motivos, e o
--: motivo é uma frase para gente ler — a mesma escolha que `ator_distinto.motivo`
--: já fez, e pela mesma razão: "é conhecimento sobre o mundo, não estado de
--: interface".
--:
--: NULO É "NASCEU DE PLANILHA", sem mais nada a dizer: é o caso comum, e exigir
--: uma frase ali encheria a coluna de ruído repetido.
--:
--: Idempotente.

begin;

alter table instituicao  add column if not exists motivo_da_revisao text;
alter table interlocutor add column if not exists motivo_da_revisao text;
alter table tema         add column if not exists motivo_da_revisao text;
alter table pessoa_aegea add column if not exists motivo_da_revisao text;

do $$
begin
    raise notice 'motivo_da_revisao nas quatro tabelas da fila de revisao';
end $$;

commit;
