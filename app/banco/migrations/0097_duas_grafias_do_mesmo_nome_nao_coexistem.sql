-- DUAS GRAFIAS DO MESMO NOME NAO PODEM COEXISTIR, e coexistiam em dois lugares.
--
-- `referencia` e `jornalista_matriz` tinham cada uma a SUA regra de chave de
-- nome, escrita em SQL dentro do indice unico:
--
--   0026  referencia         (lower(btrim(titulo)))
--   0049  jornalista_matriz  (lower(regexp_replace(nome,'\s+',' ','g')),
--                             coalesce(veiculo,''))
--
-- Nenhuma das duas TIRA ACENTO. Entao "Relatorio Anual" com e sem acento
-- entravam como duas referencias -- o comeco de duas versoes circulando, que e
-- o problema que aquela tabela existe para acabar --, e "Tais Hirata" com e sem
-- acento como duas jornalistas, contra o que o comentario da propria 0049
-- promete. A 0026 ainda deixava passar espaco interno duplo, e a 0049 nao
-- normalizava `veiculo` de jeito nenhum.
--
-- POR QUE COLUNA, E NAO UM SQL MELHOR NO INDICE. Indice em Postgres exige
-- expressao IMMUTABLE, e `unaccent()` nao e a mesma coisa que o NFKD + ascii de
-- `dominio/texto.normalizar`. Vale o desenho que `instituicao` ja usava: a
-- COLUNA guarda a chave, a APLICACAO a escreve com a funcao canonica (por um
-- gancho no modelo, que nenhum ponto de escrita pode esquecer), e o indice e
-- sobre a coluna. Uma regra, num lugar so, em Python.
--
-- == O BACKFILL, E POR QUE ELE NAO PODE SER APROXIMADO ==
--
-- A PRIMEIRA VERSAO DESTA MIGRATION ERRAVA AQUI, e a revisao pegou: ela usava
-- `translate()` com os acentos do portugues, o que NAO descarta o nao-ASCII que
-- o NFKD descarta. Medido nos dados reais: 67 dos 87 valores divergiam, todos
-- pelo travessao (U+2014) em "Posicionamento -- Metas", que o `translate`
-- preservava e o `normalizar` descarta. Uma referencia migrada deixaria de
-- colidir com uma criada pela tela -- o defeito que esta migration existe para
-- consertar, reintroduzido por ela mesma.
--
-- (E o teste que eu escrevi para pegar isso percorria ZERO linhas, porque o
-- banco de teste nasce vazio. Ele agora monta o proprio corpus.)
--
-- A REGRA CORRETA TEM TRES PARTES, e este arquivo foi GERADO do Unicode em vez
-- de digitado -- um par de `translate` fora de posicao trocaria uma letra:
--
--   1. `replace()` para o que o NFKD EXPANDE em mais de um ASCII   (1/2 -> 12)
--   2. `translate()` para o que ele resolve em um ASCII so          (c -> c)
--   3. descartar todo nao-ASCII restante                            (-- -> )
--
-- == E A MIGRATION RECUSA EM VEZ DE ADIVINHAR ==
--
-- As tres partes cobrem tudo que o NFKD produz dentro de U+00A0..U+017F, mais
-- quatro coladores de web (No, TM, fi, fl). Para QUALQUER outro caractere cujo
-- NFKD produza ASCII, o SQL nao tem como acertar -- entao a migration PARA, com
-- a linha na mensagem, e alguem decide. A lista de faixas recusadas foi provada
-- completa varrendo os 1.114.112 codepoints: nenhum diverge sem ser recusado.
--
-- SE JA HOUVER PAR DIVERGENTE NO BANCO, o `create unique index` tambem FALHA, e
-- isso tambem e o certo: qual das duas linhas sobrevive e decisao de quem cuida
-- do cadastro. Medido na pilha local: `referencia` 67 linhas e 0 pares;
-- `jornalista_matriz` 10 linhas e 0 pares.
--
-- TUDO NUMA TRANSACAO: se o indice novo falhar, nada fica pela metade -- nem
-- coluna preenchida, nem tabela sem a protecao de unicidade que ela tinha.
--
-- NENHUM GRANT NOVO: permissao no Postgres e por tabela, nao por coluna.

begin;

-- ================================================================ a guarda
do $$
declare
  achado text;
begin
  select titulo into achado from referencia
   where titulo ~ '[\u01a0-\u01a1\u01af-\u01b0\u01c4-\u01dc\u01de-\u01e1\u01e6-\u01ed\u01f0-\u01f5\u01f8-\u01fb\u0200-\u021b\u021e-\u021f\u0226-\u0233\u02b0-\u02b0\u02b2-\u02b3\u02b7-\u02b8\u02d8-\u02dd\u02e1-\u02e3\u037a-\u037a\u037e-\u037e\u0384-\u0385\u1d2c-\u1d2c\u1d2e-\u1d2e\u1d30-\u1d31\u1d33-\u1d3a\u1d3c-\u1d3c\u1d3e-\u1d43\u1d47-\u1d49\u1d4d-\u1d4d\u1d4f-\u1d50\u1d52-\u1d52\u1d56-\u1d58\u1d5b-\u1d5b\u1d62-\u1d65\u1d9c-\u1d9c\u1da0-\u1da0\u1dbb-\u1dbb\u1e00-\u1e9b\u1ea0-\u1ef9\u1fbd-\u1fbd\u1fbf-\u1fc1\u1fcd-\u1fcf\u1fdd-\u1fdf\u1fed-\u1fef\u1ffd-\u1ffe\u2000-\u200a\u2017-\u2017\u2024-\u2026\u202f-\u202f\u203c-\u203c\u203e-\u203e\u2047-\u2049\u205f-\u205f\u2070-\u2071\u2074-\u207a\u207c-\u208a\u208c-\u208e\u2090-\u2093\u2095-\u209c\u20a8-\u20a8\u2100-\u2103\u2105-\u2106\u2109-\u210e\u2110-\u2113\u2115-\u2115\u2119-\u211d\u2120-\u2121\u2124-\u2124\u2128-\u2128\u212a-\u212d\u212f-\u2131\u2133-\u2134\u2139-\u2139\u213b-\u213b\u2145-\u2149\u2150-\u217f\u2189-\u2189\u2260-\u2260\u226e-\u226f\u2460-\u24ea\u2a74-\u2a76\u2c7c-\u2c7d\u3000-\u3000\u309b-\u309c\u3200-\u321e\u3220-\u3243\u3250-\u325f\u32b1-\u32cf\u3358-\u337a\u3380-\u33ff\ua7f2-\ua7f4\ufb00-\ufb00\ufb03-\ufb06\ufb29-\ufb29\ufc5e-\ufc63\ufdfa-\ufdfb\ufe10-\ufe10\ufe13-\ufe16\ufe19-\ufe19\ufe30-\ufe30\ufe33-\ufe38\ufe47-\ufe50\ufe52-\ufe52\ufe54-\ufe57\ufe59-\ufe5c\ufe5f-\ufe66\ufe68-\ufe6b\ufe70-\ufe70\ufe72-\ufe72\ufe74-\ufe74\ufe76-\ufe76\ufe78-\ufe78\ufe7a-\ufe7a\ufe7c-\ufe7c\ufe7e-\ufe7e\uff01-\uff5e\uffe3-\uffe3\U000107a5-\U000107a5\U0001ccd6-\U0001ccf9\U0001d400-\U0001d454\U0001d456-\U0001d49c\U0001d49e-\U0001d49f\U0001d4a2-\U0001d4a2\U0001d4a5-\U0001d4a6\U0001d4a9-\U0001d4ac\U0001d4ae-\U0001d4b9\U0001d4bb-\U0001d4bb\U0001d4bd-\U0001d4c3\U0001d4c5-\U0001d505\U0001d507-\U0001d50a\U0001d50d-\U0001d514\U0001d516-\U0001d51c\U0001d51e-\U0001d539\U0001d53b-\U0001d53e\U0001d540-\U0001d544\U0001d546-\U0001d546\U0001d54a-\U0001d550\U0001d552-\U0001d6a3\U0001d7ce-\U0001d7ff\U0001f100-\U0001f10a\U0001f110-\U0001f12e\U0001f130-\U0001f14f\U0001f16a-\U0001f16c\U0001f190-\U0001f190\U0001fbf0-\U0001fbf9]' limit 1;
  if achado is not null then
    raise exception 'referencia.titulo contem caractere que o backfill nao sabe '
      'normalizar como `dominio/texto.normalizar` faria: %. Normalize a linha a '
      'mao (ou acrescente o caractere a esta migration) antes de aplicar.', achado;
  end if;

  select nome into achado from jornalista_matriz
   where nome ~ '[\u01a0-\u01a1\u01af-\u01b0\u01c4-\u01dc\u01de-\u01e1\u01e6-\u01ed\u01f0-\u01f5\u01f8-\u01fb\u0200-\u021b\u021e-\u021f\u0226-\u0233\u02b0-\u02b0\u02b2-\u02b3\u02b7-\u02b8\u02d8-\u02dd\u02e1-\u02e3\u037a-\u037a\u037e-\u037e\u0384-\u0385\u1d2c-\u1d2c\u1d2e-\u1d2e\u1d30-\u1d31\u1d33-\u1d3a\u1d3c-\u1d3c\u1d3e-\u1d43\u1d47-\u1d49\u1d4d-\u1d4d\u1d4f-\u1d50\u1d52-\u1d52\u1d56-\u1d58\u1d5b-\u1d5b\u1d62-\u1d65\u1d9c-\u1d9c\u1da0-\u1da0\u1dbb-\u1dbb\u1e00-\u1e9b\u1ea0-\u1ef9\u1fbd-\u1fbd\u1fbf-\u1fc1\u1fcd-\u1fcf\u1fdd-\u1fdf\u1fed-\u1fef\u1ffd-\u1ffe\u2000-\u200a\u2017-\u2017\u2024-\u2026\u202f-\u202f\u203c-\u203c\u203e-\u203e\u2047-\u2049\u205f-\u205f\u2070-\u2071\u2074-\u207a\u207c-\u208a\u208c-\u208e\u2090-\u2093\u2095-\u209c\u20a8-\u20a8\u2100-\u2103\u2105-\u2106\u2109-\u210e\u2110-\u2113\u2115-\u2115\u2119-\u211d\u2120-\u2121\u2124-\u2124\u2128-\u2128\u212a-\u212d\u212f-\u2131\u2133-\u2134\u2139-\u2139\u213b-\u213b\u2145-\u2149\u2150-\u217f\u2189-\u2189\u2260-\u2260\u226e-\u226f\u2460-\u24ea\u2a74-\u2a76\u2c7c-\u2c7d\u3000-\u3000\u309b-\u309c\u3200-\u321e\u3220-\u3243\u3250-\u325f\u32b1-\u32cf\u3358-\u337a\u3380-\u33ff\ua7f2-\ua7f4\ufb00-\ufb00\ufb03-\ufb06\ufb29-\ufb29\ufc5e-\ufc63\ufdfa-\ufdfb\ufe10-\ufe10\ufe13-\ufe16\ufe19-\ufe19\ufe30-\ufe30\ufe33-\ufe38\ufe47-\ufe50\ufe52-\ufe52\ufe54-\ufe57\ufe59-\ufe5c\ufe5f-\ufe66\ufe68-\ufe6b\ufe70-\ufe70\ufe72-\ufe72\ufe74-\ufe74\ufe76-\ufe76\ufe78-\ufe78\ufe7a-\ufe7a\ufe7c-\ufe7c\ufe7e-\ufe7e\uff01-\uff5e\uffe3-\uffe3\U000107a5-\U000107a5\U0001ccd6-\U0001ccf9\U0001d400-\U0001d454\U0001d456-\U0001d49c\U0001d49e-\U0001d49f\U0001d4a2-\U0001d4a2\U0001d4a5-\U0001d4a6\U0001d4a9-\U0001d4ac\U0001d4ae-\U0001d4b9\U0001d4bb-\U0001d4bb\U0001d4bd-\U0001d4c3\U0001d4c5-\U0001d505\U0001d507-\U0001d50a\U0001d50d-\U0001d514\U0001d516-\U0001d51c\U0001d51e-\U0001d539\U0001d53b-\U0001d53e\U0001d540-\U0001d544\U0001d546-\U0001d546\U0001d54a-\U0001d550\U0001d552-\U0001d6a3\U0001d7ce-\U0001d7ff\U0001f100-\U0001f10a\U0001f110-\U0001f12e\U0001f130-\U0001f14f\U0001f16a-\U0001f16c\U0001f190-\U0001f190\U0001fbf0-\U0001fbf9]' or coalesce(veiculo,'') ~ '[\u01a0-\u01a1\u01af-\u01b0\u01c4-\u01dc\u01de-\u01e1\u01e6-\u01ed\u01f0-\u01f5\u01f8-\u01fb\u0200-\u021b\u021e-\u021f\u0226-\u0233\u02b0-\u02b0\u02b2-\u02b3\u02b7-\u02b8\u02d8-\u02dd\u02e1-\u02e3\u037a-\u037a\u037e-\u037e\u0384-\u0385\u1d2c-\u1d2c\u1d2e-\u1d2e\u1d30-\u1d31\u1d33-\u1d3a\u1d3c-\u1d3c\u1d3e-\u1d43\u1d47-\u1d49\u1d4d-\u1d4d\u1d4f-\u1d50\u1d52-\u1d52\u1d56-\u1d58\u1d5b-\u1d5b\u1d62-\u1d65\u1d9c-\u1d9c\u1da0-\u1da0\u1dbb-\u1dbb\u1e00-\u1e9b\u1ea0-\u1ef9\u1fbd-\u1fbd\u1fbf-\u1fc1\u1fcd-\u1fcf\u1fdd-\u1fdf\u1fed-\u1fef\u1ffd-\u1ffe\u2000-\u200a\u2017-\u2017\u2024-\u2026\u202f-\u202f\u203c-\u203c\u203e-\u203e\u2047-\u2049\u205f-\u205f\u2070-\u2071\u2074-\u207a\u207c-\u208a\u208c-\u208e\u2090-\u2093\u2095-\u209c\u20a8-\u20a8\u2100-\u2103\u2105-\u2106\u2109-\u210e\u2110-\u2113\u2115-\u2115\u2119-\u211d\u2120-\u2121\u2124-\u2124\u2128-\u2128\u212a-\u212d\u212f-\u2131\u2133-\u2134\u2139-\u2139\u213b-\u213b\u2145-\u2149\u2150-\u217f\u2189-\u2189\u2260-\u2260\u226e-\u226f\u2460-\u24ea\u2a74-\u2a76\u2c7c-\u2c7d\u3000-\u3000\u309b-\u309c\u3200-\u321e\u3220-\u3243\u3250-\u325f\u32b1-\u32cf\u3358-\u337a\u3380-\u33ff\ua7f2-\ua7f4\ufb00-\ufb00\ufb03-\ufb06\ufb29-\ufb29\ufc5e-\ufc63\ufdfa-\ufdfb\ufe10-\ufe10\ufe13-\ufe16\ufe19-\ufe19\ufe30-\ufe30\ufe33-\ufe38\ufe47-\ufe50\ufe52-\ufe52\ufe54-\ufe57\ufe59-\ufe5c\ufe5f-\ufe66\ufe68-\ufe6b\ufe70-\ufe70\ufe72-\ufe72\ufe74-\ufe74\ufe76-\ufe76\ufe78-\ufe78\ufe7a-\ufe7a\ufe7c-\ufe7c\ufe7e-\ufe7e\uff01-\uff5e\uffe3-\uffe3\U000107a5-\U000107a5\U0001ccd6-\U0001ccf9\U0001d400-\U0001d454\U0001d456-\U0001d49c\U0001d49e-\U0001d49f\U0001d4a2-\U0001d4a2\U0001d4a5-\U0001d4a6\U0001d4a9-\U0001d4ac\U0001d4ae-\U0001d4b9\U0001d4bb-\U0001d4bb\U0001d4bd-\U0001d4c3\U0001d4c5-\U0001d505\U0001d507-\U0001d50a\U0001d50d-\U0001d514\U0001d516-\U0001d51c\U0001d51e-\U0001d539\U0001d53b-\U0001d53e\U0001d540-\U0001d544\U0001d546-\U0001d546\U0001d54a-\U0001d550\U0001d552-\U0001d6a3\U0001d7ce-\U0001d7ff\U0001f100-\U0001f10a\U0001f110-\U0001f12e\U0001f130-\U0001f14f\U0001f16a-\U0001f16c\U0001f190-\U0001f190\U0001fbf0-\U0001fbf9]' limit 1;
  if achado is not null then
    raise exception 'jornalista_matriz contem caractere que o backfill nao sabe '
      'normalizar: %. Mesma coisa.', achado;
  end if;
end $$;

-- ============================================================= referencia
alter table referencia add column if not exists titulo_normalizado text;

update referencia
   set titulo_normalizado = lower(btrim(regexp_replace(regexp_replace(translate(
              replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(titulo, chr(160), ' '), chr(188), '14'), chr(189), '12'), chr(190), '34'), chr(306), 'IJ'), chr(307), 'ij'), chr(8470), 'No'), chr(8482), 'TM'), chr(64257), 'fi'), chr(64258), 'fl'),
              '¨ª¯²³´¸¹ºÀÁÂÃÄÅÇÈÉÊËÌÍÎÏÑÒÓÔÕÖÙÚÛÜÝàáâãäåçèéêëìíîïñòóôõöùúûüýÿĀāĂăĄąĆćĈĉĊċČčĎďĒēĔĕĖėĘęĚěĜĝĞğĠġĢģĤĥĨĩĪīĬĭĮįİĴĵĶķĹĺĻļĽľĿŀŃńŅņŇňŉŌōŎŏŐőŔŕŖŗŘřŚśŜŝŞşŠšŢţŤťŨũŪūŬŭŮůŰűŲųŴŵŶŷŸŹźŻżŽžſ',
              ' a 23  1oAAAAAACEEEEIIIINOOOOOUUUUYaaaaaaceeeeiiiinooooouuuuyyAaAaAaCcCcCcCcDdEeEeEeEeEeGgGgGgGgHhIiIiIiIiIJjKkLlLlLlLlNnNnNnnOoOoOoRrRrRrSsSsSsSsTtTtUuUuUuUuUuUuWwYyYZzZzZzs'
            ), '[^[:ascii:]]', '', 'g'), '\s+', ' ', 'g')))
 where titulo_normalizado is null;

alter table referencia alter column titulo_normalizado set not null;

drop index if exists referencia_titulo_idx;
create unique index if not exists referencia_titulo_normalizado_idx
  on referencia (titulo_normalizado);

-- ====================================================== jornalista_matriz
alter table jornalista_matriz add column if not exists nome_normalizado text;
alter table jornalista_matriz add column if not exists veiculo_normalizado text;

update jornalista_matriz
   set nome_normalizado = lower(btrim(regexp_replace(regexp_replace(translate(
              replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(nome, chr(160), ' '), chr(188), '14'), chr(189), '12'), chr(190), '34'), chr(306), 'IJ'), chr(307), 'ij'), chr(8470), 'No'), chr(8482), 'TM'), chr(64257), 'fi'), chr(64258), 'fl'),
              '¨ª¯²³´¸¹ºÀÁÂÃÄÅÇÈÉÊËÌÍÎÏÑÒÓÔÕÖÙÚÛÜÝàáâãäåçèéêëìíîïñòóôõöùúûüýÿĀāĂăĄąĆćĈĉĊċČčĎďĒēĔĕĖėĘęĚěĜĝĞğĠġĢģĤĥĨĩĪīĬĭĮįİĴĵĶķĹĺĻļĽľĿŀŃńŅņŇňŉŌōŎŏŐőŔŕŖŗŘřŚśŜŝŞşŠšŢţŤťŨũŪūŬŭŮůŰűŲųŴŵŶŷŸŹźŻżŽžſ',
              ' a 23  1oAAAAAACEEEEIIIINOOOOOUUUUYaaaaaaceeeeiiiinooooouuuuyyAaAaAaCcCcCcCcDdEeEeEeEeEeGgGgGgGgHhIiIiIiIiIJjKkLlLlLlLlNnNnNnnOoOoOoRrRrRrSsSsSsSsTtTtUuUuUuUuUuUuWwYyYZzZzZzs'
            ), '[^[:ascii:]]', '', 'g'), '\s+', ' ', 'g'))),
       veiculo_normalizado = case when veiculo is null then null
                                  else lower(btrim(regexp_replace(regexp_replace(translate(
              replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(veiculo, chr(160), ' '), chr(188), '14'), chr(189), '12'), chr(190), '34'), chr(306), 'IJ'), chr(307), 'ij'), chr(8470), 'No'), chr(8482), 'TM'), chr(64257), 'fi'), chr(64258), 'fl'),
              '¨ª¯²³´¸¹ºÀÁÂÃÄÅÇÈÉÊËÌÍÎÏÑÒÓÔÕÖÙÚÛÜÝàáâãäåçèéêëìíîïñòóôõöùúûüýÿĀāĂăĄąĆćĈĉĊċČčĎďĒēĔĕĖėĘęĚěĜĝĞğĠġĢģĤĥĨĩĪīĬĭĮįİĴĵĶķĹĺĻļĽľĿŀŃńŅņŇňŉŌōŎŏŐőŔŕŖŗŘřŚśŜŝŞşŠšŢţŤťŨũŪūŬŭŮůŰűŲųŴŵŶŷŸŹźŻżŽžſ',
              ' a 23  1oAAAAAACEEEEIIIINOOOOOUUUUYaaaaaaceeeeiiiinooooouuuuyyAaAaAaCcCcCcCcDdEeEeEeEeEeGgGgGgGgHhIiIiIiIiIJjKkLlLlLlLlNnNnNnnOoOoOoRrRrRrSsSsSsSsTtTtUuUuUuUuUuUuWwYyYZzZzZzs'
            ), '[^[:ascii:]]', '', 'g'), '\s+', ' ', 'g'))) end
 where nome_normalizado is null;

alter table jornalista_matriz alter column nome_normalizado set not null;

-- O `where ativo` SE MANTEM: a matriz desativa em vez de apagar, e duas linhas
-- inativas da mesma pessoa sao historico, nao duplicata.
--
-- NOME NOVO, E NAO O MESMO `jornalista_matriz_unica`: um `create ... if not
-- exists` com nome ja usado e NO-OP SILENCIOSO, e foi assim que a 0052 pediu um
-- indice que nunca nasceu. `test_dois_indices_nao_disputam_o_mesmo_nome` me
-- parou quando eu reusei o nome.
drop index if exists jornalista_matriz_unica;
create unique index if not exists jornalista_matriz_unica_normalizada
  on jornalista_matriz (nome_normalizado, coalesce(veiculo_normalizado, ''))
  where ativo;

commit;
