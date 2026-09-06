--: O E-MAIL DE QUEM FALA PELA AEGEA.
--:
--: `interlocutor` ganhou e-mail na 0014, pelo mesmo motivo que vale aqui:
--: articular uma agenda começa por escrever para alguém, e esse endereço vivia
--: fora do sistema.
--:
--: `pessoa_aegea` tinha nome, cargo e a marca de porta-voz. Quem monta a agenda
--: precisa acionar a pessoa da casa que vai falar, e procurava o endereço no
--: catálogo corporativo — fora daqui, e sem garantia de ser o certo.
--:
--: Anulável e sem preenchimento retroativo, como os anteriores.
--:
--: Idempotente.

begin;

alter table pessoa_aegea add column if not exists email text;

comment on column pessoa_aegea.email is
  'Como se aciona a pessoa da casa. Nulo no que veio da planilha.';

commit;
