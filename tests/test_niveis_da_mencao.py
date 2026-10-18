"""O fornecedor traz um nível; o cadastro deriva os de cima. E só UMA regra.

O QUE ESTE ARQUIVO PROTEGE, em ordem de importância:

1. **que a GRAVAÇÃO e a LEITURA concordem.** Existem duas implementações da
   precedência entre níveis: `temas_da_mencao.Arvore.resolver`, que decide o que
   vai para as colunas da `0098`, e `consulta_profundidade.Taxonomia.resolver`,
   que decide o que a tela de aprofundamento mostra ao vivo. Enquanto houver
   duas, o risco não é nenhuma delas estar errada — é elas DIVERGIREM, e aí a
   coluna gravada contradiz a tela, nos dois sentidos, sem nada acusar;
2. que o prefixo numerado seja recortado por UMA função, e não por duas cópias
   do mesmo regex — o defeito que os PRs #91 e #92 tiraram de quatro lugares;
3. a precedência em si: o nível mais fundo que o CADASTRO reconhecer manda, os
   de cima são derivados, e NUNCA se desce;
4. que os nomes do cadastro não colidam sob a chave de comparação — `bloco_tema`
   e `macro_tema` não têm índice único no nome, só no código, então duas linhas
   poderiam normalizar para a mesma chave e uma sumiria do mapa em silêncio.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import BlocoTema, MacroTema, Tema
from app.casos_de_uso import temas_da_mencao
from app.casos_de_uso.temas_da_mencao import Arvore
from app.dominio import consulta_profundidade as cp
from app.dominio.niveis_de_taxonomia import Niveis, chave_do_nivel, sem_numeracao
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)


@pytest.fixture
def sessao():
    conexao = _engine.connect()
    transacao = conexao.begin()
    sessao = Session(bind=conexao, expire_on_commit=False)
    try:
        yield sessao
    finally:
        sessao.close()
        transacao.rollback()
        conexao.close()


# -- 2. uma regra de prefixo, não duas -----------------------------------------


def test_o_recorte_do_prefixo_e_a_mesma_funcao_nos_dois_lados() -> None:
    """`consulta_profundidade.sem_prefixo` É `sem_numeracao`, não uma cópia.

    `is`, e não igualdade de resultado sobre exemplos: duas funções com o mesmo
    comportamento HOJE é exatamente o estado de onde a divergência nasce. Se
    alguém reintroduzir um regex local em `consulta_profundidade`, este teste
    falha mesmo que os dois concordem em toda entrada que alguém pensou em
    testar.
    """
    assert cp.sem_prefixo is sem_numeracao


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("7. Prosperidade Compartilhada", "Prosperidade Compartilhada"),
        ("2. Eficiência Operacional e Qualidade", "Eficiência Operacional e Qualidade"),
        ("1. Governança", "Governança"),
        # os quatro separadores que um export à mão produz
        ("7) Prosperidade Compartilhada", "Prosperidade Compartilhada"),
        ("7 - Prosperidade Compartilhada", "Prosperidade Compartilhada"),
        ("7 – Prosperidade Compartilhada", "Prosperidade Compartilhada"),
        # sem prefixo, passa intacto
        ("Governança", "Governança"),
        ("Marca empregadora", "Marca empregadora"),
    ],
)
def test_o_prefixo_numerado_sai(entrada: str, esperado: str) -> None:
    assert sem_numeracao(entrada) == esperado


def test_o_regex_shipped_e_guloso_e_isso_esta_registrado() -> None:
    """O separador é OPCIONAL, então um número solto na frente também sai.

    NÃO É O COMPORTAMENTO QUE EU TERIA ESCOLHIDO, e está aqui exatamente por
    isso: ao mudar a função de casa eu quase a reescrevi mais estrita (exigindo
    o separador), o que teria mudado em silêncio o pilar de toda menção na tela
    de aprofundamento. O shipped manda; uma regra melhor é decisão com medição,
    não efeito colateral de uma mudança de casa.

    Se alguém DECIDIR apertar o regex, este teste falha e aponta para a decisão.
    """
    assert sem_numeracao("2026 Balanço") == "Balanço"
    assert sem_numeracao("14.026 Marco Legal") == "026 Marco Legal"


def test_a_chave_do_nivel_junta_as_duas_grafias_do_mesmo_n1() -> None:
    """As 15 grafias do `Atributo` caem em 7 chaves — o achado que motivou tudo.

    Medido na base local: 26.603 menções (26% das que têm atributo) ficavam fora
    do cadastro por causa de um `"2. "`.
    """
    assert chave_do_nivel("2. Eficiência Operacional e Qualidade") == chave_do_nivel(
        "Eficiência Operacional e Qualidade"
    )
    assert chave_do_nivel("1. Governança") == chave_do_nivel("Governança")
    #: E não junta o que é diferente de verdade.
    assert chave_do_nivel("Governança") != chave_do_nivel("Responsabilidade Social")


def test_a_chave_do_nivel_trata_ausencia_como_vazio() -> None:
    """`""` é o contrato de ausência, e nenhum nome do cadastro o produz."""
    assert chave_do_nivel(None) == ""
    assert chave_do_nivel("") == ""
    assert chave_do_nivel("   ") == ""


# -- 4. o cadastro não colide sob a chave --------------------------------------


def test_nenhum_nivel_do_cadastro_colide_sob_a_chave(sessao: Session) -> None:
    """Duas linhas com a mesma chave fariam uma sumir do mapa em silêncio.

    `tema` tem índice único no nome; `bloco_tema` e `macro_tema` NÃO (só no
    `codigo`). Então para esses dois a ausência de colisão é fato do cadastro de
    hoje, não garantia do schema — e é por isso que se mede aqui.
    """
    for tabela, rotulo in ((BlocoTema, "N1"), (MacroTema, "N2"), (Tema, "N3")):
        nomes = list(
            sessao.scalars(select(tabela.nome).where(tabela.ativo.is_(True)))
        )
        chaves = [chave_do_nivel(nome) for nome in nomes]
        assert "" not in chaves, f"{rotulo} tem nome que normaliza para vazio"
        duplicadas = {c for c in chaves if chaves.count(c) > 1}
        assert not duplicadas, (
            f"{rotulo} tem {len(duplicadas)} chave(s) repetida(s): {duplicadas}. "
            "Uma das linhas sumiria do mapa e as menções dela ficariam sem nível."
        )


def test_todo_n2_ativo_tem_n1_e_todo_n3_ativo_tem_n2(sessao: Session) -> None:
    """A derivação para cima não pode esbarrar em elo faltando.

    `macro_tema.bloco_tema_id` é NOT NULL no schema, então o N2->N1 é garantido.
    O N3->N2 é NULÁVEL: a taxonomia v4 desativou 45 temas e os deixou sem N2. A
    `arvore()` só carrega ATIVOS, e este teste confere que entre os ativos não
    sobrou nenhum órfão — se sobrar, a menção cai num N3 sem pilar e a tela de
    aprofundamento não tem onde desenhá-la.
    """
    orfaos = sessao.scalars(
        select(Tema.nome).where(Tema.ativo.is_(True), Tema.macro_tema_id.is_(None))
    ).all()
    assert not orfaos, (
        f"{len(orfaos)} subtema(s) ATIVO(s) sem tema estratégico: {list(orfaos)[:5]}. "
        "A menção ligada a eles fica num N3 sem N2 e sem pilar."
    )


# -- a 0098 É ADITIVA: nada que funciona hoje muda ------------------------------


def test_o_tema_id_de_hoje_nao_muda_com_a_regra_nova(sessao: Session) -> None:
    """A chave do N3 é a MESMA sob a regra antiga e a nova. Medido, não suposto.

    A regra antiga era `normalizar(tema_texto)`; a nova é
    `normalizar(sem_numeracao(tema_texto))`. Para um nome COM prefixo numerado as
    duas dariam chaves diferentes — e `tema_id` de 26.987 menções poderia mudar
    de dono sem ninguém pedir.

    MEDIDO NA BASE REAL antes de gravar a 0098 (18/10/2026): dos 350
    `tema_texto` distintos, ZERO mudam de chave; dos 104 N3 ativos, ZERO mudam;
    e das 104.670 menções, ZERO teriam `tema_id` diferente — nenhuma ganharia e
    nenhuma perderia o que tem.

    O QUE ESTE TESTE PRENDE é a metade que o schema não garante: que nenhum NOME
    DO CADASTRO comece com número. O dia em que alguém cadastrar um subtema
    chamado "7. Qualquer Coisa", a chave dele passa a divergir entre as duas
    regras e este teste falha — antes de a próxima subida remapear menções em
    silêncio.
    """
    from app.dominio.texto import normalizar

    for tabela, rotulo in ((BlocoTema, "N1"), (MacroTema, "N2"), (Tema, "N3")):
        divergentes = [
            nome
            for nome in sessao.scalars(
                select(tabela.nome).where(tabela.ativo.is_(True))
            )
            if normalizar(nome) != chave_do_nivel(nome)
        ]
        assert not divergentes, (
            f"{len(divergentes)} nome(s) de {rotulo} começam com número: "
            f"{divergentes[:5]}. A chave deles difere entre a regra antiga e a "
            "nova, e a próxima subida remaparia menções sem avisar."
        )


#: O PASSO NOVO (`subtema` como N3) NÃO TEM TESTE AQUI, de propósito.
#:
#: O que haveria para testar é que ele não mexe em menção já gravada, e isso é
#: fato da BASE, não do código: `subtema` é mapeado por uma fonte só (a
#: `approach_sl`, migration 0091) e a Approach nunca foi carregada — medido,
#: nulo em 104.670 de 104.670 linhas. Um teste disso no banco de teste, que
#: nasce vazio, contaria zero linhas e passaria por vácuo, provando nada. A
#: medição fica registrada no cabeçalho da `0098`, que é onde ela vale.


# -- 3. a precedência ----------------------------------------------------------


@pytest.fixture
def arvore_falsa() -> Arvore:
    """Uma árvore mínima e explícita: 2 pilares, 2 temas, 2 subtemas."""
    return Arvore(
        n1={chave_do_nivel("Governança"): 1, chave_do_nivel("Inovação"): 2},
        n2={chave_do_nivel("Conformidade"): 10, chave_do_nivel("Tecnologia"): 20},
        n3={chave_do_nivel("Auditoria"): 100, chave_do_nivel("Telemetria"): 200},
        n1_do_n2={10: 1, 20: 2},
        n2_do_n3={100: 10, 200: 20},
    )


def test_o_n3_manda_e_os_de_cima_sao_derivados(arvore_falsa: Arvore) -> None:
    assert arvore_falsa.resolver(tema_texto="Auditoria") == Niveis(
        n1_id=1, n2_id=10, n3_id=100
    )


def test_o_subtema_tambem_e_procurado_como_n3(arvore_falsa: Arvore) -> None:
    """A Approach traz os dois níveis vizinhos: `Tags (tema)` e `Tags (subtema)`.

    Sem este passo o N3 dela nunca resolveria — e é a única fonte que mapeia
    `subtema` (migration 0091).
    """
    assert arvore_falsa.resolver(subtema="Telemetria") == Niveis(
        n1_id=2, n2_id=20, n3_id=200
    )


def test_o_tema_como_n2_deriva_o_n1_e_deixa_o_n3_nulo(arvore_falsa: Arvore) -> None:
    """"se trazer N2 o N1 vai ser derivado do cadastro" — e o N3 fica nulo.

    NUNCA SE DESCE: um N2 tem 2,5 filhos em média e escolher um seria sorteio
    aparecendo nos gráficos como fato.
    """
    assert arvore_falsa.resolver(tema_texto="Conformidade") == Niveis(
        n1_id=1, n2_id=10, n3_id=None
    )


def test_o_atributo_e_o_n1_quando_nada_mais_casa(arvore_falsa: Arvore) -> None:
    """As 73.928 menções da Clipei que antes não tinham ligação nenhuma."""
    assert arvore_falsa.resolver(
        tema_texto="Assunto Que O Cadastro Nao Tem", atributo="2. Inovação"
    ) == Niveis(n1_id=2, n2_id=None, n3_id=None)


def test_o_n3_ganha_do_atributo_quando_os_dois_casam(arvore_falsa: Arvore) -> None:
    """O derivado ganha do declarado: o cadastro é a autoridade sobre a árvore.

    É o caso medido como 2 linhas em 27.317 — o atributo diz um pilar e a cadeia
    diz outro. O declarado não se perde: fica em `mencao.atributo`.
    """
    assert arvore_falsa.resolver(tema_texto="Auditoria", atributo="Inovação") == Niveis(
        n1_id=1, n2_id=10, n3_id=100
    )


def test_o_tema_ainda_e_procurado_como_n1(arvore_falsa: Arvore) -> None:
    """Último passo: o fornecedor cujo "tema" é o próprio pilar."""
    assert arvore_falsa.resolver(tema_texto="Governança") == Niveis(n1_id=1)


def test_nada_casa_e_nada_e_inventado(arvore_falsa: Arvore) -> None:
    vazio = arvore_falsa.resolver(
        tema_texto="Nada", subtema="Nada", atributo="Marca empregadora"
    )
    assert vazio == Niveis()
    assert vazio.nivel_mais_fundo is None


def test_o_tema_id_ja_conferido_entra_direto(arvore_falsa: Arvore) -> None:
    """Quem já tem N3 resolvido não é reconferido pelo texto."""
    assert arvore_falsa.resolver(tema_id=200, tema_texto="Auditoria") == Niveis(
        n1_id=2, n2_id=20, n3_id=200
    )


def test_tema_id_desconhecido_nao_sequestra_a_resolucao(arvore_falsa: Arvore) -> None:
    """`tema_id` de um N3 INATIVO cai para os passos seguintes.

    A árvore só carrega ativos, então um `tema_id` apontando para um dos 45
    desativados não está em `n2_do_n3`. Se ele passasse direto, a menção ficaria
    com N3 e sem N2/N1 — num nível que a tela não oferece mais.
    """
    assert arvore_falsa.resolver(tema_id=999, atributo="Governança") == Niveis(n1_id=1)


# -- 1. O TESTE QUE IMPORTA: a gravação e a leitura concordam ------------------

#: O corpus vem do que os fornecedores de verdade mandam, incluindo o que
#: quebra: as duas grafias do mesmo N1, o valor que o cadastro não tem, a célula
#: com vários assuntos, o nulo.
CORPUS: tuple[tuple[str | None, str | None, str | None], ...] = (
    # (tema_texto, subtema, atributo)
    (None, None, None),
    (None, None, "Governança"),
    (None, None, "1. Governança"),
    (None, None, "7. Prosperidade Compartilhada"),
    (None, None, "2. Eficiência Operacional e Qualidade"),
    (None, None, "Eficiência Operacional e Qualidade"),
    #: OS DOIS QUE O CADASTRO NÃO TEM — 914 menções.
    (None, None, "Marca empregadora"),
    (None, None, "Outros"),
    #: A célula com vários assuntos (52 valores da `Categoria` da Bites).
    ("Abastecimento, Agência de Regulação, Proteção ambiental", None, "Governança"),
    #: Texto que não casa com nada, com e sem atributo para salvar.
    ("Assunto inexistente", None, None),
    ("Assunto inexistente", None, "3. Crescimento e Solidez Financeira"),
    #: Branco e espaço, que não são a mesma coisa que nulo no Python.
    ("", "", ""),
    ("   ", None, None),
)


def _taxonomia_da_leitura(sessao: Session) -> cp.Taxonomia:
    """A `Taxonomia` da tela de aprofundamento, montada do mesmo cadastro."""
    pilares = [
        cp.PilarDaTaxonomia(id=i, codigo=c, nome=n)
        for i, c, n in sessao.execute(
            select(BlocoTema.id, BlocoTema.codigo, BlocoTema.nome).where(
                BlocoTema.ativo.is_(True)
            )
        )
    ]
    temas = [
        cp.TemaDaTaxonomia(id=i, codigo=c, nome=n, pilar_id=p)
        for i, c, n, p in sessao.execute(
            select(
                MacroTema.id, MacroTema.codigo, MacroTema.nome, MacroTema.bloco_tema_id
            ).where(MacroTema.ativo.is_(True))
        )
    ]
    subtemas = [
        cp.SubtemaDaTaxonomia(id=i, nome=n, tema_id=t)
        for i, n, t in sessao.execute(
            select(Tema.id, Tema.nome, Tema.macro_tema_id).where(
                Tema.ativo.is_(True), Tema.macro_tema_id.is_not(None)
            )
        )
    ]
    return cp.Taxonomia(pilares, temas, subtemas)


def test_a_gravacao_e_a_leitura_concordam(sessao: Session) -> None:
    """O pilar que a `0098` GRAVA é o mesmo que a tela CALCULA ao vivo.

    É O TESTE CENTRAL DESTE ARQUIVO. As duas implementações da precedência
    existem e vão continuar existindo um tempo (uma devolve ids para as colunas,
    a outra devolve códigos para a árvore da tela). O que não pode acontecer é
    elas discordarem: a coluna gravada contradiria a tela que lê ao vivo, e os
    dois números estariam na mesma reunião.

    SOBRE O CADASTRO DE VERDADE, e não sobre uma árvore montada à mão: é o
    cadastro que decide quais nomes existem em qual nível, e um fixture
    concordaria consigo mesmo.
    """
    arvore = temas_da_mencao.arvore(sessao)
    leitura = _taxonomia_da_leitura(sessao)
    nome_do_n1 = dict(
        sessao.execute(
            select(BlocoTema.id, BlocoTema.codigo).where(BlocoTema.ativo.is_(True))
        ).all()
    )

    divergencias = []
    for tema_texto, subtema, atributo in CORPUS:
        gravado = arvore.resolver(
            tema_texto=tema_texto, subtema=subtema, atributo=atributo
        )
        lido = leitura.resolver(
            tema_texto=tema_texto, subtema=subtema, atributo=atributo
        )
        pilar_gravado = (
            nome_do_n1.get(gravado.n1_id) if gravado.n1_id is not None else None
        )
        pilar_lido = None if lido.pilar == cp.SEM_PILAR else lido.pilar
        if pilar_gravado != pilar_lido:
            divergencias.append(
                f"  tema={tema_texto!r} subtema={subtema!r} atributo={atributo!r}: "
                f"gravaria {pilar_gravado!r}, a tela mostra {pilar_lido!r}"
            )

    assert not divergencias, (
        "a gravação da `0098` e a leitura de `consulta_profundidade` discordam "
        f"em {len(divergencias)} de {len(CORPUS)} casos:\n" + "\n".join(divergencias)
    )


def test_a_leitura_tambem_chega_ao_n3_pelo_mesmo_caminho(sessao: Session) -> None:
    """Não é só o pilar: o N3 gravado é o N3 que a tela resolve.

    Conferido com um subtema REAL do cadastro, escolhido no banco — escrever um
    nome à mão aqui amarraria o teste a uma versão da taxonomia.
    """
    nome, tema_id = sessao.execute(
        select(Tema.nome, Tema.id)
        .where(Tema.ativo.is_(True), Tema.macro_tema_id.is_not(None))
        .order_by(Tema.id)
        .limit(1)
    ).one()

    arvore = temas_da_mencao.arvore(sessao)
    gravado = arvore.resolver(tema_texto=nome)
    assert gravado.n3_id == tema_id
    assert gravado.n2_id is not None and gravado.n1_id is not None

    lido = _taxonomia_da_leitura(sessao).resolver(tema_texto=nome)
    assert lido.subtema not in ("", cp.SEM_SUBTEMA), (
        f"a tela não reconheceu como subtema o nome {nome!r}, que a gravação "
        "ligou ao N3 — as duas precedências divergiram no nível mais fundo."
    )


# -- o schema da 0098 ----------------------------------------------------------


def test_a_mencao_tem_as_tres_chaves_da_taxonomia(sessao: Session) -> None:
    colunas = set(
        sessao.scalars(
            text(
                "select column_name from information_schema.columns "
                "where table_name = 'mencao'"
            )
        )
    )
    assert {"bloco_tema_id", "macro_tema_id", "tema_id"} <= colunas


def test_os_indices_dos_niveis_existem_e_nao_reusam_nome(sessao: Session) -> None:
    """Nome de índice reusado com outra definição é NO-OP SILENCIOSO (ver 0052)."""
    indices = dict(
        sessao.execute(
            text("select indexname, indexdef from pg_indexes where tablename='mencao'")
        ).all()
    )
    for nome, coluna in (
        ("mencao_por_pilar", "bloco_tema_id"),
        ("mencao_por_tema_estrategico", "macro_tema_id"),
    ):
        assert nome in indices, f"a 0098 não criou {nome}"
        assert coluna in indices[nome], (
            f"{nome} existe mas não indexa {coluna}: "
            f"{indices[nome]}. Nome reusado de um índice anterior?"
        )


def test_apagar_nivel_da_taxonomia_com_mencao_falha(sessao: Session) -> None:
    """Sem `on delete`: a menção não vira nula nem é levada, a remoção FALHA.

    É o oposto de `instituicao_id` (que é `SET NULL` de propósito) e é
    deliberado: reorganizar a taxonomia é trabalho com decisão, e desligar 100
    mil linhas de um recorte em silêncio seria o pior jeito de fazê-lo.
    """
    acoes = sessao.execute(
        text(
            "select rc.delete_rule, kcu.column_name "
            "  from information_schema.referential_constraints rc "
            "  join information_schema.key_column_usage kcu "
            "    on kcu.constraint_name = rc.constraint_name "
            " where kcu.table_name = 'mencao' "
            "   and kcu.column_name in ('bloco_tema_id','macro_tema_id','tema_id')"
        )
    ).all()
    assert acoes, "as três chaves deveriam ter FK declarada"
    for regra, coluna in acoes:
        assert regra == "NO ACTION", (
            f"{coluna} ganhou `on delete {regra}`. Apagar um nível da taxonomia "
            "passaria a mexer em menção, que é fato do mês."
        )


# -- o backfill ----------------------------------------------------------------


def test_o_backfill_pega_quem_nao_tem_pilar_e_passa_o_tema_id(sessao: Session) -> None:
    """O critério é `bloco_tema_id is null`, e o `tema_id` da linha ENTRA.

    OS DOIS JUNTOS, porque o defeito foi a combinação deles. A primeira versão
    filtrava pelos TRÊS nulos e não passava o `tema_id`, e o resultado medido na
    base real foi `n3_sem_n1 = 29.701 de 29.701`: toda menção que já tinha
    subtema saiu do backfill sem pilar — exatamente as linhas cujo N1 é leitura
    direta da árvore.

    Quem garante a terminação é o CURSOR, não o filtro: a linha que não resolve
    é vista uma vez por execução e não é atualizada. Se alguém "consertar" o
    filtro de volta para os três nulos, este teste falha.
    """
    import inspect

    from app.comandos import ligar_mencoes_a_taxonomia as comando

    fonte = inspect.getsource(comando.executar)
    assert "Mencao.bloco_tema_id.is_(None)" in fonte
    assert "Mencao.tema_id.is_(None)" not in fonte, (
        "o filtro voltou a exigir `tema_id is null`, e com isso pula as menções "
        "que já têm N3 — que ficam com subtema e sem pilar."
    )
    assert "tema_id=tema_id" in fonte, (
        "o backfill parou de passar o `tema_id` da linha para o resolver, e sem "
        "ele o N2 e o N1 de quem já tem N3 não são derivados."
    )
    assert "Mencao.id > ultimo" in fonte, (
        "o cursor saiu. Sem ele, a linha que não resolve volta em todo lote e o "
        "comando não termina."
    )


def test_o_backfill_nunca_apaga_o_tema_id_que_a_linha_tem() -> None:
    """Ele grava as DUAS colunas novas. `tema_id` não entra no `values()`.

    O DEFEITO QUE ISTO PRENDE, e que estava escrito no comando: a linha cujo
    `tema_id` aponta para um tema DESATIVADO (ou ativo e órfão de N2) não passa
    pelo passo 1 do resolver — `n2_do_n3` só carrega ativo COM N2 —, cai para os
    passos de texto e volta com `n3_id=None`. Gravar isso apagaria a ligação que
    a linha já tinha.

    SÃO 0 LINHAS HOJE (nenhuma menção aponta para os 45 temas que a taxonomia v4
    desativou), e é por isso que vale um teste em vez de uma medição: a medição
    vale para a base de hoje, o teste vale para o dia em que alguém desativar um
    tema com menção pendurada.

    POR INSPEÇÃO DO FONTE, e não executando o comando, por uma razão explícita:
    `executar()` abre a própria sessão por `obter_fabrica_de_sessao()`, então ela
    não vê a transação do fixture — um teste de integração precisaria COMMITAR
    menções no banco de teste e deixá-las lá para os outros arquivos. O que
    importa aqui é uma propriedade do `update`, e é essa que se verifica.
    """
    import inspect

    from app.comandos import ligar_mencoes_a_taxonomia as comando

    fonte = inspect.getsource(comando.executar)
    corpo_do_update = fonte[fonte.index(".values(") :]
    assert "bloco_tema_id=" in corpo_do_update
    assert "macro_tema_id=" in corpo_do_update
    assert "tema_id=niveis.n3_id" not in corpo_do_update, (
        "o backfill voltou a gravar `tema_id`. Para a linha com tema desativado "
        "o resolver devolve `n3_id=None`, e isso APAGA a ligação que ela tinha."
    )


def test_o_backfill_nao_tem_regra_propria() -> None:
    """Ele CHAMA `Arvore.resolver`; não reimplementa a precedência.

    A `0097` pagou o preço de reimplementar `normalizar` em SQL: divergiu em 67
    de 87 valores reais. Este teste é o que impede alguém de "otimizar" o
    backfill transformando-o num `update ... case when` e reabrindo a porta.
    """
    import inspect

    from app.comandos import ligar_mencoes_a_taxonomia as comando

    fonte = inspect.getsource(comando)
    assert "arvore.resolver(" in fonte
    assert "regexp_replace" not in fonte and "translate(" not in fonte, (
        "o backfill passou a normalizar em SQL. É a regra do Python que vale — "
        "ver o cabeçalho da 0097."
    )


def test_a_mencao_sem_nivel_nenhum_nao_e_contada_como_ligada(sessao: Session) -> None:
    """`nivel_mais_fundo` é `None` quando nada casou, e é isso que o relatório diz."""
    assert Niveis().nivel_mais_fundo is None
    assert Niveis(n1_id=1).nivel_mais_fundo == "n1"
    assert Niveis(n1_id=1, n2_id=2).nivel_mais_fundo == "n2"
    assert Niveis(n1_id=1, n2_id=2, n3_id=3).nivel_mais_fundo == "n3"


def test_nenhum_nome_do_cadastro_resolve_para_n3_sem_pilar(sessao: Session) -> None:
    """Invariante da `0098`: quem ganha N3 ganha N2 e N1 junto.

    SOBRE OS 104 NOMES REAIS, um por um, e não sobre uma contagem em `mencao` —
    o banco de teste nasce vazio, e uma consulta a `mencao` aqui percorreria
    ZERO linhas e passaria por vácuo. Foi exatamente assim que o primeiro teste
    da `0097` deixou passar um backfill que divergia em 67 de 87 valores.

    A invariante vale porque `arvore()` só carrega N3 ativo COM N2 e
    `_subindo_do_n3` é o único caminho que grava `tema_id`. Este teste prova a
    primeira metade contra o cadastro de verdade: se alguém reativar um tema sem
    tema estratégico, ele falha aqui, antes de 100 mil menções ficarem num nível
    que a tela não desenha.
    """
    arvore = temas_da_mencao.arvore(sessao)
    nomes = sessao.scalars(select(Tema.nome).where(Tema.ativo.is_(True))).all()
    assert nomes, "o cadastro de subtemas está vazio — o teste não provaria nada"

    quebrados = []
    for nome in nomes:
        niveis = arvore.resolver(tema_texto=nome)
        if niveis.n3_id is not None and niveis.n1_id is None:
            quebrados.append(nome)

    assert not quebrados, (
        f"{len(quebrados)} subtema(s) resolvem para N3 sem pilar: {quebrados[:5]}. "
        "A menção ligada a eles não aparece em recorte por N1 nenhum."
    )
