# Painel Reputacional Aegea

O CRM das relações institucionais da Aegea: registra cada interação com a
imprensa, o poder público, investidores, parceiros e entidades, e lê o
conjunto delas como reputação. Este glossário vale para o back e para o
front (`front-reputacional`), que usam os mesmos nomes de propósito.

## Language

### O registro

**Interação**:
Um encontro registrado entre a Aegea e uma contraparte: reunião, entrevista,
evento, visita, manifestação formal. É a linha da Base e a unidade de todo
gráfico.
_Avoid_: agenda (fica só nos nomes internos do código), reunião (é um dos
tipos), registro

**Tipo de interação**:
Que espécie de encontro foi — Mídia, Agenda de mercado, Agenda pública,
Manifestação formal, Evento, Visita, Reunião. Escolhido por quem registra.
_Avoid_: formato (é outra coisa, ver abaixo), modalidade (essa é
presencial/online/híbrida)

**Frente**:
Quem é a contraparte, em oito famílias: Imprensa, Entidades (governo),
Parceiros, Eventos, Investidores, Agentes Públicos (legislativo), Interna,
Bancos/Credores. É DERIVADA pelo servidor do tipo da instituição (e do tipo
de interação, para Parceiros × Eventos); ninguém a escolhe.
_Avoid_: área (é a área da Aegea), público

**Formato**:
O detalhe de frente de Imprensa (entrevista, release, podcast…) e de
Investidores (roadshow, call de resultados…). Só existe dentro dessas duas
frentes.
_Avoid_: tipo de interação, tipo

**Área**:
A área da Aegea que conduziu a interação — Comunicação, Relações
Institucionais, Operações Financeiras, Relações com Investidores. Uma
interação pode ter mais de uma.
_Avoid_: frente, departamento

**Tema**:
O assunto de que a interação tratou (Tarifa, Biometano, Saneamento…). Uma
interação tem vários; é o que se filtra ao preparar uma agenda.
_Avoid_: tag (só no nome do parâmetro `tags`), assunto (nome antigo)

**Clima**:
Como a conversa foi — Proativo, Neutro ou Reativo. Há o clima esperado
(antes) e o clima registrado (depois).
_Avoid_: postura, sentimento, propositivo/tenso (códigos internos)

**Desfecho**:
Como a interação terminou — Avançou, Mantido, Recuou ou Sem definição.
_Avoid_: resultado (só no nome interno), status

**Situação**:
Onde a interação está no fluxo — Solicitado, Aceito ou Negado. Agrupa-se em
Resolvidos, Em aberto e Declinados para a taxa de resolutividade.
_Avoid_: status (só no nome interno)

**Relevância**:
O tier (1 a 4) da INSTITUIÇÃO, que a interação herda ao ser registrada.
_Avoid_: tier (só no nome interno), prioridade (é campo do legislativo)

### Com quem se fala

**Instituição**:
A contraparte institucional — órgão, veículo, entidade, investidor,
proposição, credor. Tem um tipo (derivado da categoria de público), uma
categoria de público, uma relevância e pessoas.
_Avoid_: entidade (é um dos tipos), stakeholder (aposentado), empresa

**Público**:
A categoria de público da instituição — as dez da taxonomia (Poder
Executivo, Imprensa e Formadores de Opinião, Mercado Financeiro…), com
subcategoria. É atributo da instituição, não da interação; é dele que nasce o
tipo.
_Avoid_: stakeholder, natureza do órgão (ambos aposentados pela taxonomia)

**Contato**:
Quem fala por uma instituição: nome, cargo, e-mail. Pertence a uma
instituição só.
_Avoid_: interlocutor (só no nome interno), pessoa, representante

**Representante Aegea**:
Quem fala pela Aegea numa interação; porta-voz quando conduz, equipe quando
acompanha. Tem uma área e os temas de que pode falar.
_Avoid_: pessoa Aegea (só no nome interno), porta-voz (é um dos papéis)

### O ciclo de vida de um cadastro

**Desativar / Reativar**:
Tirar de (ou devolver a) toda lista onde se escolhe — formulário de
interação, cadastro de contato — mantendo o histórico intacto. Vale para
instituição, contato, tema, referência e valores de dicionário. Uma
instituição desativada leva os contatos dela consigo, sem reescrevê-los.
_Avoid_: desligar (nome antigo de contato), arquivar, apagar

**Excluir**:
Apagar de vez o que entrou por engano. Só é permitido para quem nunca esteve
numa interação; para quem esteve, o gesto é Desativar.
_Avoid_: remover (nome antigo de contato), deletar

**Disponível**:
O contato que pode ser oferecido numa interação nova: ele ativo E a
instituição dele ativa.

### O que se lê

**Recorte**:
O conjunto de filtros em vigor — período, frente, área, tipo de interação,
público, instituição, tema, clima, desfecho, situação, relevância, esfera,
unidade, UF, busca. Mora no endereço; todo número, tabela e gráfico obedece
ao mesmo recorte, e o servidor é quem o aplica.
_Avoid_: filtro (é um campo do recorte), query, seleção

**Dicionário**:
Um vocabulário fechado que filtros e formulários oferecem (esferas, unidades
de negócio, climas…). Os ABERTOS a coordenação edita na Administração; os
FECHADOS são estrutura do modelo e mudam por código.
_Avoid_: enum, lista fixa, catálogo (o catálogo é o conjunto que o front
carrega)
