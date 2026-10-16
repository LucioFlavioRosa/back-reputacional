-- A Approach passa a ler o que a planilha dela já trazia: link, texto, autor e
-- subtema. Mais os apelidos que juntam as grafias que o fornecedor duplica.
--
-- O QUE MOTIVOU. O export de 01-08/2026 ("Aegea - Approach Dados - Conteudo -
-- SL - CM - V2.xlsx") foi medido coluna por coluna, e quatro colunas cheias não
-- tinham destino no cadastro das duas fontes:
--
--     coluna           aba   preenchida   campo de `mencao`
--     Link             SL        99%      link
--     Conteúdo         SL        99%      titulo_texto
--     Tags (subtema)   SL        30%      subtema
--     Link             CM        45%      link
--     Conteúdo         CM        79%      titulo_texto
--     Publicador       CM        77%      autor
--
-- É o mesmo achado da `0063` na Clipei e da `0070` na Bites: o campo existe em
-- `mencao`, `ler_linha` o lê, a tela o mostra — e o cadastro da fonte não o
-- apontava para coluna nenhuma, então ele subia nulo. A diferença é que aqui
-- NUNCA houve menção da Approach no banco, então não há passado a corrigir: a
-- primeira subida já entra completa.
--
-- O SUBTEMA É A PRIMEIRA VEZ. Nenhuma das cinco fontes mapeava `subtema` até
-- hoje — `tests/test_niveis_do_fornecedor.py` registrava isso como "caminho
-- aberto". O filtro "Subtema (fornecedor)" da barra da lente já existe, já tem
-- teste, e só não aparecia porque `distintos(Mencao.subtema)` voltava vazio.
--
-- E É O NÍVEL CERTO: `Tags (subtema)` é um nível ABAIXO de `Tags (tema)` no
-- vocabulário da Approach, que é de onde sai o `tema`. Apontar `subtema` para
-- uma coluna de outro nível não quebraria a subida — agruparia as menções no
-- nível errado, calado. O teste de níveis prende isso.
--
-- POR QUE AS QUATRO ENTRAM COMO OPCIONAIS. No mapeamento, "mapeada é exigida":
-- `colunas_necessarias` recusa a planilha que não traz uma coluna citada, e a
-- recusa é certa para `Data` e `Sentimento`. Para coluna de ENRIQUECIMENTO ela
-- seria uma piora: hoje este arquivo sobe, e passar a exigir `Link` faria o
-- próximo mês ser recusado se a agência renomeasse a coluna — trocando 17.039
-- menções por um erro. Mesma decisão da `0064` na Clipei ("pode ter casos sem
-- link", dono do produto, 09/10/2026).
--
-- AS COLUNAS ANTIGAS NÃO VIRAM OPCIONAIS. `Concessionárias`, `Tags (tema)`,
-- `Engajamento`, `TAG (motivo)` e `Interações` continuam exigidas, porque hoje
-- elas são exigidas e afrouxá-las deixaria o mês entrar pela metade em
-- silêncio. Esta migration só acrescenta.
--
-- OS APELIDOS SÃO MEDIDOS, um por um, no arquivo real. Cada linha abaixo é um
-- par de grafias que `achatar` prova ser a MESMA coisa, e que sem apelido vira
-- duas barras no gráfico de exposição e duas opções no filtro:
--
--     SL  unidade   Águas do Para (45)           -> Águas do Pará (220)
--     SL  tema      Premios (7)                  -> Prêmios (6)
--     SL  subtema   Seguranca no Trabalho (8)    -> Segurança no Trabalho (7)
--     SL  subtema   Gestao de Residuos (11)      -> Gestão de Resíduos (2)
--     SL  subtema   Pescando Tradicoes (2)       -> Pescando Tradições (11)
--     CM  unidade   Águas do Para (36)           -> Águas do Pará (142)
--     CM  tema      Reclamação de Serviços (115) -> Reclamação de serviços (200)
--
-- A CANÔNICA É A CORRETA, não a mais numerosa: `Gestão de Resíduos` tem 2
-- ocorrências contra 11 da sem acento, e continua sendo a forma que se escreve.
-- O apelido existe para convergir, e convergir para o erro de digitação só
-- trocaria qual metade fica torta.
--
-- `apelidos` VALE PARA tema, unidade, subtema E teor — os quatro campos que
-- passam por `_rotulo`. As chaves acima são inequívocas (nenhuma é palavra que
-- signifique outra coisa noutro campo), e é essa a condição para a lista poder
-- ser plana.
--
-- NÃO ESTÁ AQUI, de propósito:
--
--   * `Autor`, `Cidade`, `Estado` e `Atributo` da SL: as colunas EXISTEM e
--     estão 100% vazias nas 10.960 linhas. Mapear coluna vazia não traz dado e
--     passa a exigir a presença dela — custo sem ganho. É cobrança à agência.
--   * `Rede` (99% nas duas abas): não há campo em `mencao` para a rede social,
--     e inventar um é decisão de modelo, não de cadastro.
--   * `Publicador` da CM NÃO vira `veiculo`, e sim `autor`. `veiculo` é "quem
--     falou" do cadastro compartilhado, e faria nascer instituição para cada
--     perfil que comenta num post nosso — milhares de pessoas físicas no
--     Cadastro. `autor` é texto, não cria cadastro, e é o que a Bites já faz.
--   * a hashtag `Atributos` da aba `Conteúdo` (o N1 exato do painel, 7 de 7):
--     aquela aba não é menção, não tem sentimento e não entra neste caminho.

update score_fonte
   set mapeamento_colunas =
         mapeamento_colunas
         || jsonb_build_object(
              'colunas',
              (mapeamento_colunas -> 'colunas')
                || '{"link": "Link",
                     "titulo_texto": "Conteúdo",
                     "subtema": "Tags (subtema)"}'::jsonb,
              'colunas_opcionais',
              '["link", "titulo_texto", "subtema"]'::jsonb,
              'apelidos',
              '{"Águas do Para": "Águas do Pará",
                "Premios": "Prêmios",
                "Seguranca no Trabalho": "Segurança no Trabalho",
                "Gestao de Residuos": "Gestão de Resíduos",
                "Pescando Tradicoes": "Pescando Tradições"}'::jsonb
            )
 where codigo = 'approach_sl';

update score_fonte
   set mapeamento_colunas =
         mapeamento_colunas
         || jsonb_build_object(
              'colunas',
              (mapeamento_colunas -> 'colunas')
                || '{"link": "Link",
                     "titulo_texto": "Conteúdo",
                     "autor": "Publicador"}'::jsonb,
              'colunas_opcionais',
              '["link", "titulo_texto", "autor"]'::jsonb,
              'apelidos',
              '{"Águas do Para": "Águas do Pará",
                "Reclamação de Serviços": "Reclamação de serviços"}'::jsonb
            )
 where codigo = 'approach_cm';
