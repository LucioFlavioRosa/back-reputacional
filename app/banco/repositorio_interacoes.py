"""Adaptador Postgres da porta de persistência.

Traduz entre o agregado do domínio e as tabelas. Os dicionários entram e saem
por `codigo` — o domínio nunca manipula id de enum, que é detalhe de banco.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.banco.filtros_sql import (
    condicoes,
    ordenar_por,
)
from app.banco.tabelas_catalogo import (
    Casa,
    Clima,
    Formato,
    Iniciativa,
    NaturezaOrgao,
    Resultado,
    Status,
    TipoInvestidor,
    Tramitacao,
)
from app.banco.tabelas_catalogo import (
    Frente as FrenteTabela,
)
from app.banco.tabelas_interacoes import (
    RELACAO_DA_EXTENSAO,
    ImprensaRegistro,
    InstitucionalRegistro,
    InteracaoPessoaAegea,
    InteracaoRegistro,
    InteracaoTema,
    InternaRegistro,
    InvestidoresRegistro,
    LegislativoRegistro,
)
from app.dominio.erros import RegraViolada
from app.dominio.frentes import (
    Extensao,
    Frente,
    Imprensa,
    Institucional,
    Interna,
    Investidores,
    Legislativo,
)
from app.dominio.identidade import Escopo
from app.dominio.interacao import (
    Interacao,
    ParticipacaoAegea,
)
from app.dominio.recorte import Recorte
from app.dominio.repositorio import Pagina


class RepositorioSQL:
    """Implementa `RepositorioDeInteracoes` sobre o Postgres."""

    def __init__(self, sessao: Session) -> None:
        self.sessao = sessao
        self._cache_de_codigos: dict[tuple[str, str], int] = {}

    # -- dicionários ---------------------------------------------------------

    def _id_de(self, tabela: type, codigo: str | None) -> int | None:
        """Converte `codigo` em `id`, com cache por sessão."""
        if codigo is None:
            return None

        chave = (tabela.__tablename__, codigo)
        if chave in self._cache_de_codigos:
            return self._cache_de_codigos[chave]

        encontrado = self.sessao.scalar(
            select(tabela.id).where(tabela.codigo == codigo)
        )
        if encontrado is None:
            raise RegraViolada(
                f"Valor desconhecido em {tabela.__tablename__}: {codigo!r}."
            )

        self._cache_de_codigos[chave] = encontrado
        return encontrado

    def _codigo_de(self, tabela: type, id_: int | None) -> str | None:
        if id_ is None:
            return None
        return self.sessao.scalar(select(tabela.codigo).where(tabela.id == id_))

    # -- escrita -------------------------------------------------------------

    def adicionar(self, interacao: Interacao) -> Interacao:
        registro = InteracaoRegistro()
        self._aplicar_no_registro(interacao, registro)
        self.sessao.add(registro)
        self.sessao.flush()
        return self._para_dominio(registro)

    def atualizar(self, interacao: Interacao) -> Interacao:
        if interacao.id is None:
            raise RegraViolada("Não é possível atualizar uma interação sem id.")

        registro = self.sessao.get(InteracaoRegistro, interacao.id)
        if registro is None:
            raise RegraViolada(f"Interação {interacao.id} não existe.")

        self._aplicar_no_registro(interacao, registro)
        registro.atualizado_em = datetime.now(UTC)
        self.sessao.flush()
        return self._para_dominio(registro)

    def _aplicar_no_registro(
        self, interacao: Interacao, registro: InteracaoRegistro
    ) -> None:
        registro.frente_id = self._id_de(FrenteTabela, interacao.frente.value)
        registro.data_interacao = interacao.data_interacao
        registro.instituicao_id = interacao.instituicao_id
        registro.interlocutor_id = interacao.interlocutor_id
        registro.unidade_negocio_id = interacao.unidade_negocio_id
        registro.esfera_id = interacao.esfera_id
        registro.uf = interacao.uf
        registro.tier = interacao.tier
        registro.stakeholder_id = interacao.stakeholder_id

        registro.status_id = self._id_de(Status, interacao.status)
        registro.clima_id = self._id_de(Clima, interacao.clima)
        registro.resultado_id = self._id_de(Resultado, interacao.resultado)
        registro.iniciativa_id = self._id_de(Iniciativa, interacao.iniciativa)

        registro.pauta = interacao.pauta
        registro.posicionamento = interacao.posicionamento
        registro.relato = interacao.relato
        registro.encaminhamentos = interacao.encaminhamentos
        registro.pendencias = interacao.pendencias
        registro.observacoes = interacao.observacoes
        registro.registro_url = interacao.registro_url

        registro.fonte = interacao.fonte
        registro.visivel = interacao.visivel
        registro.arquivado_em = interacao.arquivado_em

        if interacao.origem_aba is not None:
            registro.origem_aba = interacao.origem_aba
        if interacao.origem_linha is not None:
            registro.origem_linha = interacao.origem_linha
        if interacao.criado_por is not None:
            registro.criado_por = interacao.criado_por

        self._aplicar_extensao(interacao, registro)
        self._aplicar_temas(interacao, registro)
        self._aplicar_participacoes(interacao, registro)

    def _aplicar_extensao(
        self, interacao: Interacao, registro: InteracaoRegistro
    ) -> None:
        """Grava a extensão da frente e zera as das outras.

        Trocar a frente de um registro precisa limpar a extensão antiga, senão
        sobra dado órfão de uma frente que ele não é mais.
        """
        relacao_ativa = RELACAO_DA_EXTENSAO[interacao.frente.value]
        for nome in set(RELACAO_DA_EXTENSAO.values()):
            if nome != relacao_ativa:
                setattr(registro, nome, None)

        if interacao.extensao is None:
            setattr(registro, relacao_ativa, None)
            return

        atual = getattr(registro, relacao_ativa)
        match interacao.extensao:
            case Imprensa() as dados:
                atual = atual or ImprensaRegistro()
                atual.formato_id = self._id_de(Formato, dados.formato)
                atual.data_atendida = dados.data_atendida
                atual.data_publicacao = dados.data_publicacao
                atual.link_materia = dados.link_materia
                atual.mensagens_chave = list(dados.mensagens_chave) or None
            case Institucional() as dados:
                atual = atual or InstitucionalRegistro()
                atual.natureza_orgao_id = self._id_de(NaturezaOrgao, dados.natureza_orgao)
                atual.cargo_interlocutor = dados.cargo_interlocutor
                atual.nome_evento = dados.nome_evento
            case Legislativo() as dados:
                atual = atual or LegislativoRegistro()
                atual.casa_id = self._id_de(Casa, dados.casa)
                atual.tramitacao_id = self._id_de(Tramitacao, dados.tramitacao)
                atual.prioridade = dados.prioridade
                atual.ementa = dados.ementa
            case Investidores() as dados:
                atual = atual or InvestidoresRegistro()
                atual.tipo_investidor_id = self._id_de(TipoInvestidor, dados.tipo_investidor)
                atual.formato_id = self._id_de(Formato, dados.formato)
            case Interna() as dados:
                atual = atual or InternaRegistro()
                atual.natureza = dados.natureza
                atual.cumprimento = dados.cumprimento
                atual.complexidade = dados.complexidade
                atual.prazo_dias = dados.prazo_dias
                atual.data_retorno = dados.data_retorno
            case _:
                raise RegraViolada(
                    f"Extensão não suportada: {type(interacao.extensao).__name__}."
                )

        setattr(registro, relacao_ativa, atual)

    def _aplicar_temas(self, interacao: Interacao, registro: InteracaoRegistro) -> None:
        desejados = set(interacao.temas)
        registro.temas[:] = [
            vinculo for vinculo in registro.temas if vinculo.tema_id in desejados
        ]
        ja_ligados = {vinculo.tema_id for vinculo in registro.temas}
        registro.temas.extend(
            InteracaoTema(tema_id=tema_id) for tema_id in desejados - ja_ligados
        )

    def _aplicar_participacoes(
        self, interacao: Interacao, registro: InteracaoRegistro
    ) -> None:
        desejadas = {(p.pessoa_aegea_id, p.papel) for p in interacao.participacoes}
        registro.participacoes[:] = [
            vinculo
            for vinculo in registro.participacoes
            if (vinculo.pessoa_aegea_id, vinculo.papel) in desejadas
        ]
        ja_ligadas = {
            (vinculo.pessoa_aegea_id, vinculo.papel) for vinculo in registro.participacoes
        }
        registro.participacoes.extend(
            InteracaoPessoaAegea(pessoa_aegea_id=pessoa, papel=papel)
            for pessoa, papel in desejadas - ja_ligadas
        )

    # -- leitura -------------------------------------------------------------

    def obter(self, id: UUID, *, escopo: Escopo) -> Interacao | None:
        # `sessao.get()` buscava pela chave primária e pulava `condicoes()`
        # inteiro — era o caminho de leitura que não respeitava filtro nenhum.
        # Um `select` com as mesmas condições da listagem fecha isso: registro
        # arquivado, invisível ou fora do escopo simplesmente não volta.
        registro = self.sessao.scalar(
            select(InteracaoRegistro).where(
                InteracaoRegistro.id == id,
                # `Recorte()` não tem `busca`, então a bandeira é inerte aqui;
                # passar `False` mantém o padrão de negar por omissão.
                *condicoes(Recorte(), escopo=escopo, busca_em_campos_sensiveis=False),
            )
        )
        return self._para_dominio(registro) if registro else None

    def listar(
        self,
        recorte: Recorte,
        *,
        escopo: Escopo,
        busca_em_campos_sensiveis: bool,
        pagina: int = 1,
        tamanho: int = 50,
        ordenacao: str = "-data_interacao",
    ) -> Pagina:
        onde = condicoes(
            recorte,
            escopo=escopo,
            busca_em_campos_sensiveis=busca_em_campos_sensiveis,
        )

        total = self.sessao.scalar(
            select(func.count()).select_from(InteracaoRegistro).where(*onde)
        )

        consulta = (
            select(InteracaoRegistro)
            .where(*onde)
            .order_by(*ordenar_por(ordenacao))
            .offset((pagina - 1) * tamanho)
            .limit(tamanho)
        )

        registros = self.sessao.scalars(consulta).unique().all()
        return Pagina(
            itens=tuple(self._para_dominio(r) for r in registros),
            total=total or 0,
            pagina=pagina,
            tamanho=tamanho,
        )

    def contar(
        self, recorte: Recorte, *, escopo: Escopo, busca_em_campos_sensiveis: bool
    ) -> int:
        return (
            self.sessao.scalar(
                select(func.count())
                .select_from(InteracaoRegistro)
                .where(
                    *condicoes(
                        recorte,
                        escopo=escopo,
                        busca_em_campos_sensiveis=busca_em_campos_sensiveis,
                    )
                )
            )
            or 0
        )

    # -- tradução para o domínio ---------------------------------------------

    def _para_dominio(self, registro: InteracaoRegistro) -> Interacao:
        frente = Frente(self._codigo_de(FrenteTabela, registro.frente_id))
        return Interacao(
            id=registro.id,
            frente=frente,
            data_interacao=registro.data_interacao,
            instituicao_id=registro.instituicao_id,
            interlocutor_id=registro.interlocutor_id,
            unidade_negocio_id=registro.unidade_negocio_id,
            esfera_id=registro.esfera_id,
            uf=registro.uf,
            tier=registro.tier,
            stakeholder_id=registro.stakeholder_id,
            status=self._codigo_de(Status, registro.status_id),
            clima=self._codigo_de(Clima, registro.clima_id),
            resultado=self._codigo_de(Resultado, registro.resultado_id),
            iniciativa=self._codigo_de(Iniciativa, registro.iniciativa_id),
            pauta=registro.pauta,
            posicionamento=registro.posicionamento,
            relato=registro.relato,
            encaminhamentos=registro.encaminhamentos,
            pendencias=registro.pendencias,
            observacoes=registro.observacoes,
            registro_url=registro.registro_url,
            extensao=self._extensao_do_registro(registro, frente),
            temas=tuple(sorted(vinculo.tema_id for vinculo in registro.temas)),
            participacoes=tuple(
                ParticipacaoAegea(
                    pessoa_aegea_id=vinculo.pessoa_aegea_id, papel=vinculo.papel
                )
                for vinculo in registro.participacoes
            ),
            fonte=registro.fonte,
            visivel=registro.visivel,
            origem_aba=registro.origem_aba,
            origem_linha=registro.origem_linha,
            criado_por=registro.criado_por,
            criado_em=registro.criado_em,
            atualizado_em=registro.atualizado_em,
            arquivado_em=registro.arquivado_em,
        )

    def _extensao_do_registro(
        self, registro: InteracaoRegistro, frente: Frente
    ) -> Extensao | None:
        dados = getattr(registro, RELACAO_DA_EXTENSAO[frente.value])
        if dados is None:
            return None

        match dados:
            case ImprensaRegistro():
                return Imprensa(
                    formato=self._codigo_de(Formato, dados.formato_id),
                    data_atendida=dados.data_atendida,
                    data_publicacao=dados.data_publicacao,
                    link_materia=dados.link_materia,
                    mensagens_chave=tuple(dados.mensagens_chave or ()),
                )
            case InstitucionalRegistro():
                return Institucional(
                    natureza_orgao=self._codigo_de(NaturezaOrgao, dados.natureza_orgao_id),
                    cargo_interlocutor=dados.cargo_interlocutor,
                    nome_evento=dados.nome_evento,
                )
            case LegislativoRegistro():
                return Legislativo(
                    casa=self._codigo_de(Casa, dados.casa_id),
                    tramitacao=self._codigo_de(Tramitacao, dados.tramitacao_id),
                    prioridade=dados.prioridade,
                    ementa=dados.ementa,
                )
            case InvestidoresRegistro():
                return Investidores(
                    tipo_investidor=self._codigo_de(TipoInvestidor, dados.tipo_investidor_id),
                    formato=self._codigo_de(Formato, dados.formato_id),
                )
            case InternaRegistro():
                return Interna(
                    natureza=dados.natureza,
                    cumprimento=dados.cumprimento,
                    complexidade=dados.complexidade,
                    prazo_dias=dados.prazo_dias,
                    data_retorno=dados.data_retorno,
                )
        return None
