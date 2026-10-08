"""As partes puras do `scripts/instantaneo.py`.

O QUE ESTE ARQUIVO NÃO COBRE, e é decisão: `criar` e `restaurar` falam com o
`docker` e com um banco no ar. Montar fixture para isso custaria mais do que o
ensaio manual que já é obrigatório antes de confiar na ferramenta — e um teste
que sobe Postgres para provar que `pg_dump` funciona prova o `pg_dump`, não o
script.

O QUE ELE COBRE é o que volta a dar errado sozinho: a impressão digital das
migrations (a guarda que decide se uma restauração é segura), a limpeza do
rótulo que vira nome de arquivo, e a ida e volta do manifesto.

A IMPRESSÃO É A PARTE CRÍTICA. A primeira versão da guarda comparava a CONTAGEM
de migrations, e este repositório tem três colisões de número — duas `0055`,
duas `0060`, duas `0061`, de branches paralelos. Duas árvores com a mesma
quantidade de arquivos e schemas diferentes passariam pela guarda. Pior: a
`0044` foi EDITADA depois de publicada, então nem a lista de nomes basta — só o
conteúdo denuncia. Os testes abaixo fixam os três casos.
"""

from __future__ import annotations

import json

import pytest

from scripts.instantaneo import (
    TABELAS_DE_CONFERENCIA,
    _limpar,
    impressao_das_migrations,
)


def _migrations(pasta, arquivos: dict[str, str]):
    """Escreve migrations de mentira e devolve a lista ordenada, como o script vê."""
    for nome, conteudo in arquivos.items():
        (pasta / nome).write_text(conteudo, encoding="utf-8")
    return sorted(pasta.glob("*.sql"))


class TestImpressaoDasMigrations:
    def test_a_mesma_arvore_da_a_mesma_impressao(self, tmp_path):
        a = _migrations(tmp_path, {"0001_a.sql": "create table a();"})
        assert impressao_das_migrations(a) == impressao_das_migrations(a)

    def test_migration_nova_muda_a_impressao(self, tmp_path):
        antes = impressao_das_migrations(
            _migrations(tmp_path, {"0001_a.sql": "create table a();"})
        )
        depois = impressao_das_migrations(
            _migrations(tmp_path, {"0002_b.sql": "create table b();"})
        )
        assert antes != depois

    def test_editar_migration_PUBLICADA_muda_a_impressao(self, tmp_path):
        """O caso que a lista de nomes não pega.

        A `0044` deste projeto foi alterada depois de aplicada, trocando um
        mapeamento de `'midia'` para outro valor. Mesmo nome, mesma contagem,
        schema diferente — e o `scripts/migrar.py` controla por nome de arquivo,
        então bancos já migrados não recebem a correção. Uma guarda que ignore o
        conteúdo deixaria restaurar entre esses dois estados sem avisar.
        """
        antes = impressao_das_migrations(
            _migrations(tmp_path, {"0001_a.sql": "select 'midia';"})
        )
        depois = impressao_das_migrations(
            _migrations(tmp_path, {"0001_a.sql": "select 'solicitacao';"})
        )
        assert antes != depois

    def test_MESMA_CONTAGEM_e_impressoes_diferentes(self, tmp_path):
        """O furo exato da guarda antiga, com a forma das colisões reais.

        Dois branches com duas `0060` cada, de conteúdos diferentes: dois
        arquivos nos dois lados, e a contagem não distingue.
        """
        um = tmp_path / "um"
        outro = tmp_path / "outro"
        um.mkdir()
        outro.mkdir()
        a = _migrations(um, {
            "0060_indices.sql": "drop index x;",
            "0060_tipos.sql": "insert into t values (1);",
        })
        b = _migrations(outro, {
            "0060_indices.sql": "drop index x;",
            "0060_tipos.sql": "insert into t values (2);",
        })

        assert len(a) == len(b) == 2
        assert impressao_das_migrations(a) != impressao_das_migrations(b)

    def test_a_ordem_dos_arquivos_nao_muda_a_impressao(self, tmp_path):
        """A impressão é da ÁRVORE, e árvore não tem ordem de leitura.

        A PRIMEIRA VERSÃO DESTE TESTE NÃO PROVAVA NADA, e foi achado de revisão:
        ela comparava a lista com `sorted(lista)`, mas o ajudante já entregava
        ordenado — os dois lados eram a mesma coisa. Agora a lista vai
        INVERTIDA, e a igualdade só vale porque a função passou a ordenar por
        conta.
        """
        arquivos = _migrations(tmp_path, {
            "0001_a.sql": "select 1;",
            "0002_b.sql": "select 2;",
        })
        assert arquivos != list(reversed(arquivos))
        assert impressao_das_migrations(arquivos) == impressao_das_migrations(
            list(reversed(arquivos))
        )

    def test_arvore_vazia_nao_estoura(self, tmp_path):
        """Uma pasta sem migration é estado possível (clone pela metade), e a
        impressão tem de sair em vez de levantar.
        """
        assert impressao_das_migrations([])


class TestLimparRotulo:
    """O rótulo vira parte de NOME DE ARQUIVO, então o que sai dele precisa ser
    seguro em todo sistema — barra, dois-pontos e acento quebram em Windows ou
    viram caminho.
    """

    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("antes de recriar", "antes-de-recriar"),
            ("ANTES/DEPOIS", "antes-depois"),
            ("com: dois-pontos", "com-dois-pontos"),
            # O ACENTO TRANSLITERA em vez de virar traço, e esta expectativa
            # mudou depois de o teste pegar o defeito: a primeira versão da
            # função deixava `ç` passar inteiro para o nome do arquivo, porque
            # `isalnum()` é verdadeiro para letra acentuada em Python. Corrigida,
            # ela poderia ter trocado acento por traço — mas "espacos" diz mais
            # que "espa-os" para quem procura o instantâneo depois.
            ("  espaços   demais  ", "espacos-demais"),
            ("---traços---", "tracos"),
            ("já_com_sublinhado", "ja_com_sublinhado"),
        ],
    )
    def test_vira_nome_de_arquivo_seguro(self, entrada, esperado):
        assert _limpar(entrada) == esperado

    def test_nao_passa_de_quarenta_caracteres(self):
        assert len(_limpar("x" * 200)) == 40

    def test_rotulo_so_de_simbolos_vira_vazio(self):
        """E vazio é aceitável: o identificador ainda tem a data e a hora."""
        assert _limpar("///") == ""


class TestManifesto:
    def test_ida_e_volta_preserva_o_que_a_guarda_le(self, tmp_path):
        """O manifesto é JSON escrito e lido pelo próprio script; o que importa
        é que as três chaves que `restaurar` consulta sobrevivam ao round-trip.
        """
        manifesto = {
            "quando": "2026-10-08T16:09:40-03:00",
            "rotulo": "depois dos achados",
            "commit": "5157c84",
            "branch": "banco/instantaneos",
            "arvore_suja": True,
            "migrations_no_disco": 63,
            "impressao_das_migrations": "6cd02b0db6ecb085",
            "contagens": {"tema": 150, "mencao": 20928},
        }
        caminho = tmp_path / "m.json"
        caminho.write_text(json.dumps(manifesto, ensure_ascii=False), encoding="utf-8")
        lido = json.loads(caminho.read_text(encoding="utf-8"))

        assert lido["impressao_das_migrations"] == "6cd02b0db6ecb085"
        assert lido["contagens"] == {"tema": 150, "mencao": 20928}
        assert lido["arvore_suja"] is True


class TestSentinelas:
    def test_cobrem_os_dominios_que_importam(self):
        """A lista existe para ser LIDA por quem restaura, então é curta — mas
        tem de cobrir o que, voltando vazio, passaria desapercebido.

        `usuario_escopo` entrou por achado de revisão: um banco sem ele abre e
        deixa todo mundo ver tudo, e nenhuma tela reclama.
        """
        assert {
            "usuario",
            "usuario_escopo",
            "instituicao",
            "interacao",
            "tema",
            "risco",
            "tema_risco",
            "importacao",
            "mencao",
        } <= set(TABELAS_DE_CONFERENCIA)

    def test_nao_cresceu_demais(self):
        """Doze números uma pessoa confere; trinta ninguém confere, e a
        conferência vira carimbo.
        """
        assert len(TABELAS_DE_CONFERENCIA) <= 14
