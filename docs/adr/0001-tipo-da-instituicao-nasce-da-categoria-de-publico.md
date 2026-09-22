# O tipo da instituição nasce da categoria de público; a frente nasce do tipo

A tela de cadastro deixou de perguntar o Tipo da instituição (órgão, veículo,
entidade, investidor, proposição, área interna, credor) e passou a perguntar
só a categoria de público; o servidor deriva o tipo dela
(`TIPO_DA_CATEGORIA_DE_PUBLICO`, `casos_de_uso/derivar_tipo.py`) e, da
interação, deriva a frente pelo tipo (`derivar_frente.py`). Escolhemos
manter o TIPO gravado — em vez de derivar a frente direto da categoria —
porque a taxonomia não distingue duas coisas que a frente precisa distinguir:
banco credor de investidor (ambos em "Mercado Financeiro e de Capitais") e
área interna (que não é público de nenhum). O tipo continua editável na
Administração justamente para esses casos; `0039`/`0040` tentaram uma frente
padrão por categoria e voltaram atrás pelo mesmo motivo.

**Consequências:** tipo informado vale mais que a categoria; criação sem tipo
e sem categoria é recusada; uma categoria nova na taxonomia exige entrada no
mapa (o teste dos dicionários acusa a falta).
