"""Registrar uma geração de relatório, e consultar o histórico."""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.repositorio_interacoes import (
    RepositorioSQL,
)
from app.banco.tabelas_acesso import Usuario
from app.banco.tabelas_relatorios import (
    RelatorioRegistro,
)
from app.dominio.erros import NaoAutorizado
from app.dominio.identidade import UsuarioAtual
from app.dominio.recorte import Recorte
from app.dominio.relatorio import (
    LinhaDoHistorico,
    Relatorio,
)
from app.observabilidade import obter_logger

logger = obter_logger("relatorios")

#: Acima disto, o RECORTE consultado vira evento de atenção no log.
#:
#: O número é o teto que o front usa para derivar (`TETO_DE_DERIVACAO`): alguém
#: gerando relatório sobre a base inteira estava olhando tudo que alcança, o que
#: é sinal ainda que o documento leve poucas linhas.
RECORTE_QUE_MERECE_ATENCAO = 5000


def registrar(
    sessao: Session,
    *,
    secoes: tuple[str, ...],
    recorte: Recorte,
    usuario: UsuarioAtual,
    formato: str = "documento",
) -> Relatorio:
    """Grava a geração e devolve o registro.

    O total é contado AQUI, e não recebido do cliente. Receber seria aceitar que
    quem exporta declare quanto exportou — e o número existe exatamente para o
    caso em que essa declaração não é confiável.
    """
    relatorio = Relatorio(
        secoes=secoes,
        formato=formato,
        filtros=_serializar(recorte),
        criado_por=usuario.id,
        total_de_registros=RepositorioSQL(sessao).contar(
            recorte,
            escopo=usuario.escopo,
            busca_em_campos_sensiveis=usuario.ve_campos_sensiveis,
        ),
    )

    registro = RelatorioRegistro(
        secoes=list(relatorio.secoes),
        formato=relatorio.formato,
        filtros=relatorio.filtros,
        criado_por=relatorio.criado_por,
        total_de_registros=relatorio.total_de_registros,
    )
    sessao.add(registro)
    sessao.flush()

    completo = Relatorio(
        **{**asdict(relatorio), "id": registro.id, "criado_em": registro.criado_em}
    )

    if completo.leva_registros:
        # `warning`, e não `info`: um documento com linhas individuais é o que se
        # procura depois de um incidente, e procurar entre `info` é procurar
        # entre milhares de linhas de rotina.
        #
        # Os campos do `extra` viram colunas em `customDimensions` no
        # Application Insights, e é deles que a consulta KQL depende. Guardar só
        # o id do usuário obrigaria a correlacionar com o banco na mão, no meio
        # de um incidente.
        logger.warning(
            "Saída com registros (%s) por %s: %d linhas sobre recorte de %d",
            completo.formato,
            usuario.email,
            completo.registros_no_documento,
            completo.total_de_registros,
            extra={
                "evento": "relatorio_com_registros",
                "formato": completo.formato,
                "relatorio_id": str(completo.id),
                "usuario_id": str(usuario.id),
                "usuario_email": usuario.email,
                "externo": usuario.externo,
                # O que SAIU no documento.
                "linhas_no_documento": completo.registros_no_documento,
                # O que a pessoa estava OLHANDO.
                "total_do_recorte": completo.total_de_registros,
                "recorte_amplo": completo.total_de_registros >= RECORTE_QUE_MERECE_ATENCAO,
                "secoes": ",".join(completo.secoes),
            },
        )

    return completo


def historico(
    sessao: Session, *, solicitante: UsuarioAtual, limite: int = 100
) -> list[LinhaDoHistorico]:
    """O que foi gerado, por quem.

    Exige `administra_acessos`. A trilha diz o que cada pessoa levou embora, e
    isso é informação sobre as pessoas, não sobre as interações — quem lê
    precisa ter o papel de quem responde por isso.
    """
    if solicitante.papel is None or not solicitante.papel.administra_acessos:
        raise NaoAutorizado("Seu perfil não consulta o histórico de relatórios.")

    linhas = sessao.execute(
        select(RelatorioRegistro, Usuario.nome)
        .join(Usuario, Usuario.id == RelatorioRegistro.criado_por)
        .order_by(RelatorioRegistro.criado_em.desc())
        .limit(limite)
    ).all()

    return [
        LinhaDoHistorico(
            id=registro.id,
            criado_em=registro.criado_em,
            criado_por=nome,
            secoes=tuple(registro.secoes),
            total_de_registros=registro.total_de_registros,
            leva_registros="base" in registro.secoes,
            formato=registro.formato,
            resumo_do_recorte=_resumir(registro.filtros),
        )
        for registro, nome in linhas
    ]


def _serializar(recorte: Recorte) -> dict:
    """O Recorte como dicionário, sem os campos vazios.

    Guardar `{"frente": null, "uf": null, ...}` para todo relatório encheria a
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
    """Uma linha legível, para a tela de histórico."""
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
