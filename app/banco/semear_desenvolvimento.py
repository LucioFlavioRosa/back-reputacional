"""Semeia o banco local com a amostra sintética do handoff.

    python -m app.banco.semear_desenvolvimento

Cria também o usuário de desenvolvimento e a senha dele, para a pilha local
não subir trancada — ver `SENHA_DE_DESENVOLVIMENTO`.

    python -m app.banco.semear_desenvolvimento

São 60 registros **sintéticos**, derivados da planilha real mas sem ser dado de
produção — servem para ver as telas funcionando antes da importação de verdade.
O script é idempotente: rodar duas vezes não duplica nada.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.banco.sessao import obter_fabrica_de_sessao
from app.banco.tabelas_acesso import Usuario
from app.banco.tabelas_catalogo import (
    Clima,
    Esfera,
    Frente,
    Status,
    Tema,
    UnidadeNegocio,
)
from app.banco.tabelas_interacoes import (
    ImprensaRegistro,
    InstitucionalRegistro,
    InteracaoPessoaAegea,
    InteracaoRegistro,
    InteracaoTema,
    InvestidoresRegistro,
    LegislativoRegistro,
)
from app.banco.tabelas_stakeholders import (
    Instituicao,
    Interlocutor,
    PessoaAegea,
)
from app.casos_de_uso.autenticar_por_senha import definir_senha
from app.dominio.texto import normalizar

AMOSTRA = Path(__file__).with_name("amostra_de_desenvolvimento.json")

FRENTE_POR_ROTULO = {
    "Imprensa": "imprensa",
    "Governo": "governo",
    "Parceiros": "parceiros",
    "Eventos": "eventos",
    "Investidores": "investidores",
    "Legislativo": "legislativo",
    "Interna": "interna",
}

STATUS_POR_ROTULO = {
    "Atendido": "atendido",
    "Declinado": "declinado",
    "Agendado": "agendado",
    "Em análise": "em_analise",
    "Realizado": "realizado",
    "Elaborado": "elaborado",
    "Cancelado": "cancelado",
}

CLIMA_POR_ROTULO = {"Propositivo": "propositivo", "Neutro": "neutro", "Tenso": "tenso"}

TIPO_DE_INSTITUICAO = {
    "imprensa": "veiculo",
    "governo": "orgao",
    "parceiros": "entidade",
    "eventos": "entidade",
    "investidores": "investidor",
    "legislativo": "proposicao",
    "interna": "area_interna",
}

#: Porta-vozes da amostra, distribuídos por frente como no protótipo.
PORTA_VOZES = [
    "Radamés Casseb",
    "André Pires",
    "Édison Carlos",
    "Márcia Costa",
    "Andréa Melo",
    "Letícia Novaes",
]


#: Um usuário por papel, para comparar o que cada perfil enxerga.
#:
#: São os oito papéis de partida da migration 0003 — um leitor e um editor
#: para cada portal.
#: Acrescentar um papel ao banco e uma linha aqui basta para ele ganhar conta de
#: desenvolvimento.
USUARIOS_DE_DESENVOLVIMENTO = [
    ("plataforma_leitura", "plataforma.leitura@aegea.com.br", "Plataforma · leitura"),
    ("plataforma_edicao", "plataforma.edicao@aegea.com.br", "Plataforma · edição"),
    ("crm_leitura", "crm.leitura@aegea.com.br", "CRM · leitura"),
    ("crm_edicao", "crm.edicao@aegea.com.br", "CRM · edição"),
    ("sintese_leitura", "sintese.leitura@aegea.com.br", "Síntese · leitura"),
    ("sintese_edicao", "sintese.edicao@aegea.com.br", "Síntese · edição"),
    ("score_leitura", "score.leitura@aegea.com.br", "Score · leitura"),
    ("score_edicao", "score.edicao@aegea.com.br", "Score · edição"),
]

#: A senha do usuário local. NÃO é segredo, e não pretende ser.
#:
#: Longa porque `definir_senha` exige 12 caracteres — a mesma regra que vale
#: para qualquer senha da plataforma, e um mínimo aplicado só em produção é um
#: mínimo que ninguém testa.
SENHA_DE_DESENVOLVIMENTO = "painel-reputacional-2026"


def _semear_usuarios(sessao: Session) -> None:
    """Um usuário POR PAPEL, e não um só.

    Ver o modelo de permissão exige alternar entre perfis, e com um usuário só
    isso é `update` no banco seguido de reinício da API — porque a autorização
    fica em cache por cinco minutos. Quatro contas transformam a comparação em
    oito logins.

    Cada uma recebe a MESMA senha, e isso é conveniência de desenvolvimento
    consciente: quem testa não deveria ter de consultar oito credenciais para
    comparar oito perfis.

    Idempotente por e-mail: rodar duas vezes não duplica, e um papel novo
    acrescentado a esta lista aparece na execução seguinte sem apagar nada.
    """
    for codigo, email, nome in USUARIOS_DE_DESENVOLVIMENTO:
        if sessao.scalar(select(Usuario).where(Usuario.email == email)):
            continue

        sessao.add(
            Usuario(
                # Prefixo `mock-` para nunca colidir com um `oid` de verdade do
                # Entra ID, que é um UUID.
                entra_object_id=f"mock-{codigo}",
                email=email,
                nome=nome,
                # Sem escopo de frente ou unidade: o que se quer comparar aqui é
                # o PAPEL. Escopo é a outra dimensão, e misturá-los faria a
                # diferença entre duas telas ter duas causas possíveis.
                acesso_irrestrito=True,
            )
        )
        sessao.flush()

        sessao.execute(
            text(
                "update usuario set papel_id = (select id from papel "
                "where codigo = :papel) where email = :email"
            ),
            {"papel": codigo, "email": email},
        )
        definir_senha(sessao, email=email, senha=SENHA_DE_DESENVOLVIMENTO)


def semear(sessao: Session) -> dict[str, int]:
    registros = json.loads(AMOSTRA.read_text(encoding="utf-8"))

    _semear_usuarios(sessao)
    autor = sessao.scalar(
        select(Usuario).where(Usuario.email == "plataforma.edicao@aegea.com.br")
    )
    # O bloco acima garante que existe pelo menos um usuário. Tornar a garantia
    # explícita evita que uma edição naquele `if` transforme isto num
    # `AttributeError` no meio da carga, com metade dos registros já dentro.
    #
    # `raise`, e não `assert`: `python -O` remove asserções, e uma invariante
    # que some conforme a flag de execução não é invariante.
    if autor is None:
        raise RuntimeError(
            "Usuário `plataforma.edicao@aegea.com.br` não encontrado. Ele é o autor "
            "dos registros da amostra, e `_semear_usuarios` deveria tê-lo "
            "criado logo acima — se chegou aqui, a criação falhou em silêncio."
        )

    ja_semeado = sessao.scalar(
        select(InteracaoRegistro).where(InteracaoRegistro.origem_aba == "amostra-handoff")
    )
    if ja_semeado is not None:
        return {"ja_semeado": 1}

    # -- dicionários -> id ---------------------------------------------------
    id_de_frente = {f.codigo: f.id for f in sessao.scalars(select(Frente))}
    id_de_status = {s.codigo: s.id for s in sessao.scalars(select(Status))}
    id_de_clima = {c.codigo: c.id for c in sessao.scalars(select(Clima))}
    id_de_esfera = {e.codigo: e.id for e in sessao.scalars(select(Esfera))}
    id_de_tema = {t.nome: t.id for t in sessao.scalars(select(Tema))}
    unidades = list(sessao.scalars(select(UnidadeNegocio)))

    # -- pessoas da Aegea ----------------------------------------------------
    pessoas: dict[str, PessoaAegea] = {}
    for nome in PORTA_VOZES:
        pessoa = PessoaAegea(nome=nome, nome_normalizado=normalizar(nome), eh_porta_voz=True)
        sessao.add(pessoa)
        pessoas[nome] = pessoa
    sessao.flush()

    instituicoes: dict[tuple[str, str], Instituicao] = {}
    interlocutores: dict[str, Interlocutor] = {}
    criadas = 0

    for indice, linha in enumerate(registros):
        rotulo_frente, data_iso, entidade, pessoa, uf, pauta, status, tier, clima, tags = linha[:10]
        extra = linha[10] if len(linha) > 10 else ""

        frente = FRENTE_POR_ROTULO[rotulo_frente]
        tipo = TIPO_DE_INSTITUICAO[frente]

        chave = (normalizar(entidade), tipo)
        if chave not in instituicoes:
            instituicao = Instituicao(
                nome=entidade,
                nome_normalizado=normalizar(entidade),
                tipo=tipo,
                uf=uf if len(uf) == 2 else None,
            )
            sessao.add(instituicao)
            sessao.flush()
            instituicoes[chave] = instituicao
        instituicao = instituicoes[chave]

        interlocutor = None
        if pessoa:
            if pessoa not in interlocutores:
                novo = Interlocutor(
                    nome=pessoa,
                    nome_normalizado=normalizar(pessoa),
                    instituicao_id=instituicao.id,
                    tipo="jornalista" if frente == "imprensa" else None,
                )
                sessao.add(novo)
                sessao.flush()
                interlocutores[pessoa] = novo
            interlocutor = interlocutores[pessoa]

        esfera = (
            "federal"
            if uf == "DF"
            else "internacional"
            if uf == "IN"
            else "nacional"
            if uf == "NA"
            else "estadual"
        )

        interacao = InteracaoRegistro(
            frente_id=id_de_frente[frente],
            data_interacao=date.fromisoformat(data_iso),
            instituicao_id=instituicao.id,
            interlocutor_id=interlocutor.id if interlocutor else None,
            unidade_negocio_id=unidades[indice % len(unidades)].id,
            esfera_id=id_de_esfera.get(esfera),
            uf=uf if len(uf) == 2 else "NA",
            tier=int(tier.split()[-1]),
            status_id=id_de_status[STATUS_POR_ROTULO[status]],
            clima_id=id_de_clima.get(CLIMA_POR_ROTULO.get(clima, "")),
            pauta=pauta,
            relato=f"Registro de amostra para {rotulo_frente.lower()}.",
            pendencias="Acompanhar retorno." if status in ("Agendado", "Em análise") else None,
            fonte="cadastro_manual",
            origem_aba="amostra-handoff",
            origem_linha=indice,
            criado_por=autor.id,
        )
        sessao.add(interacao)
        sessao.flush()

        for nome_do_tema in filter(None, tags.split(";")):
            tema_id = id_de_tema.get(nome_do_tema.strip())
            if tema_id:
                sessao.add(InteracaoTema(interacao_id=interacao.id, tema_id=tema_id))

        # Um porta-voz por registro, e a cada cinco registros dois — para que o
        # painel de exposição mostre o caso de aparição múltipla.
        escolhidos = [PORTA_VOZES[indice % len(PORTA_VOZES)]]
        if indice % 5 == 0:
            escolhidos.append(PORTA_VOZES[(indice + 1) % len(PORTA_VOZES)])
        for nome in escolhidos:
            sessao.add(
                InteracaoPessoaAegea(
                    interacao_id=interacao.id,
                    pessoa_aegea_id=pessoas[nome].id,
                    papel="porta_voz",
                )
            )

        _extensao(sessao, interacao.id, frente, extra)
        criadas += 1

    sessao.commit()
    return {
        "interacoes": criadas,
        "instituicoes": len(instituicoes),
        "interlocutores": len(interlocutores),
        "porta_vozes": len(pessoas),
    }


def _extensao(sessao: Session, interacao_id, frente: str, extra: str) -> None:
    if frente == "imprensa":
        sessao.add(
            ImprensaRegistro(
                interacao_id=interacao_id,
                mensagens_chave=["Universalização", "Disciplina financeira"],
            )
        )
    elif frente in ("governo", "parceiros", "eventos"):
        sessao.add(
            InstitucionalRegistro(
                interacao_id=interacao_id,
                nome_evento=extra if frente == "eventos" else None,
            )
        )
    elif frente == "legislativo":
        sessao.add(LegislativoRegistro(interacao_id=interacao_id, prioridade="media"))
    elif frente == "investidores":
        sessao.add(InvestidoresRegistro(interacao_id=interacao_id))


def main() -> int:
    with obter_fabrica_de_sessao()() as sessao:
        resultado = semear(sessao)

    if resultado.get("ja_semeado"):
        print("A amostra já está no banco. Nada a fazer.")
        return 0

    for chave, valor in resultado.items():
        print(f"  {chave:<16} {valor}")
    print("\nAmostra sintética carregada. Não é dado de produção.")
    print(f"\nOito contas, todas com a senha  {SENHA_DE_DESENVOLVIMENTO}")
    for _codigo, email, nome in USUARIOS_DE_DESENVOLVIMENTO:
        print(f"  {email:34} {nome}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
