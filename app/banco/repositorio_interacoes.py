"""Adaptador Postgres da porta de persistência.

Traduz entre o agregado do domínio e as tabelas. Os dicionários entram e saem
por `codigo` — o domínio nunca manipula id de enum, que é detalhe de banco.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text
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
    Arquivo,
    ImprensaRegistro,
    InstitucionalRegistro,
    InteracaoArea,
    InteracaoInterlocutor,
    InteracaoOrigem,
    InteracaoPessoaAegea,
    InteracaoRegistro,
    InteracaoTema,
    InternaRegistro,
    InvestidoresRegistro,
    LegislativoRegistro,
    Material,
    MaterialTema,
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
    ArquivoDoMaterial,
    Interacao,
    MaterialDaAgenda,
    ParticipacaoAegea,
    ParticipanteDaOutraParte,
)
from app.dominio.recorte import Recorte
from app.dominio.repositorio import Pagina


class RepositorioSQL:
    """Implementa `RepositorioDeInteracoes` sobre o Postgres."""

    def __init__(self, sessao: Session) -> None:
        self.sessao = sessao
        self._cache_de_codigos: dict[tuple[str, str], int] = {}
        #: id -> codigo, tabela por tabela, carregada INTEIRA na primeira leitura.
        self._codigos_por_id: dict[str, dict[int, str]] = {}
        #: Os bytes que perderam a linha nesta unidade de trabalho.
        #:
        #: O repositorio NAO fala com o blob: ele so anota o que ficou orfao. E
        #: proposital — o repositorio vive dentro da transacao, e apagar byte
        #: dentro dela e o jeito de destruir arquivo que um rollback vai fazer
        #: falta. Quem le esta lista e o caso de uso, depois do commit.
        self._caminhos_a_apagar: list[str] = []

    def caminhos_orfaos(self) -> list[str]:
        """O que apagar do blob DEPOIS que a transacao passar.

        Esvazia ao ser lida: chamada duas vezes, a segunda nao tenta apagar de
        novo o que ja foi.
        """
        caminhos, self._caminhos_a_apagar = self._caminhos_a_apagar, []
        return caminhos

    # -- dicionários ---------------------------------------------------------

    def _id_de(self, tabela: type, codigo: str | None) -> int | None:
        """Converte `codigo` em `id`, com cache por sessão.

        SÓ ACEITA CÓDIGO ATIVO. Desativar um valor de dicionário é como esta
        base aposenta vocabulário: a 0020 colapsou onze situações em três e
        marcou as outras oito `ativo = false` em vez de apagá-las, porque a
        trilha em `interacao_auditoria` ainda aponta para elas.

        Sem o filtro, o formulário oferecia três e a API aceitava as onze —
        qualquer outro cliente HTTP reintroduzia `atendido` na base, e o
        vocabulário que a migration acabara de unificar se partia de novo. O
        catálogo servido em `/api/dicionarios` já mostra só os ativos; a
        escrita passa a concordar com ele.
        """
        if codigo is None:
            return None

        chave = (tabela.__tablename__, codigo)
        if chave in self._cache_de_codigos:
            return self._cache_de_codigos[chave]

        consulta = select(tabela.id).where(tabela.codigo == codigo)
        coluna_ativo = getattr(tabela, "ativo", None)
        if coluna_ativo is not None:
            consulta = consulta.where(coluna_ativo.is_(True))

        encontrado = self.sessao.scalar(consulta)
        if encontrado is None:
            # Distinguir "não existe" de "foi aposentado": quem manda um código
            # antigo precisa saber que ele existiu, senão procura erro de
            # digitação onde houve mudança de vocabulário.
            existe = coluna_ativo is not None and self.sessao.scalar(
                select(tabela.id).where(tabela.codigo == codigo)
            )
            if existe:
                raise RegraViolada(
                    f"Valor desativado em {tabela.__tablename__}: {codigo!r}. "
                    "Ele continua no catálogo para dar rótulo ao histórico, "
                    "mas não pode ser gravado. Veja os valores em uso em "
                    "/api/dicionarios."
                )
            raise RegraViolada(
                f"Valor desconhecido em {tabela.__tablename__}: {codigo!r}."
            )

        self._cache_de_codigos[chave] = encontrado
        return encontrado

    def _codigo_de(self, tabela: type, id_: int | None) -> str | None:
        """Converte `id` em `codigo` — sem ir ao banco por linha.

        A LEITURA DE UMA PAGINA PASSAVA AQUI MIL VEZES. Cada agenda tem seis
        ou sete codigos (frente, status, clima, resultado, iniciativa, clima
        esperado, os da extensao), e uma pagina tem duzentas: eram mais de mil
        `SELECT` de uma linha por pagina, e a Base levava mais de um segundo
        para abrir. As tabelas de dicionario tem dezenas de linhas — cabem
        inteiras numa leitura por tabela, uma vez por repositorio.

        INCLUI OS DESATIVADOS, de proposito: quem le e o historico, e o
        historico aponta para vocabulario aposentado (ver `_id_de`). A
        escrita, essa, continua recusando o que foi aposentado.
        """
        if id_ is None:
            return None
        nome = tabela.__tablename__
        codigos = self._codigos_por_id.get(nome)
        if codigos is None:
            codigos = dict(self.sessao.execute(select(tabela.id, tabela.codigo)).all())
            self._codigos_por_id[nome] = codigos
        return codigos.get(id_)

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
        registro.modalidade = interacao.modalidade
        registro.local = interacao.local

        registro.fonte = interacao.fonte
        registro.visivel = interacao.visivel
        registro.arquivado_em = interacao.arquivado_em

        if interacao.origem_aba is not None:
            registro.origem_aba = interacao.origem_aba
        if interacao.origem_linha is not None:
            registro.origem_linha = interacao.origem_linha
        if interacao.criado_por is not None:
            registro.criado_por = interacao.criado_por

        # Os campos do ciclo sao todos anulaveis, e nulo significa NAO
        # INFORMADO — por isso sao copiados direto, sem o `if is not None` que
        # protege os campos acima. La, omitir preserva; aqui, mandar nulo LIMPA,
        # e e isso que o formulario precisa poder fazer quando alguem apaga uma
        # expectativa escrita por engano.
        registro.expectativa = interacao.expectativa
        registro.clima_esperado_id = self._id_de(
            Clima, interacao.clima_esperado
        )
        registro.declinado_por = interacao.declinado_por
        registro.motivo_declinio = interacao.motivo_declinio
        registro.nota_situacao = interacao.nota_situacao
        self._aplicar_origens(interacao, registro)
        registro.preve_desdobramento = interacao.preve_desdobramento

        self._aplicar_extensao(interacao, registro)
        self._aplicar_temas(interacao, registro)
        self._aplicar_areas(interacao, registro)
        self._aplicar_participacoes(interacao, registro)
        self._aplicar_outra_parte(interacao, registro)
        self._aplicar_materiais(interacao, registro)

    def _aplicar_origens(
        self, interacao: Interacao, registro: InteracaoRegistro
    ) -> None:
        """Substitui a lista de origens, casando por (interacao, origem).

        Nao apaga e recria: o elo que permanece fica intocado, e a trilha nao
        registra uma saida e uma entrada para uma relacao que nunca mudou.

        A guarda de ciclo roda so para o que ENTRA agora. Revalidar os elos que
        ja estavam custaria uma travessia por elo a cada salvamento de qualquer
        campo — e eles ja passaram pela guarda quando entraram.
        """
        atuais = {v.origem_id: v for v in registro.origens}
        desejadas = set(interacao.origens)

        for origem_id, vinculo in atuais.items():
            if origem_id not in desejadas:
                registro.origens.remove(vinculo)

        novas = desejadas - set(atuais)
        if novas:
            self._exigir_que_nao_feche_ciclo(interacao.id, novas)
            registro.origens.extend(
                InteracaoOrigem(interacao_id=registro.id, origem_id=origem_id)
                for origem_id in novas
            )

    def _exigir_que_nao_feche_ciclo(self, alvo, origens) -> None:
        """Uma agenda não pode descender de si mesma, em nenhuma profundidade.

        O banco barra `A -> A` com um `check`, e o domínio dá a mensagem. Mas
        `A -> B -> A` passa pelos dois e fecha um anel: qualquer leitura que
        suba a cadeia — "de onde veio esta agenda?", que é o que o grafo faz —
        roda para sempre, e a tela trava.

        É TRAVESSIA DE GRAFO, e não de cadeia: com vários pais, cada nó tem N
        antecessores e o caminho se ramifica. Um ciclo pode fechar por qualquer
        ramo, e checar só o primeiro deixaria passar o resto.

        `union` (e não `union all`) é o que faz a travessia terminar num grafo
        com losangos — A e B levam a C, e ambos vêm de X: sem deduplicar, X é
        visitado uma vez por caminho, e o custo explode antes da profundidade
        máxima.

        `profundidade < 50` continua sendo o freio para o caso de os dados JÁ
        estarem em anel — sem ele, a própria checagem herdaria o laço.
        """
        fecharia = self.sessao.scalar(
            text(
                """
                with recursive antecessores(id, profundidade) as (
                  select origem_id, 1
                    from interacao_origem
                   where interacao_id = any(:origens)
                  union
                  select o.origem_id, a.profundidade + 1
                    from interacao_origem o
                    join antecessores a on o.interacao_id = a.id
                   where a.profundidade < 50
                )
                select :alvo = any(:origens)
                    or exists (select 1 from antecessores where id = :alvo)
                """
            ),
            {"origens": list(origens), "alvo": alvo},
        )
        if fecharia:
            raise RegraViolada(
                "Essa agenda já descende desta, direta ou indiretamente. "
                "Apontar uma para a outra fecharia um ciclo, e o histórico "
                "da relação deixaria de ter começo."
            )

    def _aplicar_outra_parte(
        self, interacao: Interacao, registro: InteracaoRegistro
    ) -> None:
        """Substitui a lista de participantes da outra parte.

        Mesmo padrao de `_aplicar_temas`: mantem quem continua, acrescenta quem
        entrou, e deixa o `delete-orphan` levar quem saiu. O gatilho
        `auditar_interacao_interlocutor` registra as duas pontas, entao a ficha
        consegue dizer quem entrou e quem saiu da agenda, e quando.

        A PRESENCA e atualizada em quem ja estava: quem esta como `previsto`
        vira `presente` depois da reuniao sem sair e voltar da lista — o que
        deixaria dois eventos na trilha para um fato so.
        """
        # REBAIXA ANTES DE PROMOVER, e descarrega no meio.
        #
        # O indice unico parcial (`where principal`) e conferido a cada comando,
        # e nao no fim da transacao. Indice parcial nao pode ser `deferrable`:
        # so constraints podem, e constraint unica nao aceita `where`.
        #
        # Sem este passo, trocar o principal de A para B deixava os dois
        # marcados durante o flush e o banco recusava com `duplicate key`. Dava
        # 500 em dois caminhos reais — `PATCH` mandando lista e coluna juntas, e
        # trocar para alguem que ja estava na lista como participante comum.
        #
        # So quando a marca MUDA de dono: rebaixar e repromover a mesma pessoa a
        # cada salvamento seriam dois `UPDATE` inuteis em toda edicao.
        novo_principal = next(
            (p.interlocutor_id for p in interacao.outra_parte if p.principal), None
        )
        #
        # Rebaixa TODOS os marcados que não são o novo principal, e não só
        # quando "o primeiro marcado difere". A diferença aparece se o banco já
        # tiver mais de um marcado — estado que o índice impede de nascer, mas
        # que uma migração futura ou um `UPDATE` à mão podem produzir. Uma
        # condição que só olha o primeiro deixaria o segundo passar, e o
        # `duplicate key` voltaria sem explicação.
        a_rebaixar = [
            vinculo
            for vinculo in registro.outra_parte
            if vinculo.principal and vinculo.interlocutor_id != novo_principal
        ]
        if a_rebaixar:
            for vinculo in a_rebaixar:
                vinculo.principal = False
            self.sessao.flush()

        desejados = {p.interlocutor_id: p for p in interacao.outra_parte}
        registro.outra_parte[:] = [
            vinculo
            for vinculo in registro.outra_parte
            if vinculo.interlocutor_id in desejados
        ]
        for vinculo in registro.outra_parte:
            pedido = desejados[vinculo.interlocutor_id]
            vinculo.presenca = pedido.presenca
            vinculo.principal = pedido.principal

        ja_ligados = {vinculo.interlocutor_id for vinculo in registro.outra_parte}
        registro.outra_parte.extend(
            InteracaoInterlocutor(
                interlocutor_id=pessoa,
                presenca=pedido.presenca,
                principal=pedido.principal,
            )
            for pessoa, pedido in desejados.items()
            if pessoa not in ja_ligados
        )

        # A LISTA É A FONTE DA VERDADE; A COLUNA É PROJEÇÃO DELA.
        #
        # `interacao.interlocutor_id` existe porque 67 usos dependem dele —
        # filtros, relatórios, exportação, diretório. Mas duas fontes só não
        # divergem quando UMA manda e a outra segue, e aqui quem manda é a
        # lista: é ela que a ficha mostra e que o formulário edita.
        #
        # Rederivar o principal a partir da coluna, na ausência de marca, faria
        # o sistema desfazer uma remoção calado: tirar o principal da lista o
        # traria de volta, e `interlocutor_id: null` sozinho não limparia nada.
        # Não haveria como removê-lo por um caminho só, e nenhuma mensagem
        # diria isso.
        principal = next(
            (p for p in interacao.outra_parte if p.principal), None
        )

        if principal is not None:
            registro.interlocutor_id = principal.interlocutor_id

        elif not interacao.outra_parte and interacao.interlocutor_id is not None:
            # LISTA VAZIA É "NÃO ESTOU CUIDANDO DISTO", e não "não há ninguém".
            #
            # É o formato de quem informa só a coluna: o `POST` de hoje, os
            # testes antigos, e a importação de planilha. Nesses casos a coluna
            # manda, e a linha é criada para o interlocutor não ficar de fora da
            # própria agenda — o mesmo que a migration fez com os 60 registros.
            alvo = next(
                (
                    vinculo
                    for vinculo in registro.outra_parte
                    if vinculo.interlocutor_id == interacao.interlocutor_id
                ),
                None,
            )
            if alvo is None:
                alvo = InteracaoInterlocutor(
                    interlocutor_id=interacao.interlocutor_id
                )
                registro.outra_parte.append(alvo)
            alvo.principal = True
            registro.interlocutor_id = interacao.interlocutor_id

        else:
            # LISTA COM GENTE E SEM MARCA É "ESTES SÃO OS PARTICIPANTES, E
            # NENHUM DELES REPRESENTA A OUTRA PARTE".
            #
            # É assim que se REMOVE o principal, e por um caminho só: basta
            # mandar a lista sem ele. A coluna acompanha.
            registro.interlocutor_id = None
            for vinculo in registro.outra_parte:
                vinculo.principal = False

    def _aplicar_materiais(
        self, interacao: Interacao, registro: InteracaoRegistro
    ) -> None:
        """Casa por `id`: quem já existe é ATUALIZADO, não recriado.

        A primeira versão limpava a lista e reinseria tudo, com o argumento de
        que material não tem identidade natural. O argumento se contradizia:
        a resposta da API devolve `id` justamente porque a tela precisa
        apagar um material específico. Se o `id` muda a cada salvamento, ele não
        identifica nada — e um `PATCH` de `relato` trocaria os `id`s de todos os
        materiais da agenda, quebrando a tela aberta de quem estivesse editando.

        Material NOVO chega sem `id` e ganha um. Material que ficou de fora da
        lista some, pelo `delete-orphan`.

        `criado_por` vem de quem está salvando, e só na criação: reescrevê-lo na
        edição diria que a última pessoa a mexer na agenda cadastrou o material.
        """
        por_id = {m.id: m for m in registro.materiais if m.id is not None}
        mantidos: list[Material] = []
        autor = interacao.criado_por or registro.criado_por
        #: Os arquivos que PERDERAM seu material. Um material excluido pela
        #: tela, ou que trocou de arquivo, deixa a linha de `arquivo` e o byte
        #: no blob sem dono — `on delete restrict` protege o arquivo de sumir
        #: por baixo do material, e nao o contrario.
        antes = {m.id: m.arquivo_id for m in registro.materiais if m.arquivo_id}

        for material in interacao.materiais:
            existente = por_id.get(material.id) if material.id else None
            if existente is not None:
                existente.momento = material.momento
                existente.titulo = material.titulo.strip()
                existente.url = material.url
                existente.arquivo_id = material.arquivo_id
                existente.referencia_id = material.referencia_id
                existente.observacao = material.observacao
                _casar_temas(existente, material.temas)
                mantidos.append(existente)
            else:
                mantidos.append(
                    _novo_material(material, autor=autor)
                )

        registro.materiais[:] = mantidos

        # O ARQUIVO SEGUE O MATERIAL ATE O FIM.
        #
        # Sem isto, remover um material pela tela deixava a linha de `arquivo`
        # e o byte no blob para sempre: o material some pelo `delete-orphan`, e
        # nada olha para o que ele apontava. O painel passaria a pagar
        # armazenamento por documento que ninguem alcanca mais.
        #
        # O BYTE NAO E APAGADO AQUI. Aqui some a LINHA, dentro da transacao;
        # quem apaga o byte e o caso de uso, DEPOIS do commit. Na ordem
        # inversa, um rollback devolveria a linha apontando para o vazio — e
        # essa perda e irreversivel, enquanto um byte orfao no contenedor nao
        # quebra nada.
        depois = {m.arquivo_id for m in mantidos if m.arquivo_id}
        orfaos = [aid for aid in antes.values() if aid not in depois]
        if orfaos:
            for arquivo in self.sessao.scalars(
                select(Arquivo).where(Arquivo.id.in_(orfaos))
            ):
                self._caminhos_a_apagar.append(arquivo.caminho)
                self.sessao.delete(arquivo)

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

    def _aplicar_areas(self, interacao: Interacao, registro: InteracaoRegistro) -> None:
        """Mesmo padrão de `_aplicar_temas`: mantém quem continua, acrescenta
        quem entrou, e deixa o `delete-orphan` levar quem saiu."""
        desejadas = set(interacao.areas)
        registro.areas[:] = [
            vinculo for vinculo in registro.areas if vinculo.area_id in desejadas
        ]
        ja_ligadas = {vinculo.area_id for vinculo in registro.areas}
        registro.areas.extend(
            InteracaoArea(area_id=area_id) for area_id in desejadas - ja_ligadas
        )

    def _aplicar_participacoes(
        self, interacao: Interacao, registro: InteracaoRegistro
    ) -> None:
        # A PRESENCA ENTRA NO VALOR, e nao na chave.
        #
        # A chave e (pessoa, papel), porque e isso que identifica a participacao.
        # A presenca e um ATRIBUTO dela, e tratar como parte da chave faria o
        # porta-voz sair e voltar da lista quando `previsto` virasse `presente`
        # — dois eventos na trilha para uma confirmacao de presenca.
        desejadas = {
            (p.pessoa_aegea_id, p.papel): p.presenca for p in interacao.participacoes
        }
        registro.participacoes[:] = [
            vinculo
            for vinculo in registro.participacoes
            if (vinculo.pessoa_aegea_id, vinculo.papel) in desejadas
        ]
        for vinculo in registro.participacoes:
            vinculo.presenca = desejadas[(vinculo.pessoa_aegea_id, vinculo.papel)]
        ja_ligadas = {
            (vinculo.pessoa_aegea_id, vinculo.papel) for vinculo in registro.participacoes
        }
        registro.participacoes.extend(
            InteracaoPessoaAegea(
                pessoa_aegea_id=pessoa, papel=papel, presenca=presenca
            )
            for (pessoa, papel), presenca in desejadas.items()
            if (pessoa, papel) not in ja_ligadas
        )

    # -- leitura -------------------------------------------------------------

    def obter(
        self, id: UUID, *, escopo: Escopo, para_edicao: bool = False
    ) -> Interacao | None:
        """Lê uma interação. `para_edicao` TRAVA a linha até o fim da transação.

        Por que travar, e por que só na edição:

        Duas pessoas editando a MESMA agenda ao mesmo tempo liam o estado
        antigo, cada uma decidia quem é o principal e as duas gravavam. O
        índice único parcial recusava a segunda com `duplicate key`, e a tela
        recebia 500 — sem que ninguém tivesse feito nada errado.

        Rebaixar antes de promover resolve a ordem DENTRO de uma sessão; não
        serializa duas. Quem serializa é este `for update`: a segunda espera a
        primeira terminar e então lê o estado NOVO, em vez de decidir sobre um
        retrato vencido.

        A leitura comum não trava — travar em toda consulta serializaria o
        painel inteiro para proteger um caso que só existe na escrita. É o
        mesmo desenho de `conceder_acesso` (migration 0006), que trava o alvo
        exatamente pela mesma razão.
        """
        # NÃO É `sessao.get()`: buscar pela chave primária pularia `condicoes()`
        # inteiro, e seria o caminho de leitura que não respeita filtro nenhum.
        # Um `select` com as mesmas condições da listagem fecha isso: registro
        # arquivado, invisível ou fora do escopo simplesmente não volta.
        consulta = select(InteracaoRegistro).where(
            InteracaoRegistro.id == id,
            # `Recorte()` não tem `busca`, então a bandeira é inerte aqui;
            # passar `False` mantém o padrão de negar por omissão.
            *condicoes(Recorte(), escopo=escopo, busca_em_campos_sensiveis=False),
        )
        if para_edicao:
            # `of` limita a trava à linha de `interacao`: sem isso o Postgres
            # tentaria travar também as tabelas trazidas pelos `join` das
            # condições de escopo, e travar dicionário serializaria escritas
            # que não têm nada com esta agenda.
            consulta = consulta.with_for_update(of=InteracaoRegistro)
        registro = self.sessao.scalar(consulta)
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
        # UMA consulta para a pagina inteira, e nao uma por linha.
        arquivadas = self._arquivadas_entre(
            {v.origem_id for r in registros for v in r.origens}
            | {v.interacao_id for r in registros for v in r.derivadas}
        )
        return Pagina(
            itens=tuple(
                self._para_dominio(r, arquivadas=arquivadas) for r in registros
            ),
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

    def _arquivadas_entre(self, ids: set[UUID]) -> frozenset[UUID]:
        """Quais destas agendas estao arquivadas — UMA consulta por pagina.

        O `delete` da API e SOFT: `arquivado_em` recebe data e o registro sai
        das consultas, mas a LINHA fica. Logo o `on delete cascade` da 0017
        nunca dispara pelo fluxo real, e o elo sobrevive a agenda.

        Sem este filtro, a descendente continua dizendo que decorre de uma
        agenda cujo `GET` responde 404, e a Base marca "levou a 1" para uma
        cadeia que ninguem consegue abrir.

        A filtragem mora AQUI, e nao no join da relacao, porque com `secondary`
        os dois lados sao `InteracaoRegistro` — relacao autorreferente, que
        `selectin` nao carrega em lote. Ver o comentario em
        `tabelas_interacoes.py`.
        """
        if not ids:
            return frozenset()
        return frozenset(
            self.sessao.scalars(
                select(InteracaoRegistro.id).where(
                    InteracaoRegistro.id.in_(ids),
                    InteracaoRegistro.arquivado_em.is_not(None),
                )
            )
        )

    def _arquivadas_do_registro(self, registro: InteracaoRegistro) -> frozenset[UUID]:
        """O mesmo, para UM registro. Usado por `obter` e pela escrita."""
        return self._arquivadas_entre(
            {v.origem_id for v in registro.origens}
            | {v.interacao_id for v in registro.derivadas}
        )

    def _para_dominio(
        self,
        registro: InteracaoRegistro,
        *,
        arquivadas: frozenset[UUID] | None = None,
    ) -> Interacao:
        fora = (
            arquivadas
            if arquivadas is not None
            else self._arquivadas_do_registro(registro)
        )
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
            modalidade=registro.modalidade,
            local=registro.local,
            extensao=self._extensao_do_registro(registro, frente),
            temas=tuple(sorted(vinculo.tema_id for vinculo in registro.temas)),
            areas=tuple(sorted(vinculo.area_id for vinculo in registro.areas)),
            participacoes=tuple(
                ParticipacaoAegea(
                    pessoa_aegea_id=vinculo.pessoa_aegea_id,
                    papel=vinculo.papel,
                    presenca=vinculo.presenca,
                )
                for vinculo in registro.participacoes
            ),
            expectativa=registro.expectativa,
            clima_esperado=self._codigo_de(
                Clima, registro.clima_esperado_id
            ),
            declinado_por=registro.declinado_por,
            motivo_declinio=registro.motivo_declinio,
            nota_situacao=registro.nota_situacao,
            # Ordenado para a ficha e o grafo nao reordenarem as setas a
            # cada leitura — quem olha duas vezes acharia que algo mudou.
            # SEM AS ARQUIVADAS. Uma agenda arquivada nao aparece em lugar
            # nenhum, e apontar para ela desenharia seta para um no que a tela
            # nao mostra. Quem monta `fora` e `_arquivadas_entre`, com UMA
            # consulta por pagina.
            origens=tuple(
                sorted(
                    (v.origem_id for v in registro.origens if v.origem_id not in fora),
                    key=str,
                )
            ),
            derivadas=sum(
                1 for v in registro.derivadas if v.interacao_id not in fora
            ),
            preve_desdobramento=registro.preve_desdobramento,
            outra_parte=_com_o_principal(registro),
            materiais=tuple(
                MaterialDaAgenda(
                    id=material.id,
                    momento=material.momento,
                    titulo=material.titulo,
                    url=material.url,
                    observacao=material.observacao,
                    arquivo_id=material.arquivo_id,
                    referencia_id=material.referencia_id,
                    temas=tuple(sorted(v.tema_id for v in material.temas)),
                    # O NOME, O TIPO E O TAMANHO VOLTAM JUNTO.
                    #
                    # Sem isto a ficha teria o id do arquivo e nada para
                    # escrever ao lado do icone — e a tela precisaria de uma
                    # ida ao servidor por material so para descobrir como o
                    # arquivo se chama.
                    #
                    # Foi assim que a presenca do porta-voz se perdeu por tres
                    # revisoes: o esquema de saida declarava o campo e ninguem
                    # o preenchia. Declarar nao e preencher.
                    arquivo=(
                        ArquivoDoMaterial(
                            id=material.arquivo.id,
                            nome=material.arquivo.nome,
                            tipo_conteudo=material.arquivo.tipo_conteudo,
                            tamanho=material.arquivo.tamanho,
                        )
                        if material.arquivo is not None
                        else None
                    ),
                )
                # Ordem estavel: sem ela a ficha reordena os materiais a cada
                # leitura, e a pessoa acha que algo mudou.
                for material in sorted(
                    registro.materiais, key=lambda m: (m.momento, m.titulo)
                )
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


def _com_o_principal(registro: InteracaoRegistro) -> tuple[ParticipanteDaOutraParte, ...]:
    """Os participantes da outra parte — e o principal, mesmo sem linha.

    O `backfill` da migration 0011 alcancou as interacoes que EXISTIAM naquele
    momento. Tudo que entrou depois por fora do repositorio — o semeador de
    desenvolvimento, a importacao de planilha, um `insert` de manutencao —
    grava `interlocutor_id` e nao cria a linha de participante.

    Sem esta sintese, a ficha dessas agendas diria "nenhum participante" para
    uma reuniao que tem interlocutor havia meses. E o mesmo defeito que o
    backfill existe para corrigir, so que renascendo a cada carga nova.

    A presenca fica NULA: ninguem perguntou a essa pessoa se compareceu.
    O primeiro salvamento pela tela materializa a linha, e a sintese para de
    ser necessaria para aquele registro.
    """
    participantes = tuple(
        ParticipanteDaOutraParte(
            interlocutor_id=vinculo.interlocutor_id,
            presenca=vinculo.presenca,
            principal=vinculo.principal,
        )
        # O principal primeiro: a ficha o mostra no topo, e ordenar na tela
        # seria repetir em TypeScript uma regra que e do dominio.
        for vinculo in sorted(registro.outra_parte, key=lambda v: (not v.principal,))
    )
    if participantes or registro.interlocutor_id is None:
        return participantes
    return (
        ParticipanteDaOutraParte(
            interlocutor_id=registro.interlocutor_id, principal=True
        ),
    )


def _casar_temas(registro: Material, desejados: tuple[int, ...]) -> None:
    """Deixa os assuntos do material iguais ao pedido, mexendo só no que mudou.

    Apagar todos e reinserir seria mais curto e trocaria a identidade de linhas
    que não mudaram — um `delete`/`insert` por salvamento mesmo quando ninguém
    tocou nos assuntos.
    """
    alvo = set(desejados)
    atuais = {vinculo.tema_id for vinculo in registro.temas}

    for vinculo in list(registro.temas):
        if vinculo.tema_id not in alvo:
            registro.temas.remove(vinculo)

    for tema_id in sorted(alvo - atuais):
        registro.temas.append(MaterialTema(tema_id=tema_id))


def _novo_material(material: MaterialDaAgenda, *, autor: UUID) -> Material:
    """Um material que ainda não existe no banco, já com os assuntos dele."""
    registro = Material(
        momento=material.momento,
        titulo=material.titulo.strip(),
        url=material.url,
        arquivo_id=material.arquivo_id,
        referencia_id=material.referencia_id,
        observacao=material.observacao,
        criado_por=autor,
    )
    _casar_temas(registro, material.temas)
    return registro
