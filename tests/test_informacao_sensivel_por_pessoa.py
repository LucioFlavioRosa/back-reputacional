"""A informação sensível é por PESSOA, e não só por papel.

POR QUE ESTA CAMADA EXISTE

`papel.ve_campos_sensiveis` está no banco desde 0003, e os OITO papéis semeados
a têm verdadeira. A bandeira nunca foi usada para negar: não havia papel que
abrisse o CRM e escondesse o relato. Quem recebia o CRM recebia, junto, a
transcrição do que foi conversado.

A migration 0087 acrescenta `usuario.acesso_sensivel`, e as duas se combinam:

    efetivo = papel.ve_campos_sensiveis AND usuario.acesso_sensivel

O papel é o TETO que o cargo permite; a coluna é se ESTA pessoa recebeu.

O QUE ESTE ARQUIVO GUARDA

A conjunção mora num lugar só — `UsuarioAtual.ve_campos_sensiveis` — e é dela
que TODAS as rotas leem. Um único consumidor que leia `papel.ve_campos_sensiveis`
direto reintroduz o vazamento numa rota só, e esse é o modo de falha mais difícil
de achar: as outras continuam certas, então a tela parece correta em quase todo
lugar. `test_ninguem_decide_payload_pela_bandeira_do_papel` é a guarda disso, e
ela olha a FONTE, porque não há teste de comportamento que cubra uma rota que
ninguém escreveu ainda.

O que precisa de SQL de verdade — a função `conceder_acesso` exigindo a decisão,
a limpeza na revogação, a trilha — vive em `test_e2e_postgres`.
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from app.dominio.identidade import Escopo, Papel, UsuarioAtual
from app.dominio.interacao import Interacao
from app.dominio.frentes import Frente
from app.esquemas.interacoes import InteracaoSaida

from datetime import date

#: Um papel que ALCANÇA o sensível — o teto aberto. É o caso dos oito semeados.
COM_TETO = Papel(
    codigo="crm_leitura",
    nome="CRM · leitura",
    ve_campos_sensiveis=True,
    ve_diretorio=True,
    pode_exportar=True,
    acessa_crm=True,
)

#: Um papel que NÃO alcança — o teto fechado. Nenhum papel semeado é assim hoje,
#: e o caso existe porque a bandeira é editável no banco e um papel novo é um
#: `insert`.
SEM_TETO = Papel(
    codigo="crm_leitura_restrito",
    nome="CRM · leitura sem sensível",
    ve_campos_sensiveis=False,
    acessa_crm=True,
)


def pessoa(papel: Papel | None, **ajustes) -> UsuarioAtual:
    return UsuarioAtual(
        id=uuid4(),
        nome="Fulano",
        email="f@aegea.com.br",
        papel=papel,
        escopo=Escopo.total(),
        **ajustes,
    )


# -- a conjunção ---------------------------------------------------------------


def test_teto_aberto_e_camada_concedida_alcanca():
    assert pessoa(COM_TETO, acesso_sensivel=True).ve_campos_sensiveis


def test_teto_aberto_e_camada_negada_nao_alcanca():
    """O CASO NOVO, e a razão de a coluna existir.

    Antes de 0087 este estado não era representável: com papel de CRM, o relato
    vinha junto, e a única saída era criar um papel por combinação.
    """
    assert not pessoa(COM_TETO, acesso_sensivel=False).ve_campos_sensiveis


def test_camada_concedida_nao_vence_teto_fechado():
    """Conjunção, e NÃO substituição.

    Se a coluna sobrepujasse o papel, marcar a pessoa daria a ela mais do que o
    cargo permite — e quem marcasse não teria como saber que estava fazendo
    isso. O teto do papel continua sendo teto.
    """
    assert not pessoa(SEM_TETO, acesso_sensivel=True).ve_campos_sensiveis


def test_sem_papel_nao_alcanca_por_mais_que_esteja_marcado():
    """O padrão `True` da coluna não concede nada sozinho.

    É o que torna `default true` em 0087 seguro: quem nasce no provisionamento
    nasce sem papel, e sem papel a conjunção já é falsa. O padrão só preserva o
    acesso de quem JÁ tinha papel no dia em que a coluna apareceu.
    """
    assert not pessoa(None, acesso_sensivel=True).ve_campos_sensiveis


def test_o_padrao_de_quem_tem_papel_e_alcancar():
    """Sem passar `acesso_sensivel`, quem tem teto alcança.

    Espelha o padrão da coluna, e é o que faz aplicar a migration não tirar o
    relato de ninguém em silêncio.
    """
    assert pessoa(COM_TETO).ve_campos_sensiveis


# -- o que some do payload -----------------------------------------------------


def nova(**ajustes) -> Interacao:
    padroes = dict(
        #: `id` explícito: o agregado só ganha o dele ao ser persistido, e o
        #: esquema de saída exige um.
        id=uuid4(),
        frente=Frente.IMPRENSA,
        data_interacao=date(2026, 5, 7),
        instituicao_id=uuid4(),
        uf="SP",
        status="confirmada",
        pauta="Reajuste tarifário em concessões",
    )
    return Interacao(**{**padroes, **ajustes})


def test_os_cinco_campos_do_crm_somem_juntos():
    """A LISTA CRESCEU COM A CAMADA, e sem isso ela seria quase inútil.

    Até 0087 só `relato` e `pendencias` saíam. Quem ficasse "sem sensível"
    perderia o relato e continuaria lendo `posicionamento` — a posição interna da
    companhia — e `observacoes`, que é campo livre e por isso recebe justamente
    o que não cabia nos outros.
    """
    interacao = nova(
        relato="Disse que não haveria reajuste antes de dezembro.",
        pendencias="Confirmar com o jurídico antes de responder.",
        posicionamento="Não comentar publicamente até a decisão da agência.",
        encaminhamentos="Enviar nota à diretoria até sexta.",
        observacoes="Pediu sigilo sobre a conversa.",
    )

    completa = InteracaoSaida.de_dominio(interacao, ve_campos_sensiveis=True)
    reduzida = InteracaoSaida.de_dominio(interacao, ve_campos_sensiveis=False)

    for campo in InteracaoSaida.CAMPOS_SENSIVEIS:
        assert getattr(completa, campo) is not None, (
            f"`{campo}` deveria estar no payload de quem alcança — "
            "o teste não prova nada se o campo não foi preenchido"
        )
        assert getattr(reduzida, campo) is None, f"`{campo}` vazou"


def test_a_pauta_fica_porque_sem_ela_nao_ha_registro():
    """O limite da ideia.

    Sem `pauta` o registro perde a identidade e a tela não tem o que listar.
    Quem não alcança o sensível continua lendo o conjunto como reputação — data,
    contraparte, pauta, situação —, que é o que o painel existe para fazer.
    """
    interacao = nova(relato="texto sensível")
    reduzida = InteracaoSaida.de_dominio(interacao, ve_campos_sensiveis=False)

    assert reduzida.pauta == "Reajuste tarifário em concessões"
    assert reduzida.data_interacao == date(2026, 5, 7)
    assert "pauta" not in InteracaoSaida.CAMPOS_SENSIVEIS


# -- esconder do payload não basta: a busca também esconde ---------------------


def test_a_busca_nao_varre_campo_sensivel_nenhum():
    """ESCONDER O CAMPO E DEIXÁ-LO PESQUISÁVEL É UM ORÁCULO.

    Sem receber o texto, a pessoa descobre o conteúdo por tentativa e erro —
    uma palavra por vez — e de passagem aprende QUAIS registros casam. O painel
    guarda com quem a Aegea conversa e o que foi dito; isso é a mesma coisa que
    entregar o campo, só mais devagar.

    ESTE TESTE NASCEU DE UM DEFEITO QUE EU ESCREVI. Ao acrescentar
    `posicionamento`, `encaminhamentos` e `observacoes` a `CAMPOS_SENSIVEIS`,
    `encaminhamentos` ficou fora do payload e CONTINUOU na lista incondicional
    da busca em `filtros_sql` — onde já estava desde antes, legitimamente, por
    não ser sensível. A regra existia escrita no docstring da função e valia só
    para `relato`. Achado da revisão do Codex.

    A guarda é por COMPORTAMENTO, e não por leitura da fonte: compila o `where`
    das duas maneiras e compara. `filtros_sql` vive em `banco/` e
    `CAMPOS_SENSIVEIS` em `esquemas/`, então importar um do outro para manter as
    listas juntas inverteria as camadas — a asserção aqui é o que as mantém
    coerentes sem acoplá-las.
    """
    from app.banco.filtros_sql import condicoes
    from app.dominio.identidade import Escopo
    from app.dominio.recorte import Recorte

    def sql_da_busca(*, sensiveis: bool) -> str:
        condicao = condicoes(
            Recorte(busca="reajuste"),
            escopo=Escopo.total(),
            busca_em_campos_sensiveis=sensiveis,
        )
        return " ".join(
            str(c.compile(compile_kwargs={"literal_binds": True})) for c in condicao
        )

    sem = sql_da_busca(sensiveis=False)
    com = sql_da_busca(sensiveis=True)

    for campo in InteracaoSaida.CAMPOS_SENSIVEIS:
        assert f"interacao.{campo}" not in sem, (
            f"`{campo}` é omitido do payload e continua pesquisável — "
            "é o oráculo descrito acima. Mova-o para dentro do "
            "`if em_campos_sensiveis` em `filtros_sql.condicoes`."
        )

    #: E O CONTRÁRIO TAMBÉM: quem alcança o sensível tem de continuar achando.
    #: Sem esta metade, "arrumar" o vazamento tirando os campos da busca para
    #: todo mundo passaria no teste e quebraria a busca de quem tem direito.
    assert "interacao.relato" in com
    assert "interacao.encaminhamentos" in com

    #: E A GUARDA SABE RECONHECER O FORMATO QUE ELA PROCURA.
    #:
    #: `pauta` é pesquisável para todo mundo e NÃO é sensível, então ela aparece
    #: nos dois SQL. É a prova de que a comparação por `interacao.<campo>` casa
    #: de verdade — sem ela, um dia em que o SQL compilado mudasse de forma
    #: (apelido de tabela, por exemplo) este teste passaria para sempre sem
    #: olhar para nada.
    assert "interacao.pauta" in sem
    assert "interacao.pauta" in com


# -- a guarda do seam ----------------------------------------------------------

#: Onde mora o código da aplicação.
APP = Path(__file__).resolve().parent.parent / "app"

#: O ÚNICO lugar onde ler a bandeira do papel direto é correto: é onde a
#: conjunção é feita. Qualquer outro é um consumidor decidindo payload pelo teto
#: em vez do efetivo — o vazamento que 0087 fecha.
#:
#: A lista é curta de propósito. Isentar um arquivo cega a guarda para uma
#: violação FUTURA dentro dele, então isentar "por garantia" é o jeito de a
#: guarda deixar de guardar. Os outros dois lugares que mencionam a bandeira —
#: `provisionar_usuario`, que copia a linha da tabela para o `Papel`, e
#: `api/acesso.py`, que lista o teto de cada papel para a tela — não precisam de
#: isenção: eles leem de `registro.` e de `p.`, e não de `papel.`.
LEITURAS_LEGITIMAS = {"dominio/identidade.py"}


def sem_prosa(linha: str) -> str:
    """A linha sem o que é texto para gente ler.

    SEM ISTO A GUARDA ACUSA A SI MESMA. Este projeto documenta decisão em
    comentário, e a decisão aqui é justamente "combina com
    `papel.ve_campos_sensiveis`" — a frase aparece em três arquivos que não
    decidem payload nenhum. Uma guarda que reprova a própria explicação obriga
    quem escreve a parar de explicar, e é assim que o comentário desaparece.

    Duas podas, e as duas valem para código Python normal:

        `...`   referência a código DENTRO de prosa. É a convenção do projeto, e
                código de verdade não põe o atributo entre acentos graves.
        #       comentário até o fim da linha.

    Não é um analisador: uma crase dentro de literal de texto confundiria. Vale
    porque o projeto não tem crase em literal — e, se tivesse, o erro seria
    deixar passar uma linha, nunca inventar uma.
    """
    return re.sub(r"`[^`]*`", "", linha).split("#", 1)[0]


def test_ninguem_decide_payload_pela_bandeira_do_papel():
    """A conjunção só vale se TODO mundo passar por ela.

    Um consumidor que leia `usuario.papel.ve_campos_sensiveis` recebe o TETO, e
    não o efetivo: entregaria o relato a quem teve a camada negada. E entregaria
    só naquela rota, o que é o pior formato de defeito de autorização — as
    outras continuam certas, então ninguém procura.

    A guarda é na FONTE porque não há teste de comportamento que cubra a rota
    que ainda não foi escrita. É o mesmo raciocínio das guardas de fonte do
    front.

    O QUE ELA NÃO PEGA, e vale estar escrito: ela casa o receptor chamado
    `papel`. `teto = usuario.papel; teto.ve_campos_sensiveis` passaria. É
    heurística, não análise — pega a forma que alguém escreveria sem pensar, que
    é justamente a que chega sem revisão.
    """
    culpados: list[str] = []

    for caminho in sorted(APP.rglob("*.py")):
        relativo = caminho.relative_to(APP).as_posix()
        if relativo in LEITURAS_LEGITIMAS:
            continue

        fonte = caminho.read_text(encoding="utf-8")
        for numero, linha in enumerate(fonte.splitlines(), start=1):
            # Só o ACESSO ao atributo via `papel`, e não a palavra solta: o nome
            # aparece legitimamente como nome de argumento nomeado
            # (`ve_campos_sensiveis=...`), que é quem CHAMA a propriedade, não
            # quem a contorna.
            if re.search(r"papel\s*\.\s*ve_campos_sensiveis", sem_prosa(linha)):
                culpados.append(f"{relativo}:{numero}: {linha.strip()}")

    assert culpados == [], (
        "Estes lugares leem o teto do papel em vez do acesso efetivo. "
        "Use `usuario.ve_campos_sensiveis`:\n  " + "\n  ".join(culpados)
    )


def test_a_guarda_reconhece_o_que_existe_para_pegar():
    """Guarda de fonte que nunca viu um positivo pode ter parado de casar.

    As duas formas que importam: o acesso direto pelo usuário e o acesso pelo
    papel já em mão.
    """
    assert re.search(
        r"papel\s*\.\s*ve_campos_sensiveis",
        "if usuario.papel.ve_campos_sensiveis:",
    )
    assert re.search(
        r"papel\s*\.\s*ve_campos_sensiveis",
        "ve_campos_sensiveis=papel.ve_campos_sensiveis,",
    )
    #: E NÃO denuncia a chamada certa — é ela que está em quinze lugares.
    assert not re.search(
        r"papel\s*\.\s*ve_campos_sensiveis",
        "ve_campos_sensiveis=usuario.ve_campos_sensiveis,",
    )


def test_a_guarda_esta_olhando_para_os_arquivos_de_verdade():
    arquivos = list(APP.rglob("*.py"))
    assert len(arquivos) > 50
    assert any(
        "ve_campos_sensiveis" in a.read_text(encoding="utf-8") for a in arquivos
    )
