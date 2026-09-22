# A alegação é uma entidade própria, e não um campo da consulta

Investidores e bancos mandam questionários cuja pergunta já dá algo como
fato — "como a companhia trata a possibilidade de o Banco X não renegociar a
dívida?". O sinal de mercado não é o e-mail: é a premissa, e ela só significa
alguma coisa quando se repete. Guardá-la como texto dentro da consulta
responderia "o que perguntaram" e nunca "quantas instituições diferentes
perguntaram a mesma coisa em quinze dias", que é a pergunta que existe para
ser respondida.

Por isso `alegacao` é tabela, com vínculo N:N para as consultas, índice único
sobre o texto normalizado (duas grafias da mesma frase partiriam a contagem em
duas) e um status de apuração próprio — a mesma premissa é apurada uma vez, e
não uma vez por e-mail.

O custo aceito é o atrito: quem registra a consulta precisa escolher uma
alegação existente ou criar uma, em vez de digitar texto livre. É o mesmo
atrito de tema e instituição, e pela mesma razão.

A consulta, por sua vez, entra como TIPO DE INTERAÇÃO (`formato_interacao`) e
não como frente: quem manda continua sendo um credor, um investidor ou um
veículo, e a frente segue derivada do tipo da instituição (ADR 0001). O bloco
1-1 `interacao_consulta` convive com a extensão da frente em vez de disputar o
lugar dela — uma consulta de banco é frente `bancos_credores`, que já usa a
extensão institucional.

Chamamos de "alegação", e não de "boato": a premissa pode proceder, e
registrar que uma instituição espalha boatos é uma afirmação com consequência
jurídica feita a partir de um e-mail que pode ser diligência honesta. A tela
mostra convergência; a conclusão é de quem lê.
