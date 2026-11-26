-- =============================================================================
-- A BITES TEM CARGO CONHECIDO, DO JEITO QUE O TEMA JÁ TEM APELIDO (0121)
-- =============================================================================
--
-- O QUE ESTAVA ACONTECENDO. A Bites manda `Cargo` vazio em ~95-100% das
-- linhas de todo export mensal já conferido (Julho a Novembro/2026) — não é
-- defeito do arquivo, é como o fornecedor sempre entrega. E o sistema já
-- aceita qualquer valor nessa coluna sem vocabulário fechado
-- (`app/dominio/ingestao_score.rotulo_do_cargo`): o problema nunca foi o
-- sistema recusar, é a Bites não mandar o dado.
--
-- ESTA TABELA É O CATÁLOGO DE CONTAS JÁ JULGADAS — mesma ideia de
-- `tema_apelido` (0121) e `unidade_negocio_apelido` (0099): não inventa
-- vocabulário novo, só registra que uma conta de rede social (`Autor` do
-- export) JÁ TEVE o cargo/perfil dela julgado uma vez, caso a caso, olhando
-- `Autor` + rede social + o texto dos posts (nunca um default fixo tipo
-- "Internauta" para tudo).
--
-- O GRÃO É A CONTA (`Autor`), NÃO Autor+Rede: `migrations/0071` mediu, sobre
-- 1.173 autores distintos do arquivo de 01-09/2026, que só 54 aparecem em
-- mais de uma rede — e é o Autor sozinho que identifica o `perfil_rede` no
-- cadastro compartilhado. As 176 entradas julgadas aqui colapsam para 166
-- contas distintas por esse grão, zero conflito (nenhuma conta tem cargo
-- diferente julgado em rede diferente).
--
-- O QUE ESTA MIGRATION NÃO FAZ, de propósito: não aplica a tabela a nenhuma
-- menção já gravada — isso é o pré-processamento da próxima subida
-- (`app/dominio/enriquecimento_bites.py`), não SQL retroativo. E não cobre
-- toda conta que algum dia aparecer: conta nova continua em branco até
-- alguém julgar e entrar aqui numa migration futura, igual ao apelido de
-- tema.
--
-- Idempotente: `on conflict do nothing`.
-- =============================================================================

begin;

create table if not exists cargo_de_conta (
    autor_normalizado text primary key,
    autor             text not null,
    cargo             text not null
);

insert into cargo_de_conta (autor_normalizado, autor, cargo) values
    ('18horasnews', '18horasnews', 'Imprensa'),
    ('_carlosmec', '_carlosmec', 'Internauta'),
    ('_jorginda12', '_jorginda12', 'Internauta'),
    ('_rmotoka022', '_rmotoka022', 'Internauta'),
    ('abim4el_carlos', 'abim4el_carlos', 'Internauta'),
    ('acoes simplificadas', 'Ações Simplificadas', 'Comunicador'),
    ('adeiltonleite', 'adeiltonleite', 'Internauta'),
    ('agoramaurolopes.rs', 'agoramaurolopes.rs', 'Imprensa'),
    ('aguasbombinhas', 'aguasbombinhas', 'Unidade Aegea'),
    ('aguasdecamboriusc', 'aguasdecamboriusc', 'Unidade Aegea'),
    ('aguasdesfs', 'aguasdesfs', 'Unidade Aegea'),
    ('aguasdeteresina', 'aguasdeteresina', 'Unidade Aegea'),
    ('aguasdetimon', 'aguasdetimon', 'Unidade Aegea'),
    ('aguasdorio', 'aguasdorio', 'Unidade Aegea'),
    ('aimiseria', 'aimiseria', 'Internauta'),
    ('airtondeppman', 'airtondeppman', 'Internauta'),
    ('airtonsouzars', 'airtonsouzars', 'Internauta'),
    ('alessandroferrazale', 'alessandroferrazale', 'Internauta'),
    ('alexand09931376', 'alexand09931376', 'Internauta'),
    ('alexboscaini', 'alexboscaini', 'Internauta'),
    ('alexsanderfmen1', 'alexsanderfmen1', 'Internauta'),
    ('alvaniver', 'alvaniver', 'Internauta'),
    ('amoraproducoesculturais', 'amoraproducoesculturais', 'Empresa'),
    ('analiseenergia', 'analiseenergia', 'Comunicador'),
    ('antonietaenei', 'antonietaenei', 'Internauta'),
    ('associacaomicoleaodourado', 'associacaomicoleaodourado', 'Outros'),
    ('attuchroberto', 'attuchroberto', 'Internauta'),
    ('bacananews_', 'bacananews_', 'Imprensa'),
    ('batsuteko', 'batsuteko', 'Internauta'),
    ('bfranco89', 'bfranco89', 'Internauta'),
    ('bipador', 'bipador', 'Internauta'),
    ('brazil journal', 'Brazil Journal', 'Imprensa'),
    ('braziljournal', 'braziljournal', 'Imprensa'),
    ('braziljournalnews', 'braziljournalnews', 'Imprensa'),
    ('camaralajeado', 'camaralajeado', 'Órgão público'),
    ('carlosaugusto1', 'carlosaugusto1', 'Internauta'),
    ('claudio tatsch', 'Claudio Tatsch', 'Político'),
    ('claudiotatsch.dep', 'claudiotatsch.dep', 'Político'),
    ('cnibr', 'cnibr', 'Outros'),
    ('comment on beca alcantara', 'Comment on Beca Alcântara', 'Internauta'),
    ('comment on gaucha', 'Comment on Gaúcha', 'Internauta'),
    ('comment on portal leouve - leia ouca veja.', 'Comment on Portal Leouve - Leia Ouça Veja.', 'Internauta'),
    ('comment on reclame aqui cachoeirinha', 'Comment on Reclame Aqui Cachoeirinha', 'Internauta'),
    ('confederacao nacional da industria', 'Confederação Nacional da Indústria', 'Outros'),
    ('correiodopovo', 'correiodopovo', 'Imprensa'),
    ('corsanoficial', 'corsanoficial', 'Unidade Aegea'),
    ('cpgclickpetroleoegas', 'cpgclickpetroleoegas', 'Empresa'),
    ('decsjunior', 'decsjunior', 'Internauta'),
    ('delbianconeri', 'delbianconeri', 'Internauta'),
    ('dez investimentos', 'Dez investimentos', 'Comunicador'),
    ('diarinho', 'diarinho', 'Imprensa'),
    ('difusora973', 'difusora973', 'Imprensa'),
    ('dinheiro na bolsa', 'Dinheiro na bolsa', 'Comunicador'),
    ('dividendocerto', 'dividendocerto', 'Comunicador'),
    ('donifloripa', 'donifloripa', 'Comunicador'),
    ('dudareuank', 'dudareuank', 'Internauta'),
    ('dulce80280656', 'dulce80280656', 'Internauta'),
    ('fabiogeribello', 'fabiogeribello', 'Internauta'),
    ('fadingstarbr', 'fadingstarbr', 'Internauta'),
    ('ferandreduarte', 'ferandreduarte', 'Internauta'),
    ('filipeddilha', 'filipeddilha', 'Internauta'),
    ('folha', 'folha', 'Imprensa'),
    ('folhadepiracicaba.oficial', 'folhadepiracicaba.oficial', 'Imprensa'),
    ('fora da curva', 'Fora Da Curva', 'Comunicador'),
    ('gabriel_jrpi', 'gabriel_jrpi', 'Internauta'),
    ('gabrieldjunq', 'gabrieldjunq', 'Internauta'),
    ('gazetaderosario', 'gazetaderosario', 'Imprensa'),
    ('girodegravatai', 'girodegravatai', 'Comunicador'),
    ('gpsdanoticiaoficial', 'gpsdanoticiaoficial', 'Imprensa'),
    ('gruponoroestonline', 'gruponoroestonline', 'Comunicador'),
    ('heitorzzap', 'heitorzzap', 'Internauta'),
    ('helencabral', 'helencabral', 'Internauta'),
    ('herbertc76', 'herbertc76', 'Internauta'),
    ('igoorkohl', 'igoorkohl', 'Internauta'),
    ('iia.brasil', 'iia.brasil', 'Outros'),
    ('instituto aegea', 'Instituto Aegea', 'Aegea'),
    ('invest em foco', 'INVEST EM FOCO', 'Comunicador'),
    ('investidor sincero', 'Investidor Sincero', 'Comunicador'),
    ('itausaholding', 'itausaholding', 'Empresa'),
    ('izadora_sinott', 'izadora_sinott', 'Internauta'),
    ('jcneconomista', 'jcneconomista', 'Comunicador'),
    ('jean78740937', 'jean78740937', 'Internauta'),
    ('jfc131331', 'jfc131331', 'Internauta'),
    ('jknoticiasof', 'jknoticiasof', 'Imprensa'),
    ('joaolucas100620', 'joaolucas100620', 'Internauta'),
    ('jonasojunior', 'jonasojunior', 'Internauta'),
    ('jornal.aqui', 'jornal.aqui', 'Imprensa'),
    ('jornaldiarinho', 'jornaldiarinho', 'Imprensa'),
    ('jornalpontagrossa', 'jornalpontagrossa', 'Imprensa'),
    ('kzz0e_', 'kzz0e_', 'Internauta'),
    ('lenoticias', 'lenoticias', 'Imprensa'),
    ('lidesantacatarina', 'lidesantacatarina', 'Outros'),
    ('lucas_beluci', 'lucas_beluci', 'Internauta'),
    ('lucaspdesousa91', 'lucaspdesousa91', 'Internauta'),
    ('lucianoncomodo', 'lucianoncomodo', 'Internauta'),
    ('maay_ii', 'maay_ii', 'Internauta'),
    ('marceloaltavini', 'marceloaltavini', 'Internauta'),
    ('marcioqmaciel', 'marcioqmaciel', 'Internauta'),
    ('marcosboniatti', 'marcosboniatti', 'Internauta'),
    ('maximabarros', 'maximabarros', 'Internauta'),
    ('miguelsrossetto', 'miguelsrossetto', 'Político'),
    ('mverass', 'mverass', 'Internauta'),
    ('nanectr', 'nanectr', 'Internauta'),
    ('naty', 'Naty', 'Comunicador'),
    ('newsevocebr', 'newsevocebr', 'Imprensa'),
    ('nielsen_jr7', 'nielsen_jr7', 'Internauta'),
    ('noticiasdefato', 'noticiasdefato', 'Imprensa'),
    ('o moyses que consegue!', 'O Moysés que consegue!', 'Comunicador'),
    ('octavejit', 'octavejit', 'Internauta'),
    ('oervinensenc', 'oervinensenc', 'Imprensa'),
    ('omunicipiobrusque', 'omunicipiobrusque', 'Imprensa'),
    ('opapoeconomico', 'opapoeconomico', 'Comunicador'),
    ('p2portal', 'p2portal', 'Imprensa'),
    ('pactoglobalonubr', 'pactoglobalonubr', 'Outros'),
    ('pantvbarracao', 'pantvbarracao', 'Imprensa'),
    ('paparicobacchioficial', 'paparicobacchioficial', 'Internauta'),
    ('paulosouto43', 'paulosouto43', 'Internauta'),
    ('pedr0lucc4', 'pedr0lucc4', 'Internauta'),
    ('pedroamaralc', 'pedroamaralc', 'Internauta'),
    ('pipelinevalor', 'pipelinevalor', 'Imprensa'),
    ('pit money', 'Pit Money', 'Comunicador'),
    ('politicacapixaba', 'politicacapixaba', 'Comunicador'),
    ('portalalegretetudo', 'portalalegretetudo', 'Imprensa'),
    ('portalgaz', 'portalgaz', 'Imprensa'),
    ('prefeituradealcinopolis', 'prefeituradealcinopolis', 'Prefeitura'),
    ('prefeituradejaguarao', 'prefeituradejaguarao', 'Prefeitura'),
    ('prefeituraslg', 'prefeituraslg', 'Prefeitura'),
    ('prefmanaus', 'prefmanaus', 'Prefeitura'),
    ('radar capex - noticias de obras', 'Radar Capex - Notícias de Obras', 'Imprensa'),
    ('radar financeiro', 'Radar Financeiro', 'Comunicador'),
    ('radardomercado_', 'radardomercado_', 'Comunicador'),
    ('radioaltouruguai.com.br', 'radioaltouruguai.com.br', 'Imprensa'),
    ('radiomeninabc', 'radiomeninabc', 'Imprensa'),
    ('radioprogressodeijui', 'radioprogressodeijui', 'Imprensa'),
    ('re.n.d.a.', 'RE.N.D.A.', 'Comunicador'),
    ('rebob.brasil', 'rebob.brasil', 'Outros'),
    ('rebobbrasil', 'rebobbrasil', 'Outros'),
    ('recordaltamira', 'recordaltamira', 'Imprensa'),
    ('redetv sgc - ariquemes', 'REDETV SGC - Ariquemes', 'Imprensa'),
    ('resumo critico', 'Resumo Crítico', 'Comunicador'),
    ('resumo do ri', 'Resumo do RI', 'Comunicador'),
    ('rev_sambiental', 'rev_sambiental', 'Imprensa'),
    ('ricardolod0fla', 'ricardolod0fla', 'Internauta'),
    ('saneamento salva', 'Saneamento Salva', 'Comunicador'),
    ('saneamento.basico', 'saneamento.basico', 'Comunicador'),
    ('santamariadazoeira', 'santamariadazoeira', 'Comunicador'),
    ('sauba.co', 'sauba.co', 'Empresa'),
    ('sbcomunicacoes', 'sbcomunicacoes', 'Outros'),
    ('sentinelusai', 'sentinelusai', 'Internauta'),
    ('shmeedt', 'shmeedt', 'Internauta'),
    ('simaobacamars', 'simaobacamars', 'Internauta'),
    ('stela farias', 'Stela Farias', 'Político'),
    ('stelafariasrs', 'stelafariasrs', 'Político'),
    ('studionoticiastv', 'studionoticiastv', 'Imprensa'),
    ('taquarivivo', 'taquarivivo', 'Outros'),
    ('tato_rj', 'tato_rj', 'Internauta'),
    ('thomas_hesler', 'thomas_hesler', 'Internauta'),
    ('tribunadeparnaiba', 'tribunadeparnaiba', 'Imprensa'),
    ('tribunadephb', 'tribunadephb', 'Imprensa'),
    ('tv pampa', 'TV Pampa', 'Imprensa'),
    ('tvmetropolitanapiracicaba', 'tvmetropolitanapiracicaba', 'Imprensa'),
    ('vagas_pi', 'vagas_pi', 'Empresa'),
    ('varos.br', 'varos.br', 'Comunicador'),
    ('vdibrasil', 'vdibrasil', 'Outros'),
    ('vonoffe', 'vonoffe', 'Internauta'),
    ('williamwasinhes', 'williamwasinhes', 'Internauta')
  on conflict (autor_normalizado) do nothing;

do $$
declare
    total int;
begin
    select count(*) into total from cargo_de_conta;
    raise notice 'cargo_de_conta tem % contas julgadas', total;
end $$;

commit;
