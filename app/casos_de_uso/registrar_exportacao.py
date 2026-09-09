"""Registra que alguém exportou a Base, e devolve a trilha.

ERA `registrar_relatorio`, e servia a dois casos: o documento impresso pela
tela e a exportação CSV. A tela de relatório saiu do produto; o que sobrou é o
que o plano de segurança pedia desde o começo — "Export CSV: quem exportou,
qual recorte, quantas linhas".

É TRILHA, E NÃO BARREIRA. O CSV é montado no navegador a partir da listagem já
baixada; um cliente modificado monta o arquivo sem chamar isto. O que se ganha
é saber, depois de um incidente, o que saiu pelo caminho normal.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.repositorio_interacoes import RepositorioSQL
from app.banco.tabelas_acesso import Usuario
from app.banco.tabelas_exportacoes import ExportacaoRegistro
from app.dominio.erros import NaoAutorizado
from app.dominio.identidade import UsuarioAtual
from app.dominio.recorte import Recorte
from app.observabilidade import obter_logger

logger = obter_logger("exportacoes")

#: Acima disto, o RECORTE exportado vira evento de atenção no log.
#:
#: O número é o teto que o front usa para derivar (`TETO_DE_DERIVACAO`): quem
#: exporta sobre a base inteira está levando tudo o que alcança.
RECORTE_QUE_MERECE_ATENCAO = 5000


@dataclass(frozen=True, slots=True)
class Exportacao:
    """Uma exportação registrada."""

    filtros: dict
    criado_por: UUID
    total_de_registros: int = 0
    id: UUID | None = None
    criado_em: datetime | None = None


@dataclass(frozen=True, slots=True)
class LinhaDoHistorico:
    """Uma exportação, na trilha."""

    id: UUID
    criado_em: datetime
    criado_por: str
    total_de_registros: int
    resumo_do_recorte: str = ""


def registrar(sessao: Session, *, recorte: Recorte, usuario: UsuarioAtual) -> Exportacao:
    """Grava a exportação e devolve o registro.

    O total é contado AQUI, e não recebido do cliente. Receber seria aceitar
    que quem exporta declare quanto exportou — e o número existe exatamente
    para o caso em que essa declaração não é confiável.
    """
    total = RepositorioSQL(sessao).contar(
        recorte,
        escopo=usuario.escopo,
        busca_em_campos_sensiveis=usuario.ve_campos_sensiveis,
    )

    registro = ExportacaoRegistro(
        filtros=_serializar(recorte),
        criado_por=usuario.id,
        total_de_registros=total,
    )
    sessao.add(registro)
    sessao.flush()

    # `warning`, e não `info`: uma saída com linhas individuais é o que se
    # procura depois de um incidente, e procurar entre `info` é procurar entre
    # milhares de linhas de rotina.
    #
    # Os campos do `extra` viram colunas em `customDimensions` no Application
    # Insights, e é deles que a consulta KQL depende. Guardar só o id do
    # usuário obrigaria a correlacionar com o banco na mão, no meio de um
    # incidente.
    #
    # O CSV NÃO CORTA: leva tudo que o recorte alcança, e por isso as linhas
    # levadas são o próprio total.
    logger.warning(
        "Exportação da Base por %s: %d linhas",
        usuario.email,
        total,
        extra={
            "evento": "exportacao_da_base",
            "exportacao_id": str(registro.id),
            "usuario_id": str(usuario.id),
            "usuario_email": usuario.email,
            "externo": usuario.externo,
            "linhas_exportadas": total,
            "total_do_recorte": total,
            "recorte_amplo": total >= RECORTE_QUE_MERECE_ATENCAO,
        },
    )

    return Exportacao(
        filtros=registro.filtros,
        criado_por=registro.criado_por,
        total_de_registros=registro.total_de_registros,
        id=registro.id,
        criado_em=registro.criado_em,
    )


def historico(
    sessao: Session, *, solicitante: UsuarioAtual, limite: int = 100
) -> list[LinhaDoHistorico]:
    """Quem exportou o quê.

    Exige `administra_acessos`. A trilha diz o que cada pessoa levou embora, e
    isso é informação sobre as pessoas, não sobre as interações — quem lê
    precisa ter o papel de quem responde por isso.
    """
    if solicitante.papel is None or not solicitante.papel.administra_acessos:
        raise NaoAutorizado("Seu perfil não consulta a trilha de exportações.")

    linhas = sessao.execute(
        select(ExportacaoRegistro, Usuario.nome)
        .join(Usuario, Usuario.id == ExportacaoRegistro.criado_por)
        .order_by(ExportacaoRegistro.criado_em.desc())
        .limit(limite)
    ).all()

    return [
        LinhaDoHistorico(
            id=registro.id,
            criado_em=registro.criado_em,
            criado_por=nome,
            total_de_registros=registro.total_de_registros,
            resumo_do_recorte=_resumir(registro.filtros),
        )
        for registro, nome in linhas
    ]


def _serializar(recorte: Recorte) -> dict:
    """O Recorte como dicionário, sem os campos vazios.

    Guardar `{"frente": null, "uf": null, ...}` para toda exportação encheria a
    coluna de nada e tornaria ilegível o que de fato foi filtrado.
    """
    bruto = asdict(recorte)
    periodo = bruto.pop("periodo", {}) or {}

    filtros = {
        chave: _texto(valor)
        for chave, valor in bruto.items()
        if valor not in (None, (), "", [])
    }
    for extremo in ("de", "ate"):
        if periodo.get(extremo):
            filtros[extremo] = _texto(periodo[extremo])
    return filtros


def _resumir(filtros: dict) -> str:
    """Uma linha legível, para quem lê a trilha."""
    if not filtros:
        return "todo o histórico"
    return ", ".join(f"{chave}={valor}" for chave, valor in sorted(filtros.items()))


def _texto(valor: object) -> object:
    """JSONB não guarda `date`, `UUID` nem tupla."""
    if isinstance(valor, (list, tuple)):
        return [str(item) for item in valor]
    if isinstance(valor, (int, float, bool)) or valor is None:
        return valor
    return str(valor)
