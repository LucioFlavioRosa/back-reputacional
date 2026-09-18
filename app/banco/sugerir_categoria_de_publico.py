"""Sugestão de categoria de público para as instituições sem classificação.

    python -m app.banco.sugerir_categoria_de_publico [caminho-do-csv]
    python -m app.banco.sugerir_categoria_de_publico --aplicar [caminho-do-csv]

SEM `--aplicar`, SÓ LÊ O BANCO. Nenhum `insert`/`update`/`commit` — é seguro
rodar em qualquer ambiente, quantas vezes quiser. O caminho do CSV é
opcional; sem ele, grava `categoria_publico_sugerida.csv` no diretório atual.

COM `--aplicar`, além do CSV, GRAVA no banco as sugestões de CONFIANÇA ALTA
— ver `aplicar_sugestoes` mais abaixo. Confiança baixa nunca é gravada: fica
`null`, honesto sobre o que a heurística não sabe de verdade, e continua
aparecendo no CSV para revisão humana.

O QUE ESTE SCRIPT NÃO É
------------------------
Não é um classificador em quem confiar. É um PRIMEIRO PALPITE, para poupar
trabalho de digitação em quem vai revisar — não trabalho de decisão. As
colunas que ele preenche:

  instituicao_id, nome, tipo_atual, natureza_orgao_mais_recente,
  categoria_sugerida, confianca_categoria,
  subcategoria_sugerida, confianca_subcategoria

`categoria_sugerida`/`subcategoria_sugerida` saem pelo NOME (não pelo
`codigo`), porque quem revisa isto abre a planilha, não o banco.

DUAS CONFIANÇAS, NÃO UMA — de propósito: `tipo='veiculo'` diz, sem
ambiguidade nenhuma, que a categoria é "Imprensa e Formadores de Opinião"
(confiança alta), mas não diz NADA sobre qual das 4 linhas editoriais é essa
— aí a confiança da subcategoria é baixa. Se as duas saíssem numa coluna só,
quem revisasse desconfiaria à toa da categoria (que já está certa) por causa
da subcategoria (que é, de fato, um chute).

A HEURÍSTICA, EM DUAS CAMADAS
------------------------------
1. PALAVRA-CHAVE NO NOME, primeiro — pega os casos que `tipo`/`natureza_orgao`
   sozinhos não distinguem: `natureza_orgao='executivo'` cobre tanto uma
   prefeitura quanto a ANA quanto o TCU, e só o nome desempata. Confiança
   ALTA no que a palavra-chave resolveu.
2. `tipo` + `natureza_orgao` MAIS RECENTE da instituição, como resguardo —
   cobre o resto. Confiança ALTA só onde o mapeamento é seguro por definição
   (`veiculo`→Imprensa, `credor`→Mercado Financeiro, `investidor`→Mercado
   Financeiro, `judiciario`→Poder Judiciário); BAIXA no resto (é o "melhor
   palpite sem pista melhor", não uma classificação).

Áreas internas (`tipo='area_interna'`) saem na planilha com as colunas de
sugestão vazias e confiança baixa: não são público externo, então não há o
que sugerir — ficam ali só para o total bater com o inventário real.

Instituição que JÁ TEM categoria (reclassificada por outro motivo, ou criada
depois que o campo passou a ser obrigatório) não entra na planilha — não há
nada a sugerir para quem já foi classificado.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.sessao import obter_fabrica_de_sessao
from app.banco.tabelas_catalogo import CategoriaPublico, NaturezaOrgao, SubcategoriaPublico
from app.banco.tabelas_interacoes import InstitucionalRegistro, InteracaoRegistro
from app.banco.tabelas_stakeholders import Instituicao

CSV_PADRAO = "categoria_publico_sugerida.csv"

CABECALHO = [
    "instituicao_id",
    "nome",
    "tipo_atual",
    "natureza_orgao_mais_recente",
    "categoria_sugerida",
    "confianca_categoria",
    "subcategoria_sugerida",
    "confianca_subcategoria",
]


# -- camada 1: palavra-chave no nome ------------------------------------------
#
# ORDEM IMPORTA: percorrida de cima para baixo, primeira que bater vence.
# Reguladores/Controle antes de Executivo/Legislativo genéricos, porque um
# órgão regulador ou um tribunal de contas também tem natureza_orgao=
# 'executivo' na base de hoje — o nome é o único jeito de diferenciar.
REGRAS_POR_PALAVRA_CHAVE: list[tuple[re.Pattern[str], str, str | None]] = [
    # (padrão no nome, categoria, subcategoria — None = sem_quebra)
    (re.compile(r"tribunal de contas|\btce\b|\btcm\b|\btcu\b", re.I),
        "Controle e Fiscalização", "Controle e auditoria"),
    (re.compile(r"minist[ée]rio p[úu]blico|\bmpf\b|\bmpe\b|promotoria", re.I),
        "Controle e Fiscalização", "Ministério Público"),
    (re.compile(r"procon|defesa do consumidor", re.I),
        "Controle e Fiscalização", "Defesa do consumidor"),
    (re.compile(r"\bagência nacional de águas|\bana\b", re.I),
        "Reguladores", "Federal"),
    (re.compile(r"arsesp|arsae|agergs|agir\b|ares-?pcj|agência reguladora", re.I),
        "Reguladores", "Estadual"),
    (re.compile(r"\b(s&p|standard\s*&\s*poor|moody'?s|fitch)\b", re.I),
        "Mercado Financeiro e de Capitais", "Rating"),
    (re.compile(r"prefeitura|c[âa]mara municipal|secretaria municipal", re.I),
        None, "Municipal"),  # categoria decidida pela camada 2 (executivo/legislativo)
    (re.compile(r"assembleia legislativa|secretaria de estado|governo do estado", re.I),
        None, "Estadual"),
    (re.compile(r"c[âa]mara dos deputados|senado federal|congresso nacional|"
                r"minist[ée]rio (?!p[úu]blico)|presid[êe]ncia da rep[úu]blica|casa civil", re.I),
        None, "Federal"),
    (re.compile(r"\b(abcon|aesbe|abdib|\bcni\b|fiesp|sindicato|federação|confederação|"
                r"instituto\b|associação brasileira)", re.I),
        "Entidades Setoriais e Representativas", "Institutos e Associações"),
    (re.compile(r"\bong\b|organização não governamental|associação de moradores|"
                r"conselho comunitário|comitê de bacia", re.I),
        "Sociedade Civil e Comunidade", "Comunidade e lideranças locais"),
]


def _por_palavra_chave(nome: str) -> tuple[str | None, str | None]:
    """`(categoria, subcategoria)` — os dois `None` quando nada bateu, ou
    `subcategoria` sozinha quando só a esfera foi reconhecida (o chamador
    completa a categoria com a camada 2, que sabe se é Executivo ou
    Legislativo)."""
    for padrao, categoria, subcategoria in REGRAS_POR_PALAVRA_CHAVE:
        if padrao.search(nome):
            return categoria, subcategoria
    return None, None


# -- camada 2: tipo + natureza_orgao mais recente, como resguardo ------------

_CATEGORIA_POR_NATUREZA = {
    "executivo": "Poder Executivo",
    "legislativo": "Poder Legislativo",
    "judiciario": "Poder Judiciário",
}


def sugerir(
    tipo: str, natureza_orgao: str | None, nome: str
) -> tuple[str | None, str, str | None, str]:
    """A sugestão para uma instituição — ver o docstring do módulo.

    Devolve `(categoria_sugerida, confianca_categoria, subcategoria_sugerida,
    confianca_subcategoria)` — DUAS CONFIANÇAS, NÃO UMA: `tipo='veiculo'` diz
    a categoria sem ambiguidade nenhuma, mas nada diz qual das 4 linhas
    editoriais é a subcategoria — misturar as duas confianças numa só faria a
    categoria (já certa) parecer tão duvidosa quanto a subcategoria (um
    chute). `categoria_sugerida`/`subcategoria_sugerida` já saem como NOME
    (não `codigo`), prontos para a planilha.
    """
    if tipo == "area_interna":
        return None, "baixa", None, "baixa"

    categoria_chave, subcategoria_chave = _por_palavra_chave(nome)
    if categoria_chave is not None:
        # PALAVRA-CHAVE ESPECÍFICA bateu (regulador, MP, TCU, rating...) —
        # a categoria já veio pronta, com ou sem subcategoria; as duas vieram
        # da MESMA palavra-chave, então as duas confianças são altas.
        return categoria_chave, "alta", subcategoria_chave, "alta"

    if subcategoria_chave is not None:
        # SÓ A ESFERA bateu (prefeitura, assembleia...) — falta decidir entre
        # Executivo e Legislativo, e só `natureza_orgao` sabe isso.
        categoria = _CATEGORIA_POR_NATUREZA.get(natureza_orgao or "")
        if categoria in ("Poder Executivo", "Poder Legislativo"):
            return categoria, "alta", subcategoria_chave, "alta"
        # Esfera reconhecida (subcategoria confiável) mas sem natureza_orgao
        # para desempatar Executivo x Legislativo — melhor não adivinhar SÓ a
        # categoria; a subcategoria continua valendo.
        return None, "baixa", subcategoria_chave, "alta"

    if tipo == "veiculo":
        # A CATEGORIA é certa pelo tipo; a linha editorial, ninguém disse.
        return "Imprensa e Formadores de Opinião", "alta", None, "baixa"
    if tipo == "investidor":
        return (
            "Mercado Financeiro e de Capitais", "alta",
            "Dívida, crédito, equity e acionistas", "baixa",
        )
    if tipo == "credor":
        # Um credor/banco É, por definição, do lado da dívida — as duas
        # confianças são altas aqui.
        return (
            "Mercado Financeiro e de Capitais", "alta",
            "Dívida, crédito, equity e acionistas", "alta",
        )
    if tipo == "proposicao":
        return None, "baixa", None, "baixa"

    if natureza_orgao == "judiciario":
        # SEM AMBIGUIDADE: Poder Judiciário é "sem_quebra" — a subcategoria
        # vazia é a resposta certa, não um "não sei".
        return "Poder Judiciário", "alta", None, "alta"
    if natureza_orgao in _CATEGORIA_POR_NATUREZA:
        # Executivo/Legislativo sem palavra-chave de esfera: a categoria é só
        # um palpite (`natureza_orgao` sozinho não distingue de regulador,
        # controle...), então a subcategoria — que dependeria dela — também.
        return _CATEGORIA_POR_NATUREZA[natureza_orgao], "baixa", None, "baixa"
    if natureza_orgao == "empresa":
        return "Parceiros e Cadeia de Valor", "baixa", None, "baixa"
    if natureza_orgao in ("entidade", "associacao", "escritorio"):
        return "Entidades Setoriais e Representativas", "baixa", None, "baixa"

    # Nem palavra-chave, nem natureza_orgao registrada em nenhuma interação —
    # não há pista nenhuma para arriscar um palpite.
    return None, "baixa", None, "baixa"


def _natureza_orgao_mais_recente_por_instituicao(sessao: Session) -> dict[str, str]:
    """`instituicao_id` (como string) -> `codigo` do `natureza_orgao` da
    interação institucional MAIS RECENTE dela, entre as que registraram o
    campo.

    Uma query só, sem `group by`/janela: o volume (poucas centenas de
    instituições, dezenas de milhares de interações no pior caso de produção)
    não paga a complexidade de fazer o banco escolher "a mais recente" —
    é mais simples, e mais fácil de auditar, escolher em Python. """
    linhas = sessao.execute(
        select(
            InteracaoRegistro.instituicao_id,
            InteracaoRegistro.data_interacao,
            NaturezaOrgao.codigo,
        )
        .join(
            InstitucionalRegistro,
            InstitucionalRegistro.interacao_id == InteracaoRegistro.id,
        )
        .join(NaturezaOrgao, NaturezaOrgao.id == InstitucionalRegistro.natureza_orgao_id)
        .order_by(InteracaoRegistro.instituicao_id, InteracaoRegistro.data_interacao.desc())
    ).all()

    mais_recente: dict[str, str] = {}
    for instituicao_id, _data, codigo in linhas:
        # A PRIMEIRA linha de cada instituição já é a mais recente, por causa
        # do `order_by` acima — as seguintes (mesma instituição, data menor)
        # são ignoradas.
        chave = str(instituicao_id)
        if chave not in mais_recente:
            mais_recente[chave] = codigo
    return mais_recente


def gerar_sugestoes(sessao: Session) -> list[dict[str, str]]:
    natureza_por_instituicao = _natureza_orgao_mais_recente_por_instituicao(sessao)

    instituicoes = sessao.scalars(
        select(Instituicao)
        .where(Instituicao.categoria_publico_id.is_(None))
        .order_by(Instituicao.nome)
    ).all()

    linhas: list[dict[str, str]] = []
    for instituicao in instituicoes:
        natureza = natureza_por_instituicao.get(str(instituicao.id))
        categoria, confianca_categoria, subcategoria, confianca_subcategoria = sugerir(
            instituicao.tipo, natureza, instituicao.nome
        )
        linhas.append(
            {
                "instituicao_id": str(instituicao.id),
                "nome": instituicao.nome,
                "tipo_atual": instituicao.tipo,
                "natureza_orgao_mais_recente": natureza or "",
                "categoria_sugerida": categoria or "",
                "confianca_categoria": confianca_categoria,
                "subcategoria_sugerida": subcategoria or "",
                "confianca_subcategoria": confianca_subcategoria,
            }
        )
    return linhas


def aplicar_sugestoes(sessao: Session, linhas: list[dict[str, str]]) -> dict[str, int]:
    """Grava no banco só as linhas de `confianca_categoria == "alta"` — e,
    dentro dessas, só marca `subcategoria_publico_id` onde
    `confianca_subcategoria` também é alta. O restante (baixa confiança nos
    dois, ou só na subcategoria) fica como já estava: `null`.

    RECEBE `linhas` já prontas (as mesmas que viram CSV), em vez de chamar
    `gerar_sugestoes` de novo — assim o que se grava no banco é EXATAMENTE o
    que a planilha desta mesma execução mostrou, nunca uma segunda leitura
    que poderia (em tese) enxergar o banco de outro jeito.

    Devolve quantas instituições ganharam categoria, e quantas dessas também
    ganharam subcategoria — os mesmos dois números que o CSV já resume."""
    categoria_id_por_nome = {
        categoria.nome: categoria.id
        for categoria in sessao.scalars(select(CategoriaPublico)).all()
    }
    subcategoria_id_por_categoria_e_nome = {
        (subcategoria.categoria_publico_id, subcategoria.nome): subcategoria.id
        for subcategoria in sessao.scalars(select(SubcategoriaPublico)).all()
    }

    ids_da_planilha = [linha["instituicao_id"] for linha in linhas]
    instituicao_por_id = {
        str(instituicao.id): instituicao
        for instituicao in sessao.scalars(
            select(Instituicao).where(Instituicao.id.in_(ids_da_planilha))
        ).all()
    }

    aplicadas_categoria = 0
    aplicadas_subcategoria = 0
    for linha in linhas:
        if linha["confianca_categoria"] != "alta":
            continue
        categoria_id = categoria_id_por_nome.get(linha["categoria_sugerida"])
        if categoria_id is None:
            # Não deveria acontecer (o nome vem do mesmo dicionário que
            # `sugerir` conhece) — mas gravar um id incerto é pior do que
            # deixar de fora, então pula em vez de arriscar.
            continue

        instituicao_por_id[linha["instituicao_id"]].categoria_publico_id = categoria_id
        aplicadas_categoria += 1

        if linha["confianca_subcategoria"] == "alta" and linha["subcategoria_sugerida"]:
            subcategoria_id = subcategoria_id_por_categoria_e_nome.get(
                (categoria_id, linha["subcategoria_sugerida"])
            )
            if subcategoria_id is not None:
                instituicao = instituicao_por_id[linha["instituicao_id"]]
                instituicao.subcategoria_publico_id = subcategoria_id
                aplicadas_subcategoria += 1

    sessao.commit()
    return {"categoria": aplicadas_categoria, "subcategoria": aplicadas_subcategoria}


def main() -> int:
    aplicar = "--aplicar" in sys.argv
    argumentos_posicionais = [a for a in sys.argv[1:] if not a.startswith("--")]
    destino = Path(argumentos_posicionais[0]) if argumentos_posicionais else Path(CSV_PADRAO)

    with obter_fabrica_de_sessao()() as sessao:
        linhas = gerar_sugestoes(sessao)
        resultado = aplicar_sugestoes(sessao, linhas) if aplicar else None

    with destino.open("w", newline="", encoding="utf-8-sig") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=CABECALHO)
        escritor.writeheader()
        escritor.writerows(linhas)

    altas_categoria = sum(1 for linha in linhas if linha["confianca_categoria"] == "alta")
    altas_ambas = sum(
        1
        for linha in linhas
        if linha["confianca_categoria"] == "alta" and linha["confianca_subcategoria"] == "alta"
    )
    print(f"{len(linhas)} instituições sem categoria.")
    print(f"  {altas_categoria} com categoria de confiança alta")
    print(f"  {altas_ambas} dessas também com subcategoria de confiança alta")
    print(f"Planilha gravada em {destino.resolve()}")
    if resultado is not None:
        print(
            f"\nGravado no banco: {resultado['categoria']} instituições com categoria, "
            f"{resultado['subcategoria']} dessas também com subcategoria."
        )
    else:
        print("\nÉ um primeiro palpite para revisão, não uma classificação — confira cada linha.")
        print("Rode de novo com --aplicar para gravar no banco as sugestões de confiança alta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
