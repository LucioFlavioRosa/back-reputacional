"""Ligar a menção ao tema do cadastro de assuntos.

POR QUE ISTO EXISTE. A menção guardava o assunto como texto do fornecedor
(`mencao.tema_texto`) e nada mais. O cadastro de assuntos já modela a árvore
inteira — `bloco_tema` (N1) → `macro_tema` (N2) → `tema` (N3, o "subtema") — e
pendura o risco no N3. As duas metades não se falavam: medido neste banco,
`mencao.tema_id` estava preenchido em ZERO das 29.898 menções.

E ISSO DEIXAVA UMA FEATURE INTEIRA INERTE. O filtro do dossiê por Pilar (N1),
Tema estratégico (N2) e Subtema (N3) já existe (`repositorio_score`,
`condicoes_do_filtro`) e casa justamente por `Mencao.tema_id`: sem o vínculo,
as opções voltavam vazias e o recorte nunca batia em nada.

A DECISÃO DE NEGÓCIO QUE ISTO SERVE. O fornecedor informa UM nível — o N1, o N2
ou o N3 —, e os de cima são consequência: 104 temas ativos, nenhum sem N2; 41
N2, nenhum sem N1; 100 das 104 ligações para risco. Dado o N3, o N2, o N1 e os
riscos não são escolha de quem preenche a planilha — são leitura do cadastro.

UM NÍVEL, E NÃO "SÓ O N3": esta frase dizia "a planilha passa a informar só o
N3", e era estreita demais. O dono do produto decidiu em 18/10/2026 que o
fornecedor traz o nível que ele TEM, e o cadastro deriva o resto para cima. A
Bites fala N3 (92 de 92 assuntos casam no cadastro); a Clipei fala N1 e só
casa 71 dos 326 assuntos que chama de N3 — descartar o N1 dela, como a `0069`
fez com a Bites, deixaria 73.928 menções (71% da base) fora de todo recorte por
pilar. `dominio/niveis_de_taxonomia.py` tem a medição inteira e o porquê de
isto NÃO reintroduzir a divergência que a `0079` mediu.

CASA POR NOME NORMALIZADO, e é seguro por uma razão medida: `tema(nome)` tem
índice único, e os 149 nomes (104 ativos + 45 desativados pela taxonomia v4)
normalizam para 149 chaves distintas — nenhuma colisão, nenhum nome que
normalize para vazio. Então um nome identifica uma linha só.

NÃO SE PARTE A CÉLULA EM VÍRGULAS, por mais que a planilha de hoje traga
"Fatura, Serviços". Cinco temas do cadastro têm vírgula no próprio nome —
"Perdas, fraudes e furtos", "Dívida, captação e solidez financeira" — e partir
destruiria justamente os nomes certos. Célula com mais de um assunto é conteúdo
a corrigir na planilha, e a conferência a mostra como desconhecida.

O CADASTRO É A AUTORIDADE: aqui não se cria tema. É a diferença em relação ao
vínculo do veículo (`veiculos_da_imprensa`), onde o que falta nasce no upload —
veículo é fato do mundo, assunto é taxonomia da companhia, e deixar o
fornecedor inventar assunto desfaria a árvore que a revisão da taxonomia
construiu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import BlocoTema, MacroTema, Tema
from app.dominio.niveis_de_taxonomia import Niveis, chave_do_nivel
from app.dominio.texto import normalizar


@dataclass(frozen=True, slots=True)
class TemaNaoLigado:
    """Um assunto que a planilha traz e o cadastro não reconhece."""

    #: O texto como o fornecedor o escreveu — é o que a pessoa vai procurar na
    #: planilha para corrigir.
    nome: str
    #: Quantas linhas do arquivo o citam. É por aqui que a lista ordena: o
    #: nome errado que aparece 300 vezes importa mais que o que aparece uma.
    mencoes: int
    #: SE O NOME EXISTE NO CADASTRO MAS ESTÁ DESATIVADO. São dois problemas
    #: diferentes com dois consertos diferentes: nome errado se conserta na
    #: planilha, tema desativado se conserta no cadastro (ou é a planilha que
    #: está usando a taxonomia antiga — a v4 desativou 45 temas).
    desativado: bool = False


@dataclass(frozen=True, slots=True)
class Reconhecimento:
    """O que a subida FARIA com os assuntos do arquivo, antes de gravar."""

    #: Quantas linhas achariam tema no cadastro.
    ligadas: int
    #: Quantas linhas vieram sem assunto nenhum. Não é erro: a planilha da
    #: Bites de 01–09/2026 veio com 84% da coluna em branco, e o acordo é que o
    #: conteúdo seja refeito. Mas o número tem de aparecer.
    sem_assunto: int
    nao_ligados: tuple[TemaNaoLigado, ...] = field(default_factory=tuple)

    @property
    def nao_ligadas(self) -> int:
        """Quantas linhas citam assunto que o cadastro não reconhece."""
        return sum(item.mencoes for item in self.nao_ligados)


def por_nome(sessao: Session) -> dict[str, int]:
    """Nome normalizado → id do tema, só dos ATIVOS.

    SÓ OS ATIVOS, e isto é escolha. A taxonomia v4 desativou 45 temas, e ligar
    a menção a um deles a faria aparecer num filtro que a tela não oferece mais
    — o dossiê lista o que as menções alcançam, e o front descarta o tema
    desativado. O número discordaria de si mesmo em duas telas.

    O nome que casa só com tema desativado NÃO fica em silêncio: a conferência
    o mostra como tal, porque o conserto é no cadastro e não na planilha.
    """
    return {
        normalizar(nome): ident
        for ident, nome in sessao.execute(
            select(Tema.id, Tema.nome).where(Tema.ativo.is_(True))
        )
    }


@dataclass(frozen=True, slots=True)
class Arvore:
    """A árvore do cadastro, carregada uma vez, para resolver os três níveis.

    UMA CONSULTA POR NÍVEL E POR GRAVAÇÃO — são 7 N1, 41 N2 e 104 N3 ativos, e o
    conjunto inteiro cabe em memória. É o mesmo motivo de `por_nome` existir:
    perguntar ao banco por linha faria da subida de 25.597 linhas um problema de
    rede, não de banco.

    SÓ OS ATIVOS, nos três níveis, pela mesma razão que `por_nome` explica: a
    taxonomia v4 desativou 45 N3, e ligar a menção a um deles a faria aparecer
    num filtro que a tela não oferece. Medido: dos 45 desativados, ZERO têm
    menção apontando para eles hoje, então nada se perde ao manter o critério.
    """

    #: chave do nome → id, por nível.
    n1: dict[str, int] = field(default_factory=dict)
    n2: dict[str, int] = field(default_factory=dict)
    n3: dict[str, int] = field(default_factory=dict)
    #: Os elos para SUBIR: filho → pai. Nunca o contrário.
    n1_do_n2: dict[int, int] = field(default_factory=dict)
    n2_do_n3: dict[int, int] = field(default_factory=dict)

    def _subindo_do_n3(self, n3_id: int) -> Niveis:
        """O N2 e o N1 de um N3. O ÚNICO lugar que sobe a árvore."""
        n2_id = self.n2_do_n3.get(n3_id)
        return Niveis(
            n1_id=self.n1_do_n2.get(n2_id) if n2_id is not None else None,
            n2_id=n2_id,
            n3_id=n3_id,
        )

    def resolver(
        self,
        *,
        tema_id: int | None = None,
        tema_texto: object = None,
        subtema: object = None,
        atributo: object = None,
    ) -> Niveis:
        """Os três níveis da menção, a partir do que o fornecedor falou.

        A REGRA, decisão de produto (dono do produto, 18/10/2026): o nível mais
        fundo que o cadastro RECONHECER manda, e os de cima são derivados dele.
        Nunca se desce. Ver `dominio/niveis_de_taxonomia.py` para a medição.

        ESTA PRECEDÊNCIA NÃO É NOVA, E É DE PROPÓSITO QUE NÃO É. Ela é a mesma
        de `consulta_profundidade.Taxonomia.resolver`, que resolve o pilar de
        cada menção na LEITURA desde que a tela de aprofundamento existe. O que
        a `0098` faz é GRAVAR o resultado, para que a menção tenha chave e possa
        ser filtrada e juntada entre fornecedores — não decidir de novo.

        `tests/test_niveis_da_mencao.py::test_a_gravacao_e_a_leitura_concordam`
        roda as duas sobre o mesmo corpus e exige o mesmo pilar. É o teste que
        importa aqui: enquanto houver duas implementações da precedência, o
        risco não é nenhuma delas estar errada — é elas DIVERGIREM, e aí a
        coluna gravada contradiz a tela que lê ao vivo, nos dois sentidos.

        O MAIS FUNDO QUE O CADASTRO RECONHECER, e não o mais fundo que o
        fornecedor MANDAR — a diferença é a Clipei: ela manda `Subcategoria`
        (o N3 dela) em quase toda linha, e o cadastro reconhece 27% delas. Nas
        outras 73% aquele N3 não existe para o cadastro, e aí o N1 que ela
        também manda é o que sobra. Se o "mais fundo mandado" mandasse, 73.928
        menções ficariam sem nível nenhum com um N1 bom na mão.

        E QUANDO O DERIVADO E O DECLARADO DISCORDAM, o derivado ganha, porque a
        árvore do cadastro é a autoridade sobre quem é pai de quem. Medido: 2
        linhas em 27.317. O declarado não se perde — fica em `mencao.atributo`,
        texto cru do fornecedor, e é de lá que a leitura marca `divergente`.
        """
        #: 1. O N3 QUE O CADASTRO JÁ RESOLVEU. Vem da conferência, não do texto.
        if tema_id is not None and tema_id in self.n2_do_n3:
            return self._subindo_do_n3(tema_id)

        #: 2 e 3. O TEXTO DO FORNECEDOR COMO N3 — o `tema` de quem fala N3 (a
        #: Bites, 92 de 92) e o `subtema` de quem traz os dois níveis vizinhos
        #: (a Approach: `Tags (tema)` e `Tags (subtema)`, migration 0091).
        for texto in (tema_texto, subtema):
            if not texto:
                continue
            achado = self.n3.get(normalizar(str(texto)))
            if achado is not None:
                return self._subindo_do_n3(achado)

        #: 4. O `tema` COMO N2, para o fornecedor cujo "tema" é o nível do meio.
        #: O N3 fica nulo: descer seria sortear um filho entre 2,5.
        n2_id = self.n2.get(normalizar(str(tema_texto))) if tema_texto else None
        if n2_id is not None:
            return Niveis(n1_id=self.n1_do_n2.get(n2_id), n2_id=n2_id)

        #: 5. O N1 PELO `atributo` (a Clipei) — e é o ÚNICO passo que recorta o
        #: prefixo numerado. É aqui que entram as 73.928 menções que antes não
        #: tinham ligação nenhuma, e as 26.603 que um `"2. "` deixava de fora.
        if atributo:
            achado = self.n1.get(chave_do_nivel(atributo))
            if achado is not None:
                return Niveis(n1_id=achado)

        #: 6. O `tema` COMO N1, sem recorte, para o fornecedor cujo "tema" é o
        #: próprio pilar.
        if tema_texto:
            achado = self.n1.get(normalizar(str(tema_texto)))
            if achado is not None:
                return Niveis(n1_id=achado)

        return Niveis()


def arvore(sessao: Session) -> Arvore:
    """A árvore ativa do cadastro, em quatro consultas.

    OS TRÊS MAPAS SÃO CHAVEADOS POR `normalizar`, o mesmo de `por_nome` e o
    mesmo que `consulta_profundidade.Taxonomia` usa nos índices dela. Quem
    recorta o prefixo numerado é a BUSCA do passo 5 (`chave_do_nivel(atributo)`),
    não a chave do mapa — exatamente como `Taxonomia._pilar_pelo_atributo` faz
    contra um `_pilar_por_nome` chaveado pelo normalizar puro.

    DAVA NA MESMA HOJE e não dá na mesma sempre: nenhum nome do cadastro começa
    com dígito, então chavear por um ou por outro produz as mesmas chaves (o
    `test_o_tema_id_de_hoje_nao_muda_com_a_regra_nova` prende isso). Mas
    chavear pelo recorte faria o mapa aceitar como "Governança" um cadastro
    chamado `"1. Governança"`, e aí as duas engenhas divergiriam de novo.

    `BlocoTema` e `MacroTema` não têm índice único no nome (só no `codigo`),
    diferente de `Tema` — então duas linhas poderiam normalizar para a mesma
    chave e uma sumiria do mapa em silêncio. Medido hoje: 7 N1 dão 7 chaves e 41
    N2 dão 41 chaves, nenhuma colisão. `tests/test_niveis_da_mencao.py` prende
    isso, porque é o cadastro que pode mudar, não este código.
    """
    return Arvore(
        n1={
            normalizar(nome): ident
            for ident, nome in sessao.execute(
                select(BlocoTema.id, BlocoTema.nome).where(BlocoTema.ativo.is_(True))
            )
        },
        n2={
            normalizar(nome): ident
            for ident, nome in sessao.execute(
                select(MacroTema.id, MacroTema.nome).where(MacroTema.ativo.is_(True))
            )
        },
        n3={
            normalizar(nome): ident
            for ident, nome in sessao.execute(
                select(Tema.id, Tema.nome).where(Tema.ativo.is_(True))
            )
        },
        n1_do_n2=dict(
            sessao.execute(
                select(MacroTema.id, MacroTema.bloco_tema_id).where(
                    MacroTema.ativo.is_(True)
                )
            ).all()  # type: ignore[arg-type]
        ),
        n2_do_n3=dict(
            sessao.execute(
                select(Tema.id, Tema.macro_tema_id).where(
                    Tema.ativo.is_(True), Tema.macro_tema_id.is_not(None)
                )
            ).all()  # type: ignore[arg-type]
        ),
    )


def _desativados(sessao: Session) -> dict[str, str]:
    """Nome normalizado → nome, dos temas desativados."""
    return {
        normalizar(nome): nome
        for (nome,) in sessao.execute(select(Tema.nome).where(Tema.ativo.is_(False)))
    }


def reconhecer(sessao: Session, assuntos: dict[str, int]) -> Reconhecimento:
    """O que o cadastro reconhece dos assuntos do arquivo. NÃO GRAVA NADA.

    `assuntos` é texto cru do fornecedor → quantas linhas o citam, e é o que
    `veiculos_da_planilha` faz do outro lado: a conferência precisa do número
    ANTES de alguém confirmar.
    """
    ativos = por_nome(sessao)
    desativados = _desativados(sessao)

    ligadas = 0
    sem_assunto = assuntos.get("", 0)
    nao_ligados: list[TemaNaoLigado] = []
    for texto, quantas in assuntos.items():
        if not texto.strip():
            continue
        chave = normalizar(texto)
        if chave in ativos:
            ligadas += quantas
            continue
        nao_ligados.append(
            TemaNaoLigado(
                nome=texto, mencoes=quantas, desativado=chave in desativados
            )
        )
    #: PELO VOLUME, porque é o nome errado que aparece muito que vale corrigir
    #: primeiro; empate pelo nome, para a lista não dançar entre duas aberturas.
    nao_ligados.sort(key=lambda item: (-item.mencoes, item.nome))
    return Reconhecimento(
        ligadas=ligadas,
        sem_assunto=sem_assunto,
        nao_ligados=tuple(nao_ligados),
    )
