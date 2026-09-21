--: DESFAZ 0039: `categoria_publico.frente_padrao_id` NUNCA CHEGOU A SERVIR.
--:
--: `derivar_frente` (app/casos_de_uso/derivar_frente.py) passou a derivar a
--: Frente do TIPO da instituição — que já basta sozinho em todos os casos
--: menos "entidade" (Parceiros x Eventos, resolvido pelo Formato) — e não
--: mais da categoria de público. O tipo cobre inclusive os dois casos que a
--: categoria não tinha como cobrir: proposição (Legislativo) e credor
--: (Bancos/Credores), que não têm categoria de público nenhuma.
--:
--: Categoria de público continua existindo — é o campo informativo
--: "Público" da tela — só não participa mais da derivação, então esta
--: coluna fica sem uso nenhum.

alter table categoria_publico drop column if exists frente_padrao_id;
