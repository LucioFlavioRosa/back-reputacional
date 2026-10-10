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

A DECISÃO DE NEGÓCIO QUE ISTO SERVE. A planilha passa a informar só o N3,
porque o resto é consequência: 104 temas ativos, nenhum sem N2; 41 N2, nenhum
sem N1; 100 das 104 ligações para risco. Dado o N3, o N2, o N1 e os riscos não
são escolha de quem preenche a planilha — são leitura do cadastro. Por isso a
coluna de atributo do fornecedor saiu do mapeamento da Bites: ela traria um N1
que pode DISCORDAR do N1 derivado, e aí a mesma menção teria dois.

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

from app.banco.tabelas_catalogo import Tema
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
