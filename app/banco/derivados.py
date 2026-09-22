"""O que se deriva do que já está gravado, onde está faltando.

Três lacunas do acervo importado deixavam a plataforma incoerente com o que
a Administração cadastra: a instituição sem relevância (e a agenda nova
passou a herdar a relevância da instituição), a instituição sem categoria de
público (filtro e gráfico "Tipo de Público" vazios) e a interação sem formato
("Tipo de Interação" vazio). As três têm um palpite razoável a partir do que
já existe — e é SÓ ISSO que este módulo grava: onde está `null`, nunca por
cima de uma escolha feita à mão.

As mesmas regras estão em SQL nas migrations 0043 (tier) e 0044 (formato),
para o banco já existente; aqui elas servem à base semeada, que nasce
depois das migrations. `test_derivados` confere que os dois espelhos dizem
a mesma coisa.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.banco.sugerir_categoria_de_publico import aplicar_sugestoes, gerar_sugestoes
from app.banco.tabelas_catalogo import FormatoInteracao
from app.banco.tabelas_catalogo import Frente as FrenteTabela
from app.banco.tabelas_interacoes import InteracaoRegistro
from app.banco.tabelas_stakeholders import Instituicao
from app.dominio.frentes import FORMATO_PADRAO_DA_FRENTE, Frente


def tier_das_instituicoes_pelas_agendas(sessao: Session) -> int:
    """A relevância da instituição é a que as agendas dela já registraram.

    A MODA dos tiers das agendas; empate desempata pelo tier mais alto (o
    número menor). Só onde `tier` está nulo. Devolve quantas ganharam tier.
    """
    moda = (
        select(
            InteracaoRegistro.instituicao_id.label("instituicao_id"),
            InteracaoRegistro.tier.label("tier"),
            func.count().label("n"),
        )
        .where(InteracaoRegistro.tier.is_not(None))
        .group_by(InteracaoRegistro.instituicao_id, InteracaoRegistro.tier)
        .subquery()
    )
    melhor = (
        select(moda.c.instituicao_id, moda.c.tier)
        .distinct(moda.c.instituicao_id)
        .order_by(moda.c.instituicao_id, moda.c.n.desc(), moda.c.tier.asc())
        .subquery()
    )
    resultado = sessao.execute(
        Instituicao.__table__.update()
        .where(Instituicao.tier.is_(None), Instituicao.id == melhor.c.instituicao_id)
        .values(tier=melhor.c.tier)
    )
    return resultado.rowcount or 0


def formato_das_interacoes_pela_frente(sessao: Session) -> int:
    """`FORMATO_PADRAO_DA_FRENTE`, gravado onde `formato_interacao_id` está nulo."""
    id_da_frente = {f.codigo: f.id for f in sessao.scalars(select(FrenteTabela))}
    id_do_formato = {f.codigo: f.id for f in sessao.scalars(select(FormatoInteracao))}
    total = 0
    for frente, formato in FORMATO_PADRAO_DA_FRENTE.items():
        resultado = sessao.execute(
            InteracaoRegistro.__table__.update()
            .where(
                InteracaoRegistro.formato_interacao_id.is_(None),
                InteracaoRegistro.frente_id == id_da_frente[Frente(frente).value],
            )
            .values(formato_interacao_id=id_do_formato[formato])
        )
        total += resultado.rowcount or 0
    return total


def categoria_das_instituicoes_pelo_sugeridor(sessao: Session) -> int:
    """O mesmo `--aplicar` do sugeridor: só confiança ALTA, só onde é nulo."""
    return aplicar_sugestoes(sessao, gerar_sugestoes(sessao))["categoria"]


def derivar_o_que_falta(sessao: Session) -> dict[str, int]:
    """As três, na ordem que faz sentido: categoria antes de tier não importa,
    mas ambas antes do `flush` final de quem chamou."""
    return {
        "tier_de_instituicao": tier_das_instituicoes_pelas_agendas(sessao),
        "categoria_de_instituicao": categoria_das_instituicoes_pelo_sugeridor(sessao),
        "formato_de_interacao": formato_das_interacoes_pela_frente(sessao),
    }


# Mantido para o teste dos espelhos: o SQL da 0044 precisa citar cada par.
SQL_PARES_DA_0044 = tuple(
    (Frente(frente).value, formato) for frente, formato in FORMATO_PADRAO_DA_FRENTE.items()
)

