const AREAS = {
  Imprensa: '#0027BD',
  Governo: '#17E3CB',
  Parceiros: '#A11FFF',
  Eventos: '#FE952B',
  Investidores: '#E12379',
  Legislativo: '#F8DC00',
  Interna: '#8C91A4'
};

const PORTAVOZ = ['Radamés Casseb','André Pires','Édison Carlos','Márcia Costa','Andréa Melo','Letícia Novaes'];

const MESES = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];

const UNID_POR_REGISTRO = {
  2: 'Corsan', 4: 'Corsan', 5: 'Águas do Rio 1', 7: 'Corsan', 9: 'Corsan',
  10: 'Águas do Rio 4', 11: 'Holding / corporativo', 13: 'Águas do Pará — Bloco A', 15: 'Corsan',
  18: 'Águas do Rio 1', 19: 'Águas do Pará — Bloco A', 21: 'Águas do Rio 4', 22: 'Reuso Itaboraí',
  23: 'Águas do Piauí', 25: 'Corsan', 26: 'Águas de Governador Valadares',
  29: 'Regenera Rio', 30: 'Corsan', 32: 'Ambiental Metrosul', 33: 'Holding / corporativo', 34: 'Nascentes do Xingu',
  36: 'Águas de Teresina', 38: 'Ambiental Ceará 1', 39: 'Regenera Rio', 40: 'Corsan',
  42: 'Ambiental MS Pantanal', 43: 'Nascentes do Xingu',
  46: 'Corsan', 48: 'Rio Investimentos', 50: 'Águas do Rio 1', 53: 'Corsan',
  55: 'Águas Guariroba', 56: 'Corsan', 57: 'Águas do Pará — Bloco B', 58: 'Holding / corporativo', 59: 'Corsan'
};

const UNID_SEED = {
  RJ: 'Águas do Rio 1', MG: 'Águas de Governador Valadares', PI: 'Águas do Piauí', PA: 'Águas do Pará — Bloco A',
  MT: 'Nascentes do Xingu', MS: 'Águas Guariroba', CE: 'Ambiental Ceará 1', SC: 'Águas de Camboriú',
  AM: 'Águas de Manaus', RS: 'Corsan'
};

const RAW = [
  ['Imprensa','2026-01-14','The Economic Observer','Bernardo Cortez','SP','Relatório especial sobre o Brasil','Declinado','Tier 3','Neutro','IPO'],
  ['Imprensa','2026-01-21','Brazil Journal','Luciano Costa','SP','Estratégia de médio prazo e IPO','Declinado','Tier 1','Neutro','IPO;Modelo de negócio'],
  ['Imprensa','2026-01-21','Valor Econômico','Taís Hirata','SP','Leilão e expansão de concessões','Atendido','Tier 1','Propositivo','Leilões;Universalização'],
  ['Imprensa','2026-02-03','O Globo','Cássia Almeida','RJ','Juros e investimento obrigatório em saneamento','Atendido','Tier 1','Neutro','Tarifa;Universalização'],
  ['Imprensa','2026-02-11','Mergermarket','Priscilla Murphy','SP','IPO e Copasa','Declinado','Tier 2','Tenso','IPO;Copasa'],
  ['Imprensa','2026-02-19','Gazeta do Povo','Rodrigo Alvares','PR','Participação privada no saneamento','Atendido','Tier 2','Propositivo','Modelo de negócio;Universalização'],
  ['Imprensa','2026-03-05','Exame Infra','Luciano Pádua','SP','Metas de universalização e próximos leilões','Atendido','Tier 1','Propositivo','Universalização;Leilões'],
  ['Imprensa','2026-03-18','Debtwire','Fabiola Gomes','SP','Margem EBITDA e cenário de crédito','Atendido','Tier 2','Neutro','Disciplina financeira'],
  ['Imprensa','2026-04-02','Valor Econômico','Andrea Assef','SP','Presença de marcas na COP30','Atendido','Tier 1','Propositivo','Clima;Inclusão sanitária'],
  ['Imprensa','2026-04-16','InfoMoney','Marina Alves','SP','Resultados do 1T e alavancagem','Atendido','Tier 2','Tenso','Disciplina financeira;IPO'],
  ['Imprensa','2026-05-07','Folha de S.Paulo','Paulo Ribeiro','SP','Reajuste tarifário em concessões','Atendido','Tier 1','Tenso','Tarifa'],
  ['Imprensa','2026-05-22','Money Report TV','Cristina Falcão','SP','Entrevista de bate-papo com o CEO','Agendado','Tier 3','Propositivo','Modelo de negócio'],
  ['Imprensa','2026-06-09','Reuters','Ana Mendes','DF','Marco do saneamento e revisão regulatória','Atendido','Tier 1','Neutro','Regulação'],
  ['Imprensa','2026-06-24','Saneamento Ambiental','Luana Oliveira','SP','Instituto Aegea: educação e saúde','Atendido','Tier 3','Propositivo','Inclusão sanitária'],
  ['Imprensa','2026-07-08','Bloomberg Línea','Rafael Dias','SP','Fusões e consolidação do setor','Em análise','Tier 2','Neutro','Leilões;IPO'],
  ['Imprensa','2026-07-30','Broadcast','Helena Prado','SP','Captação via debêntures de infraestrutura','Atendido','Tier 2','Propositivo','Disciplina financeira'],
  ['Governo','2026-01-27','ANA','Ana Carolina Argolo','DF','Avanços da regulamentação do saneamento','Atendido','Tier 1','Propositivo','Regulação'],
  ['Governo','2026-02-04','BNDES','Luciana Capanema','DF','Estruturação de projetos e resíduos sólidos','Atendido','Tier 1','Propositivo','Resíduos;Universalização'],
  ['Governo','2026-02-25','Câmara dos Deputados','Comissão de Defesa do Consumidor','DF','Audiência sobre tarifa social','Atendido','Tier 2','Tenso','Tarifa'],
  ['Governo','2026-03-11','MDS','Camile Sahb','DF','Programa Cisternas no Marajó','Atendido','Tier 2','Propositivo','Inclusão sanitária'],
  ['Governo','2026-03-26','ANA','Iracema Freitas','MG','Outorgas e pontos de lançamento em Valadares','Atendido','Tier 2','Neutro','Regulação'],
  ['Governo','2026-04-08','Senado Federal','Sen. Eduardo Braga','DF','Impacto de insumos e reequilíbrio contratual','Atendido','Tier 1','Tenso','Tarifa;Regulação'],
  ['Governo','2026-04-29','CNRH','Conselho pleno','DF','Reúso e pagamento por serviços ambientais','Atendido','Tier 3','Propositivo','Reúso'],
  ['Governo','2026-05-14','MS','Cristiane Godoy','DF','Acordo de cooperação Saneamento Salva','Atendido','Tier 2','Propositivo','Inclusão sanitária'],
  ['Governo','2026-06-03','MDIC','Luis Felipe Giesteira','DF','Cadeia de insumos e política industrial','Atendido','Tier 3','Neutro','Regulação'],
  ['Governo','2026-06-30','ALMG','Bancada de infraestrutura','MG','Acompanhamento do processo da Copasa','Atendido','Tier 2','Tenso','Copasa'],
  ['Governo','2026-07-15','CMBH','Comissão de meio ambiente','MG','Metas municipais de esgotamento','Atendido','Tier 3','Neutro','Universalização'],
  ['Parceiros','2026-01-08','Eurasia Group','Time de análise','DF','Atualização político-econômica','Atendido','Tier 2','Neutro','Cenário político'],
  ['Parceiros','2026-01-16','Itaú BBA','Mesa de infraestrutura','SP','Biometano Day','Atendido','Tier 2','Propositivo','Biometano'],
  ['Parceiros','2026-02-12','BMJ','Victor Figueiredo','DF','Alinhamento institucional sobre Copasa','Atendido','Tier 2','Neutro','Copasa'],
  ['Parceiros','2026-03-04','Centro de Liderança Pública','Tadeu Barros','SP','Parceria de conteúdo institucional','Atendido','Tier 3','Propositivo','Reputação'],
  ['Parceiros','2026-04-21','Instituto FHC','Sergio Fausto','SP','Agenda de desenvolvimento e infraestrutura','Atendido','Tier 3','Propositivo','Cenário político'],
  ['Parceiros','2026-05-19','ABDIB','Comitê legal e tributário','SP','Reforma tributária e incentivos','Atendido','Tier 1','Tenso','Tributário'],
  ['Parceiros','2026-06-17','ABCON','Comitê estratégico','SP','Agenda legislativa do setor','Atendido','Tier 1','Neutro','Regulação'],
  ['Parceiros','2026-07-22','CNI','Conselho de infraestrutura','DF','Emissões relativas e Plano Clima','Atendido','Tier 2','Propositivo','Carbono;Clima'],
  ['Eventos','2026-02-04','BNDES','Nelson Barbosa','DF','Painel sobre financiamento da universalização','Realizado','Tier 1','Propositivo','Universalização','Superciclo de Investimentos em Infraestrutura'],
  ['Eventos','2026-03-22','ANA','Veronica Sánchez','DF','Lançamento do panorama da tarifa social','Realizado','Tier 1','Neutro','Tarifa','Celebração do Dia Mundial da Água'],
  ['Eventos','2026-04-14','CONAMP','Tarcísio Bonfim','DF','Relacionamento institucional','Realizado','Tier 3','Neutro','Reputação','Solenidade de posse 2026-2028'],
  ['Eventos','2026-05-06','ABCON','Percy Soares Neto','SP','Painel com porta-voz da companhia','Realizado','Tier 1','Propositivo','Universalização;Modelo de negócio','Congresso do saneamento privado'],
  ['Eventos','2026-06-11','Itaú BBA','Renata Iervolino','SP','Mesa sobre resíduos e biometano','Realizado','Tier 2','Propositivo','Biometano;Resíduos','Infra Day'],
  ['Eventos','2026-07-02','ALMG','Comissão de meio ambiente','MG','Participação institucional','Realizado','Tier 2','Tenso','Copasa','Audiência pública de saneamento'],
  ['Interna','2026-01-30','Novos Negócios','Equipe institucional','SP','Levantamento de estados no Propag','Elaborado','Tier 3','Neutro','Cenário político'],
  ['Interna','2026-03-13','Jurídico','Equipe institucional','SP','Nota técnica sobre licenciamento ambiental','Elaborado','Tier 2','Neutro','Regulação'],
  ['Interna','2026-05-28','Engenharia','Equipe institucional','MT','Dados de emissões para o Plano Clima','Elaborado','Tier 2','Neutro','Carbono'],
  ['Interna','2026-07-09','Comunicação','Equipe institucional','SP','Consolidação do report mensal ABCON','Elaborado','Tier 3','Neutro','Reputação'],
  ['Investidores','2026-01-19','BlackRock','John Meyer','Internacional','Tese de infraestrutura e pipeline de leilões','Atendido','Tier 1','Propositivo','IPO;Leilões','Fundo de investimento'],
  ['Investidores','2026-02-06','BTG Pactual','Mesa de research','SP','Atualização de resultados e alavancagem','Atendido','Tier 1','Neutro','Disciplina financeira','Banco / sell-side'],
  ['Investidores','2026-02-27','Fitch Ratings','Comitê de rating','SP','Revisão anual de rating corporativo','Atendido','Tier 1','Neutro','Disciplina financeira','Agência de rating'],
  ['Investidores','2026-03-19','JP Morgan','Equipe de infraestrutura','Internacional','Perspectiva de IPO e uso de recursos','Atendido','Tier 1','Propositivo','IPO','Banco / sell-side'],
  ['Investidores','2026-04-10','XP Asset','Gestores de renda fixa','SP','Debêntures incentivadas e covenants','Atendido','Tier 2','Neutro','Disciplina financeira','Fundo de investimento'],
  ['Investidores','2026-05-13','Itaú BBA','Marcelo Sá','SP','Impacto tarifário no fluxo de caixa','Atendido','Tier 2','Tenso','Tarifa','Analista / research'],
  ['Investidores','2026-06-05','Bradesco BBI Infra Day','Investidores institucionais','SP','Apresentação institucional em conferência','Realizado','Tier 1','Propositivo','IPO;Modelo de negócio','Roadshow / conferência'],
  ['Investidores','2026-06-26','S&P Global','Analistas de crédito','Internacional','Cenário regulatório e risco de contrato','Atendido','Tier 1','Neutro','Regulação','Agência de rating'],
  ['Investidores','2026-07-17','Autonomous Research','Gabriela Lins','SP','Consolidação do setor e Copasa','Em análise','Tier 2','Neutro','Copasa;Leilões','Analista / research'],
  ['Investidores','2026-08-05','GIC','Time de infraestrutura','Internacional','Governança e plano de investimentos','Agendado','Tier 1','Propositivo','Modelo de negócio','Fundo de investimento'],
  ['Legislativo','2026-02-10','PL 260/2024','Dep. Marina Rocha','DF','Remoção de poluentes orgânicos persistentes e microplásticos das águas','Em análise','Tier 2','Neutro','Regulação','Câmara dos Deputados'],
  ['Legislativo','2026-03-24','PLP 18/2026','Sen. Eduardo Braga','DF','Tratamento tributário de concessões de saneamento','Em análise','Tier 1','Tenso','Tributário;Tarifa','Senado Federal'],
  ['Legislativo','2026-05-08','PL 1.492/2025','Dep. Carlos Pontes','DF','Marco de resíduos sólidos e metas de aproveitamento energético','Atendido','Tier 1','Propositivo','Resíduos;Biometano','Câmara dos Deputados'],
  ['Legislativo','2026-06-19','PEC 32/2026','Sen. Helena Vieira','DF','Competência regulatória de saneamento entre entes federativos','Em análise','Tier 1','Tenso','Regulação','Congresso Nacional'],
  ['Legislativo','2026-07-28','PL 905/2026','Dep. Est. Rui Amaral','MG','Revisão de contratos estaduais de abastecimento','Em análise','Tier 2','Tenso','Copasa;Tarifa','Assembleia estadual']
];

const RELATOS = {
  r2: { posicionamento: 'A companhia reforçou que acompanha os leilões previstos e avalia oportunidades de expansão com disciplina de capital, mantendo o compromisso com as metas de universalização já contratadas.', mensagens: 'Modelo de negócio; Evolução do setor; Universalização; Disciplina financeira e solidez', encaminhamentos: 'Matéria publicada; acompanhar repercussão junto ao mercado.' },
  r3: { posicionamento: 'A magnitude dos investimentos necessários para a universalização exige complementaridade entre iniciativa privada, poder público e atração de capital — o cenário de juros altos torna a previsibilidade regulatória ainda mais decisiva.', mensagens: 'Evolução do setor; Solidez financeira; Modelo de negócio', encaminhamentos: 'Nota enviada e aproveitada integralmente pelo veículo.' },
  r5: { posicionamento: 'Ainda existem cerca de 32 milhões de pessoas sem acesso a água tratada e quase 90 milhões sem coleta e tratamento de esgoto. Os esforços de inclusão sanitária de pessoas em vulnerabilidade são fundamentais para as metas do Novo Marco.', mensagens: 'Evolução do setor; Universalização; Inclusão sanitária', encaminhamentos: 'Matéria publicada com posicionamento na íntegra; link registrado na clipadora.' },
  r6: { posicionamento: 'A companhia apresentou o cenário do setor, a meta de universalização e o critério de participação em novos leilões, reforçando disciplina financeira na alocação de capital.', mensagens: 'Modelo de negócio; Evolução do setor; Universalização; Disciplina financeira e solidez; Responsabilidade social corporativa', encaminhamentos: 'Episódio publicado; avaliar repescagem do conteúdo nas redes.' },
  r8: { posicionamento: 'A COP é um evento global de grande relevância. Sendo realizada no Pará, região estratégica para o debate climático e onde a Aegea leva saneamento a centenas de famílias, a companhia avalia as melhores formas de contribuir.', mensagens: 'Universalização; Inclusão sanitária; Clima', encaminhamentos: 'Aguardando definição da agenda institucional para a COP30.', pendencias: 'Estratégia de presença na COP30 não fechada.' },
  r10: { posicionamento: 'Os reajustes seguem as regras contratuais e as decisões das agências reguladoras, com paramétricas públicas. A companhia reforçou o peso dos insumos e da energia na composição tarifária.', mensagens: 'Tarifa; Regulação; Disciplina financeira', encaminhamentos: 'Matéria publicada com contraponto da companhia; monitorar desdobramentos.', observacoes: 'Clima tenso — veículo trabalhou o ângulo do impacto no consumidor.' },
  r12: { posicionamento: 'A companhia defendeu previsibilidade regulatória e segurança jurídica dos contratos como condição para sustentar o ciclo de investimentos do setor.', mensagens: 'Regulação; Evolução do setor; Modelo de negócio', encaminhamentos: 'Informações enviadas por e-mail e utilizadas na reportagem.' },
  r13: { posicionamento: 'O Instituto Aegea atua em educação e saúde como extensão da agenda de inclusão sanitária, com foco em comunidades atendidas pelas concessões.', mensagens: 'Universalização; Inclusão sanitária; Responsabilidade social corporativa', encaminhamentos: 'Entrevista concedida; aguardando publicação.' },
  r15: { posicionamento: 'A captação via debêntures de infraestrutura reforça a estrutura de capital e viabiliza a agenda de obras contratada, sem alterar a disciplina de alavancagem.', mensagens: 'Disciplina financeira e solidez; Modelo de negócio', encaminhamentos: 'Nota enviada; matéria publicada.' },
  r45: { relato: 'Apresentação da tese de infraestrutura e do pipeline de leilões ao time global do fundo, com detalhamento do modelo de concessões brasileiro.', encaminhamentos: 'Enviar material complementar sobre estrutura de contratos e reajuste tarifário.' },
  r46: { relato: 'Atualização de resultados e alavancagem para a mesa de research, com detalhamento de capex contratado.', encaminhamentos: 'Compartilhar release e planilha de indicadores.' },
  r47: { relato: 'Revisão anual de rating: agência pediu abertura de cronograma de investimentos e sensibilidade tarifária.', encaminhamentos: 'Enviar cronograma revisado e cenários de sensibilidade.', pendencias: 'Cenários de sensibilidade pendentes.' },
  r48: { relato: 'Conversa sobre perspectiva de IPO e uso de recursos, com foco em governança e agenda de desinvestimentos.', encaminhamentos: 'Manter o banco atualizado sobre marcos societários.' },
  r51: { relato: 'Research de utilities questionou o impacto tarifário no fluxo de caixa das concessões maduras.', encaminhamentos: 'Enviar abertura de paramétricas por contrato.', observacoes: 'Clima tenso — analista trabalha cenário conservador de reajuste.' },
  r54: { relato: 'Reunião de governança e plano de investimentos com o time de infraestrutura do fundo soberano.', encaminhamentos: 'Agendar visita técnica a uma concessão do grupo.', pendencias: 'Visita técnica a ser agendada.' },
  r16: { relato: 'Audiência entre a Aegea e a diretora-presidente interina da ANA sobre os avanços da regulamentação do saneamento básico no âmbito da agência.', encaminhamentos: 'Reunião institucional; acompanhar a publicação das normas de referência.', registro: 'Ata no SharePoint — Relações Institucionais' },
  r17: { relato: 'O BNDES destacou o papel estratégico da infraestrutura para o desenvolvimento econômico e anunciou novas iniciativas de financiamento, incluindo chamadas públicas com participação de capital do banco.', encaminhamentos: 'Avaliar participação da Aegea nas chamadas públicas; mapear estruturação de projetos de resíduos sólidos.', pendencias: 'Aguardando edital das chamadas públicas.', registro: 'Apresentação do evento no SharePoint' },
  r18: { relato: 'Audiência pública sobre a implementação da tarifa social. A comissão questionou o efeito do desconto sobre o equilíbrio econômico-financeiro dos contratos.', encaminhamentos: 'Enviar nota técnica com o impacto tarifário por concessão.', pendencias: 'Nota técnica não enviada.', observacoes: 'Clima tenso — parlamentares cobraram prazos.' },
  r19: { relato: 'O Ministério informou que, sendo a intenção aperfeiçoar os sistemas sanitários das escolas, não há impedimento para o uso das cisternas instaladas pelo governo federal.', encaminhamentos: 'Aegea enviará ao Ministério a lista de escolas em que as estruturas federais foram localizadas e informações sobre as iniciativas escolares (parcerias UNICEF e CNMP).', pendencias: 'Lista de escolas e laudo das vistorias pendentes.', registro: 'E-mail de alinhamento + relatório IPESA' },
  r20: { relato: 'Tratativa sobre pontos de lançamento de esgoto in natura e outorgas em Governador Valadares com a superintendência de fiscalização da ANA.', encaminhamentos: 'Alinhamento institucional; protocolar pedido de outorga revisado.', registro: 'Processo administrativo ANA' },
  r21: { relato: 'Avaliação do impacto da alta de insumos: curva de recuperação de 3 a 5 anos para o setor químico, com alta abrupta de preços causada por formação de estoque.', encaminhamentos: 'Pedido de formalização do conceito técnico contratual do índice de variação das resinas; associação trará a curva de perspectiva de entrada dos insumos no país.', pendencias: 'Índice de variação de preços das resinas ainda não obtido.', observacoes: 'Contratos de longo prazo da Aegea usam esse índice como paramétrica.' },
  r22: { relato: 'Discussão sobre reúso e pagamento por serviços ambientais como instrumentos de valorização dos serviços ecossistêmicos hídricos.', encaminhamentos: 'Acompanhar a evolução regulatória do reúso.', registro: 'Resolução em consulta pública' },
  r23: { relato: 'Ministério enviará o levantamento das doenças que já têm materiais elaborados, com indicação de priorização e sugestão de interlocutor para podcast.', encaminhamentos: 'Aegea compartilhará o calendário anual das ações do Saneamento Salva e enviará o que deseja divulgar junto aos Agentes Comunitários de Saúde.', pendencias: 'Levantamento do Ministério pendente; corte pelo período eleitoral.', registro: 'Acordo de Cooperação — SharePoint' },
  r27: { relato: 'Atualização político-econômica com o time de análise sobre cenário fiscal e eleitoral.', encaminhamentos: 'Sem encaminhamentos formais.', registro: 'Deck de cenário enviado por e-mail' },
  r32: { relato: 'Comitê legal e tributário tratou da redução de incentivos fiscais (LC 224/2025) e da reforma da tributação da renda (Lei 15.270/2025).', encaminhamentos: 'Consolidar posição do setor para envio ao relator.', pendencias: 'Posição setorial em construção.', observacoes: 'Também em pauta: IPTU nos contratos de concessão e dedução de ISSQN na construção civil.' },
  r33: { relato: 'Comitê estratégico apresentou propostas de escritórios de advocacia para atuação setorial e discutiu a agenda legislativa do ano.', encaminhamentos: 'Levar a agenda legislativa ao comitê estratégico na próxima reunião.', pendencias: 'Contratação do escritório não decidida.', registro: 'Ata ABCON' },
  r35: { relato: 'Painel sobre financiamento da universalização: foi enfatizado o desafio de mobilizar cerca de R$ 800 bilhões e o papel dos grandes operadores privados no fortalecimento do financiamento do setor.', encaminhamentos: 'Mapear oportunidades de debêntures incentivadas.', registro: 'Apresentação e fotos no SharePoint' },
  r36: { relato: 'A ANA lançou a Lista Positiva da Tarifa Social e o Panorama de Implementação: cerca de 69% da população vive em municípios onde a implementação já começou, e 34% dos municípios já a concluíram.', encaminhamentos: 'Checar posição das concessões da Aegea na lista positiva.', pendencias: 'Cerca de 40% dos prestadores não enviaram informações às agências reguladoras.', observacoes: 'Norte e Nordeste concentram os menores índices de implementação.' },
  r41: { relato: 'Levantamento dos estados que aderiram ao Propag, com consolidação de impactos por unidade.', encaminhamentos: 'E-mail enviado à área de Novos Negócios.', registro: 'Planilha no SharePoint' },
  r55: { relato: 'A Aegea informou que o projeto foi despachado às comissões e acompanha a designação de relator.', encaminhamentos: 'Monitorar designação de relatoria e pedir audiência com o relator.', pendencias: 'Relator não designado.' },
  r56: { relato: 'Tratamento tributário das concessões em discussão, com risco de elevação de carga sobre contratos vigentes.', encaminhamentos: 'Construir nota técnica conjunta com a ABCON.', pendencias: 'Nota técnica conjunta pendente.', observacoes: 'Tema conectado à reforma tributária.' }
};

// distribuição de porta-vozes coerente com a frente: CEO e CFO na imprensa e no RI,
// diretoria institucional no governo, parceiros e legislativo
function PV_POR_FRENTE(area, i) {
  const P = {
    Imprensa: ['Radamés Casseb', 'Radamés Casseb', 'André Pires', 'Édison Carlos', 'Radamés Casseb', 'Márcia Costa'],
    Investidores: ['André Pires', 'André Pires', 'André Pires', 'Radamés Casseb'],
    Governo: ['Andréa Melo', 'Andréa Melo', 'Letícia Novaes', 'Édison Carlos'],
    Parceiros: ['Andréa Melo', 'Letícia Novaes', 'Andréa Melo', 'Radamés Casseb'],
    Legislativo: ['Letícia Novaes', 'Andréa Melo', 'Letícia Novaes'],
    Eventos: ['Radamés Casseb', 'Édison Carlos', 'Andréa Melo', 'Édison Carlos'],
    Interna: ['Letícia Novaes', 'Márcia Costa']
  };
  const lista = P[area] || PORTAVOZ;
  return lista[i % lista.length];
}

export const dados = { AREAS, PORTAVOZ, MESES, UNID_POR_REGISTRO, UNID_SEED, RAW, RELATOS };

export function registros() {
  return RAW.map((r, i) => ({
    id: 'r' + i, area: r[0], data: r[1], entidade: r[2], pessoa: r[3], uf: r[4],
    pauta: r[5], status: r[6], tier: r[7], clima: r[8], tags: r[9].split(';'),
    subtipo: (r[0] === 'Legislativo' || r[0] === 'Eventos') ? '' : (r[10] || ''),
    casa: r[0] === 'Legislativo' ? (r[10] || '') : '',
    evento: r[0] === 'Eventos' ? (r[10] || '') : '',
    unidade: UNID_POR_REGISTRO[i] || UNID_SEED[r[4]] || 'Holding / corporativo',
    relato: (RELATOS['r' + i] || {}).relato || '',
    posicionamento: (RELATOS['r' + i] || {}).posicionamento || '',
    encaminhamentos: (RELATOS['r' + i] || {}).encaminhamentos || '',
    pendencias: (RELATOS['r' + i] || {}).pendencias || '',
    resultado: (r[0] === 'Imprensa' || r[0] === 'Interna') ? 'Sem definição'
      : ['Avançou', 'Avançou', 'Mantido', 'Avançou', 'Retrocedeu', 'Mantido', 'Avançou', 'Sem definição', 'Mantido', 'Avançou'][(i * 7) % 10],
    portaVoz: PV_POR_FRENTE(r[0], i),
    esfera: r[0] === 'Legislativo' ? (r[4] === 'DF' ? 'Federal' : 'Estadual')
      : r[0] === 'Investidores' ? (r[4] === 'Internacional' ? 'Internacional' : 'Nacional')
      : r[0] === 'Governo' ? (r[4] === 'DF' ? 'Federal' : 'Estadual')
      : (r[0] === 'Imprensa' ? 'Nacional' : 'Federal')
  })).sort((a, b) => (a.data < b.data ? 1 : -1));
}
