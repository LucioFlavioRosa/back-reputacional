--: OS VEÍCULOS QUE A LENTE MERCADO CONSIDERA, pela subcategoria do cadastro.
--:
--: A lente Mercado se separa hoje por `Público-alvo = Investidores`, uma coluna
--: que a Clipei preenche. Medido contra o export de 08–09/2026: isso captura
--: **80 linhas** onde a lista de veículos do mercado financeiro que a Aegea
--: mantém captura **323**. Os dois critérios discordam em 267 das 335 linhas
--: envolvidas — o de hoje perde Valor Econômico (49 menções), InfoMoney (25),
--: Expert XP (20) e Times Brasil (15), que entram só na Imprensa.
--:
--: O CRITÉRIO PASSA A SER O CADASTRO, e esta migration o semeia. "Econômica e de
--: negócios" já existia em `subcategoria_publico` sob Imprensa — cuja
--: `padrao_de_quebra` é literalmente `logica_editorial` —, e nenhum veículo a
--: tinha. Daqui em diante a lista se mantém pela tela, não por SQL.
--:
--: SÃO OS 81 DA PLANILHA da Aegea (`veiculos_mercado_financeiro.xlsx`),
--: nas duas categorias que o dono do produto classificou:
--:
--:     1. Mercado financeiro      51   bolsa, investimentos, crédito, M&A, rating
--:     2. Economia e negócios     30   economia e mundo corporativo em geral
--:
--: AS DUAS ENTRAM. A lente responde "como o mercado me vê", e não "quem fala de
--: bolsa": Valor Econômico e Folha cobrem a Aegea para investidor e estão na
--: segunda categoria. Fica registrado aqui porque muda um número que todo mundo
--: lê na reunião.
--:
--: CASA POR `nome_normalizado`, E NÃO POR `lower(nome)`. A primeira versão desta
--: migration usava `lower()` e marcou 78 dos 81: `normalizar` também
--: remove acento e colapsa espaço, e três veículos diferiam exatamente nisso.
--: A coluna normalizada é a que a aplicação usa para casar nome — e é a que tem
--: índice único com o tipo. Os nomes abaixo já vêm normalizados por ela.
--:
--: (Um dos veículos da Clipei traz EMOJI no nome. `normalizar` o DESCARTA —
--: ela faz `NFKD` e corta tudo que não é ASCII, medido: `normalizar("Jornal 📈")`
--: dá `"jornal"` —, enquanto o `achatar` da ingestão o preserva. Os dois lados
--: desta comparação usam `normalizar`, então o casamento fecha; é por isso que
--: gerar a lista pela própria função do domínio importa, e não por preservar o
--: emoji. Corrigido depois de revisão: a frase anterior afirmava o contrário.)
--:
--: Nome que não casar é ignorado SEM ERRO: numa base onde a Clipei ainda não
--: entrou o veículo não existe, e parar a migration por isso impediria o banco
--: de subir.
--:
--: NÃO MEXE EM QUEM JÁ TEM OUTRA SUBCATEGORIA. Um veículo classificado à mão
--: como "Geral nacional" é decisão de alguém; sobrescrever seria desfazer
--: trabalho humano com uma lista.
--:
--: Idempotente.

begin;

create temporary table veiculos_do_mercado (
    nome_normalizado text primary key,
    nome_na_planilha text not null
) on commit drop;

insert into veiculos_do_mercado (nome_normalizado, nome_na_planilha) values
        ('acionista', 'Acionista'),
        ('advfn news', 'ADVFN News'),
        ('bolsa brasileira de mercadorias', 'Bolsa Brasileira de Mercadorias'),
        ('bolsa e mercado', 'Bolsa e Mercado'),
        ('brazil stock guide', 'Brazil Stock Guide'),
        ('capital aberto', 'Capital Aberto'),
        ('investing', 'Investing'),
        ('trading view', 'Trading View'),
        ('alta renda blog', 'Alta Renda Blog'),
        ('auvp analitica', 'AUVP Analítica'),
        ('btg pactual', 'BTG Pactual'),
        ('eu quero investir', 'Eu Quero Investir'),
        ('expert xp', 'Expert Xp'),
        ('genial investimentos | analisa', 'Genial Investimentos | Analisa'),
        ('guia do investidor', 'Guia do Investidor'),
        ('inves talk', 'Inves Talk'),
        ('investidor 10', 'Investidor 10'),
        ('investidores brasil', 'Investidores Brasil'),
        ('renova invest', 'Renova Invest'),
        ('seu dinheiro', 'Seu Dinheiro'),
        ('suno', 'Suno'),
        ('valor investe', 'Valor Investe'),
        ('visno invest', 'Visno Invest'),
        ('clube fii news', 'Clube Fii News'),
        ('bloomberg linea', 'Bloomberg Línea'),
        ('bm&c news', 'BM&C News'),
        ('bmc news', 'BMC News'),
        ('bp money', 'BP Money'),
        ('broadcast', 'Broadcast'),
        ('economic news brasil', 'Economic News Brasil'),
        ('finance news', 'Finance News'),
        ('infomoney', 'InfoMoney'),
        ('invest news', 'Invest News'),
        ('istoe dinheiro', 'IstoÉ Dinheiro'),
        ('latin finance', 'Latin Finance'),
        ('money report', 'Money Report'),
        ('money times', 'Money Times'),
        ('monitor mercantil', 'Monitor Mercantil'),
        ('space money', 'Space Money'),
        ('times brasil', 'Times Brasil'),
        ('uol economia', 'UOL Economia'),
        ('valor economico', 'Valor Econômico'),
        ('valor internacional', 'Valor Internacional'),
        ('brazil journal', 'Brazil Journal'),
        ('dealflow brasil', 'Dealflow Brasil'),
        ('neo feed', 'Neo Feed'),
        ('fitch ratings', 'Fitch Ratings'),
        ('let''s money', 'Let''s Money'),
        ('seu credito digital', 'Seu Crédito Digital'),
        ('beneficios e auxilios', 'Benefícios e Auxílios'),
        ('seguinte', 'Seguinte'),
        ('exame', 'Exame'),
        ('forbes', 'Forbes'),
        ('epoca negocios', 'Época Negócios'),
        ('lide.com', 'Lide.com'),
        ('revista empreende', 'Revista Empreende'),
        ('jornal empresas & negocios', 'Jornal Empresas & Negócios'),
        ('movimento economico', 'Movimento Econômico'),
        ('o poder economico', 'O Poder Econômico'),
        ('fronteira economica', 'Fronteira Econômica'),
        ('economia pr', 'Economia PR'),
        ('paraiba business', 'Paraíba Business'),
        ('meio e negocio', 'Meio e negócio'),
        ('diario do comercio | belo horizonte', 'Diário do Comércio | Belo Horizonte'),
        ('diario do comercio | sao paulo', 'Diário do Comércio | São Paulo'),
        ('diario industria e comercio', 'Diário Indústria e Comércio'),
        ('jornal do comercio - porto alegre', 'Jornal do Comércio - Porto Alegre'),
        ('bn americas', 'BN Américas'),
        ('relatorio reservado', 'Relatório Reservado'),
        ('inteligencia brasil imprensa (ibi)', 'Inteligência Brasil Imprensa (IBI)'),
        ('mercado e consumo', 'Mercado e Consumo'),
        ('consumidor moderno', 'Consumidor Moderno'),
        ('marcas e mercados', 'Marcas e Mercados'),
        ('fundacao getulio vargas - fgv', 'Fundação Getulio Vargas - FGV'),
        ('eventos fgv', 'Eventos FGV'),
        ('associacao comercial e industrial de aracatuba', 'Associação Comercial e Industrial de Araçatuba'),
        ('acibr - associacao empresarial de brusque', 'ACIBr - Associação Empresarial de Brusque'),
        ('camara portuguesa do rio de janeiro', 'Câmara Portuguesa do Rio de Janeiro'),
        ('associacao brasileira de shopping centers (abrasce)', 'Associação Brasileira de Shopping Centers (Abrasce)'),
        ('i profesional', 'I Profesional'),
        ('somos pymes', 'Somos Pymes');

update instituicao i
   set subcategoria_publico_id = (
         select s.id
           from subcategoria_publico s
           join categoria_publico c on c.id = s.categoria_publico_id
          where c.nome = 'Imprensa' and s.nome = 'Econômica e de negócios'
          limit 1
       )
 where i.tipo = 'veiculo'
   and i.subcategoria_publico_id is null
   and exists (
         select 1 from veiculos_do_mercado v
          where v.nome_normalizado = i.nome_normalizado
       );

do $$
declare
    alvo int;
    marcados int;
begin
    select s.id into alvo
      from subcategoria_publico s
      join categoria_publico c on c.id = s.categoria_publico_id
     where c.nome = 'Imprensa' and s.nome = 'Econômica e de negócios'
     limit 1;
    if alvo is null then
        raise exception
            'a subcategoria "Econômica e de negócios" da Imprensa não existe';
    end if;

    select count(*) into marcados
      from instituicao
     where tipo = 'veiculo' and subcategoria_publico_id = alvo;
    raise notice 'veiculos marcados como imprensa economica: %', marcados;
end $$;

commit;
