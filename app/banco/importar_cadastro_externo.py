"""Importa o cadastro externo de Instituições, Contatos e Representantes Aegea.

    python -m app.banco.importar_cadastro_externo <pasta_com_os_csvs> [--confirmar]

A pasta precisa ter `instituicoes.csv`, `contatos.csv` e
`representantes_aegea.csv`, no formato descrito no README do dataset
consolidado (`20261009_Aegea_Instituições_Contatos_Representantes_consolidado`).
Lê com a biblioteca padrão (`csv`), e não com pandas — é um script de uso
único, e pandas não é dependência do projeto; trazê-la só para isto obrigaria
a mexer no lockfile com hash pinado por nada.

Grava pelas MESMAS validações de domínio que a API usa — `derivar_tipo`,
`_conferir_tier`, `_conferir_categoria_publico`, `_conferir_area`, `gravar` —
e não por `insert` cru: um script que escrevesse direto via ORM, sem essas
checagens, poderia gravar `tier`/`categoria_publico_id`/`subcategoria_publico_id`
incoerentes sem erro algum, porque a chave estrangeira sozinha não barra valor
desativado nem cruzamento categoria×subcategoria inválido.

SEM `--confirmar`, roda A SECO: o `commit` vira `rollback` no final, então os
números impressos (criados/já existia/erro) são reais — passaram pela mesma
inserção e pelo mesmo índice único do Postgres — mas nada fica gravado. Rode
assim primeiro, revise a contagem, só depois rode com `--confirmar`.

É DADO REAL (nome, cargo, e-mail de pessoas) — nunca commitar os CSVs de
origem no repositório. Aponte `pasta` para um caminho fora do versionado.

Mapeamento acertado com Jones em 2026-10-09:
  - Categoria de público: nome bate direto com `categoria_publico.nome`.
  - Esfera -> subcategoria_publico, só para categorias com
    `padrao_de_quebra != sem_quebra`. Em "Mercado Financeiro e de Capitais",
    os rótulos finos da planilha (Dívida e crédito, Equity e acionistas,
    Bancos e intermediação, Dados e informação de mercado, Consultoria)
    agrupam na subcategoria combinada "Dívida, crédito, equity e acionistas"
    — decisão de negócio, não é um de-para 1:1.
  - "Academia e estudantes" (1 instituição, categoria Sociedade Civil e
    Comunidade) mapeia para a subcategoria "Comunidade e lideranças locais".
  - Abrangência -> uf: Nacional->NA, Internacional->IN, sigla de UF direto.
  - Tier: "Tier N" -> inteiro N.
  - Rastreio (contatos): descartado — não existe campo correspondente em
    `interlocutor`.
  - Representantes sem "Tipo" preenchido: Equipe (`eh_porta_voz=False`).
  - Área "Sustentabilidade" (1 representante): sem área — não existe no
    dicionário `area_pessoa` hoje.
  - "Sub-Temas habilitados": vazio nas 55 linhas desta carga, nada a mapear.

Idempotente: rodar de novo sobre o mesmo banco não duplica — cada linha que já
existe (mesma chave única) aparece em "já existia", não em "criado".
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.stakeholders import (
    _conferir_area,
    _conferir_categoria_publico,
    _conferir_tier,
)
from app.banco.gravar import gravar
from app.banco.sessao import obter_fabrica_de_sessao
from app.banco.tabelas_catalogo import AreaPessoa, CategoriaPublico, SubcategoriaPublico
from app.banco.tabelas_stakeholders import Instituicao, Interlocutor, PessoaAegea
from app.casos_de_uso.derivar_tipo import derivar_tipo
from app.dominio.erros import RegraViolada
from app.dominio.texto import normalizar

Linha = dict[str, str]

#: Esfera (CSV) -> nome da subcategoria (banco), só quando não é igual.
ESFERA_PARA_SUBCATEGORIA = {
    "Dívida e crédito": "Dívida, crédito, equity e acionistas",
    "Equity e acionistas": "Dívida, crédito, equity e acionistas",
    "Bancos e intermediação": "Dívida, crédito, equity e acionistas",
    "Dados e informação de mercado": "Dívida, crédito, equity e acionistas",
    "Consultoria": "Dívida, crédito, equity e acionistas",
    "Academia e estudantes": "Comunidade e lideranças locais",
}

ABRANGENCIA_PARA_UF = {"Nacional": "NA", "Internacional": "IN"}

#: Área (CSV de representantes) -> nome em `area_pessoa`, só quando não é igual.
AREA_REPRESENTANTE_PARA_DICIONARIO = {
    "RI": "Relações com Investidores",
    "Op Fin": "Operações Financeiras",
    "Op Fin (DCM)": "Operações Financeiras",
    "Op Fin (ECM)": "Operações Financeiras",
    "Op Fin (DCM e ECM)": "Operações Financeiras",
    "Op Fin (Internacionais)": "Operações Financeiras",
}

#: Nome de coluna (como a planilha trouxe) -> nome seguro de atributo. A ordem
#: é a mesma do README do dataset — conferida contra o cabeçalho real antes de
#: renomear, para nunca aplicar o mapa errado num CSV com colunas fora de
#: ordem.
COLUNAS_INSTITUICOES = [
    "nome_curto",
    "nome_completo",
    "abrangencia",
    "tier",
    "categoria_publico",
    "esfera",
    "origem",
]
COLUNAS_CONTATOS = ["instituicao", "nome", "cargo", "area", "email", "rede_social", "rastreio"]
COLUNAS_REPRESENTANTES = ["nome", "email", "cargo", "tipo", "area", "sub_temas"]


def _vazio(valor: str | None) -> bool:
    return valor is None or valor.strip() == ""


class Resultado:
    def __init__(self) -> None:
        self.criados: dict[str, int] = {"instituicoes": 0, "contatos": 0, "representantes": 0}
        self.existentes: dict[str, int] = {"instituicoes": 0, "contatos": 0, "representantes": 0}
        self.erros: list[str] = []
        self.avisos: list[str] = []

    def imprimir(self) -> None:
        print("\n--- resultado ---")
        for chave in self.criados:
            print(
                f"  {chave:<14} criados={self.criados[chave]:<4} "
                f"ja_existia={self.existentes[chave]:<4}"
            )
        if self.avisos:
            print(f"\n  {len(self.avisos)} aviso(s) (não bloqueiam, mas confira):")
            for aviso in self.avisos:
                print(f"    - {aviso}")
        if self.erros:
            print(f"\n  {len(self.erros)} erro(s):")
            for erro in self.erros:
                print(f"    - {erro}")


def _ler_csv(pasta: Path, nome: str, colunas: list[str]) -> list[Linha]:
    caminho = pasta / nome
    if not caminho.exists():
        raise SystemExit(f"Não encontrei {caminho}.")
    with caminho.open(encoding="utf-8-sig", newline="") as arquivo:
        leitor = csv.reader(arquivo)
        cabecalho = next(leitor)
        if len(cabecalho) != len(colunas):
            raise SystemExit(
                f"{caminho}: esperava {len(colunas)} colunas, achei {len(cabecalho)} "
                f"({cabecalho!r}). Formato mudou — confira antes de rodar."
            )
        return [dict(zip(colunas, linha, strict=True)) for linha in leitor]


def _mapear_categoria_e_subcategoria(
    categorias: dict[str, CategoriaPublico],
    subcategorias_por_categoria: dict[int, dict[str, int]],
    nome_categoria: str,
    esfera: str,
) -> tuple[int | None, int | None]:
    categoria = categorias.get(nome_categoria)
    if categoria is None:
        raise RegraViolada(f"Categoria de público desconhecida: {nome_categoria!r}.")
    if _vazio(esfera) or categoria.padrao_de_quebra == "sem_quebra":
        return categoria.id, None
    esfera = esfera.strip()
    nome_subcategoria = ESFERA_PARA_SUBCATEGORIA.get(esfera, esfera)
    subcategoria_id = subcategorias_por_categoria.get(categoria.id, {}).get(nome_subcategoria)
    if subcategoria_id is None:
        raise RegraViolada(
            f"Esfera {esfera!r} (categoria {nome_categoria!r}) não bate com nenhuma "
            "subcategoria do banco — mapeamento incompleto, não vou chutar."
        )
    return categoria.id, subcategoria_id


def _importar_instituicoes(
    sessao: Session, linhas: list[Linha], resultado: Resultado
) -> dict[str, str]:
    """Cria as instituições; devolve {nome_normalizado: id} para os contatos."""
    categorias = {c.nome: c for c in sessao.scalars(select(CategoriaPublico))}
    subcategorias_por_categoria: dict[int, dict[str, int]] = {}
    for sub in sessao.scalars(select(SubcategoriaPublico)):
        subcategorias_por_categoria.setdefault(sub.categoria_publico_id, {})[sub.nome] = sub.id

    ids_por_nome: dict[str, str] = {}
    for linha in linhas:
        nome_curto = linha["nome_curto"].strip()
        try:
            categoria_id, subcategoria_id = _mapear_categoria_e_subcategoria(
                categorias,
                subcategorias_por_categoria,
                linha["categoria_publico"].strip(),
                linha["esfera"],
            )
            _conferir_categoria_publico(sessao, categoria_id, subcategoria_id)
            tier = None
            if not _vazio(linha["tier"]):
                tier = int(linha["tier"].strip().removeprefix("Tier ").strip())
            _conferir_tier(sessao, tier)
            uf = None
            if not _vazio(linha["abrangencia"]):
                abrangencia = linha["abrangencia"].strip()
                uf = ABRANGENCIA_PARA_UF.get(abrangencia, abrangencia)
            tipo = derivar_tipo(sessao, tipo=None, categoria_publico_id=categoria_id, atual=None)

            registro = Instituicao(
                nome=nome_curto,
                nome_normalizado=normalizar(nome_curto),
                tipo=tipo,
                nome_completo=(
                    linha["nome_completo"].strip() if not _vazio(linha["nome_completo"]) else None
                ),
                categoria_publico_id=categoria_id,
                subcategoria_publico_id=subcategoria_id,
                esfera_id=None,
                uf=uf,
                tier=tier,
                ativo=True,
            )
            gravar(
                sessao,
                registro,
                novo=True,
                ao_colidir=f"Já existe uma instituição chamada {nome_curto!r} do tipo {tipo!r}.",
            )
            ids_por_nome[registro.nome_normalizado] = registro.id
            resultado.criados["instituicoes"] += 1
        except RegraViolada as erro:
            if "Já existe" in str(erro):
                resultado.existentes["instituicoes"] += 1
                # A CHAVE REAL E (nome_normalizado, tipo) — o mesmo nome pode
                # existir com outro tipo (ex.: "ANA" como órgão e como
                # entidade). Buscar só por nome escolheria uma linha arbitrária
                # quando há mais de uma, e os contatos desta instituição
                # entrariam ligados à linha errada.
                existente = sessao.scalar(
                    select(Instituicao).where(
                        Instituicao.nome_normalizado == normalizar(nome_curto),
                        Instituicao.tipo == tipo,
                    )
                )
                if existente is not None:
                    ids_por_nome[existente.nome_normalizado] = existente.id
                else:
                    resultado.erros.append(
                        f"instituição {nome_curto!r}: colidiu mas não achei a linha "
                        f"existente com tipo {tipo!r} — contatos dela ficarão sem vínculo"
                    )
            else:
                resultado.erros.append(f"instituição {nome_curto!r}: {erro}")
    return ids_por_nome


def _importar_contatos(
    sessao: Session,
    linhas: list[Linha],
    ids_das_instituicoes: dict[str, str],
    resultado: Resultado,
) -> None:
    for linha in linhas:
        nome = linha["nome"].strip() if not _vazio(linha["nome"]) else None
        instituicao_nome = linha["instituicao"].strip()
        if not nome:
            resultado.erros.append(f"contato sem nome na instituição {instituicao_nome!r}")
            continue
        instituicao_id = ids_das_instituicoes.get(normalizar(instituicao_nome))
        if instituicao_id is None:
            resultado.erros.append(
                f"contato {nome!r}: instituição {instituicao_nome!r} não foi criada/encontrada"
            )
            continue
        try:
            registro = Interlocutor(
                nome=nome,
                nome_normalizado=normalizar(nome),
                instituicao_id=instituicao_id,
                cargo=linha["cargo"].strip() if not _vazio(linha["cargo"]) else None,
                area=linha["area"].strip() if not _vazio(linha["area"]) else None,
                email=linha["email"].strip() if not _vazio(linha["email"]) else None,
                redes_sociais=[],
                tipo=None,
                ativo=True,
            )
            gravar(
                sessao,
                registro,
                novo=True,
                ao_colidir=f"{nome!r} já está cadastrada em {instituicao_nome!r}.",
            )
            resultado.criados["contatos"] += 1
        except RegraViolada as erro:
            if "já está cadastrada" in str(erro):
                resultado.existentes["contatos"] += 1
            else:
                resultado.erros.append(f"contato {nome!r}: {erro}")


def _importar_representantes(sessao: Session, linhas: list[Linha], resultado: Resultado) -> None:
    areas = {a.nome: a.id for a in sessao.scalars(select(AreaPessoa))}
    for linha in linhas:
        nome = linha["nome"].strip()
        try:
            area_id = None
            if not _vazio(linha["area"]):
                area_csv = linha["area"].strip()
                nome_area = AREA_REPRESENTANTE_PARA_DICIONARIO.get(area_csv, area_csv)
                area_id = areas.get(nome_area)
                if area_id is None and area_csv != "Sustentabilidade":
                    resultado.avisos.append(
                        f"representante {nome!r}: área {area_csv!r} sem equivalente em "
                        "area_pessoa, entrou sem área"
                    )
            _conferir_area(sessao, area_id)
            tipo = linha["tipo"].strip() if not _vazio(linha["tipo"]) else None
            registro = PessoaAegea(
                nome=nome,
                nome_normalizado=normalizar(nome),
                cargo=linha["cargo"].strip() if not _vazio(linha["cargo"]) else None,
                email=linha["email"].strip() if not _vazio(linha["email"]) else None,
                eh_porta_voz=(tipo == "Porta-voz"),
                area_id=area_id,
                ativo=True,
            )
            gravar(
                sessao,
                registro,
                novo=True,
                ao_colidir=f"Já existe uma pessoa chamada {nome!r} na Aegea.",
            )
            resultado.criados["representantes"] += 1
        except RegraViolada as erro:
            if "Já existe" in str(erro):
                resultado.existentes["representantes"] += 1
            else:
                resultado.erros.append(f"representante {nome!r}: {erro}")


def importar(sessao: Session, pasta: Path) -> Resultado:
    resultado = Resultado()
    instituicoes = _ler_csv(pasta, "instituicoes.csv", COLUNAS_INSTITUICOES)
    contatos = _ler_csv(pasta, "contatos.csv", COLUNAS_CONTATOS)
    representantes = _ler_csv(pasta, "representantes_aegea.csv", COLUNAS_REPRESENTANTES)

    ids_das_instituicoes = _importar_instituicoes(sessao, instituicoes, resultado)
    _importar_contatos(sessao, contatos, ids_das_instituicoes, resultado)
    _importar_representantes(sessao, representantes, resultado)
    return resultado


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pasta", type=Path, help="pasta com os CSVs do dataset consolidado")
    parser.add_argument(
        "--confirmar",
        action="store_true",
        help="grava de verdade; sem isso, roda a seco (rollback no final)",
    )
    args = parser.parse_args()

    with obter_fabrica_de_sessao()() as sessao:
        resultado = importar(sessao, args.pasta)
        if args.confirmar:
            sessao.commit()
            print("Gravado.")
        else:
            sessao.rollback()
            print("A SECO — nada foi gravado. Rode com --confirmar para gravar de verdade.")
        resultado.imprimir()
    return 0


if __name__ == "__main__":
    sys.exit(main())
