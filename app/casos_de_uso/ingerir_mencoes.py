"""A planilha do fornecedor entrando no índice.

O que este módulo acrescenta ao `dominio/ingestao_score.py`: abrir o `.xlsx`
(openpyxl), achar a aba, casar o cabeçalho com o mapeamento gravado e trocar o
mês inteiro no banco. A regra de o que vira menção NÃO mora aqui.

SUBSTITUIÇÃO POR MÊS, e não acréscimo. O fornecedor reenvia o arquivo quando
corrige uma classificação — e o mesmo post reenviado, somado, contaria duas
vezes. Cada mês presente no arquivo é apagado e regravado; um mês que o arquivo
não traz fica intacto, porque o export de junho não é uma afirmação sobre maio.

POR QUE O AGREGADO SE REFAZ AQUI. `score_mes_fonte` guarda as quatro somas de
que toda régua precisa. Como a substituição deixa o banco com exatamente as
menções do arquivo para aqueles meses, as somas do arquivo JÁ SÃO as somas do
mês — não há por que relê-las do banco para conferir a própria escrita.
"""

from __future__ import annotations

import io
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.banco.tabelas_score import Mencao, ScoreFonte, ScoreMesFonte
from app.dominio.erros import RegraViolada
from app.dominio.ingestao_score import Leitura, Mapeamento, ler_planilha, somar

#: Abrir uma planilha de 10 mil linhas é barato; abrir um arquivo de 200 MB
#: enviado por engano não é. O maior dos quatro exports de hoje tem 1,4 MB.
TAMANHO_MAXIMO = 40 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Resumo:
    """O que a ingestão fez — o que a tela mostra depois do upload."""

    fonte: str
    linhas: int
    ingeridas: int
    descartes: Mapping[str, int]
    meses: tuple[date, ...]


def _linhas_da_aba(conteudo: bytes, mapeamento: Mapeamento) -> Iterator[Mapping[str, object]]:
    """As linhas da planilha como dicionários cabeçalho → célula."""
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as erro:  # pragma: no cover - dependência declarada
        raise RegraViolada("Leitura de planilha indisponível neste servidor.") from erro

    # `read_only` não carrega a planilha inteira na memória, e `data_only` traz
    # o VALOR de uma célula com fórmula — sem ele, a coluna de engajamento
    # calculada chegaria como a string "=SOMA(...)".
    try:
        planilha = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except Exception as erro:
        # Um `.xls` antigo, um CSV renomeado ou um upload truncado chegam aqui.
        # Sem a tradução, o openpyxl devolveria 500 e a pessoa leria "erro
        # interno" para um arquivo que ela mesma pode trocar.
        raise RegraViolada(
            "Não consegui abrir o arquivo como planilha .xlsx. "
            "Se ele veio em .xls ou .csv, salve como .xlsx e envie de novo."
        ) from erro
    try:
        if mapeamento.aba and mapeamento.aba in planilha.sheetnames:
            aba = planilha[mapeamento.aba]
        elif mapeamento.aba:
            raise RegraViolada(
                f"A planilha não tem a aba {mapeamento.aba!r}. "
                f"Abas encontradas: {', '.join(planilha.sheetnames)}."
            )
        else:
            aba = planilha[planilha.sheetnames[0]]

        linhas = aba.iter_rows(values_only=True)
        try:
            cabecalho = [
                str(celula).strip() if celula is not None else ""
                for celula in next(linhas)
            ]
        except StopIteration:
            raise RegraViolada("A planilha está vazia.") from None

        faltando = sorted(mapeamento.colunas_necessarias - set(cabecalho))
        if faltando:
            raise RegraViolada(
                "A planilha não tem as colunas que o cadastro desta fonte espera: "
                f"{', '.join(faltando)}."
            )

        for linha in linhas:
            yield dict(zip(cabecalho, linha, strict=False))
    finally:
        planilha.close()


def _regravar(sessao: Session, fonte: ScoreFonte, leitura: Leitura) -> None:
    """Troca os meses que o arquivo traz — menções e agregado."""
    meses = list(leitura.meses)
    sessao.execute(
        delete(Mencao).where(Mencao.fonte_id == fonte.id, Mencao.mes.in_(meses))
    )
    sessao.execute(
        delete(ScoreMesFonte).where(
            ScoreMesFonte.fonte_id == fonte.id, ScoreMesFonte.mes.in_(meses)
        )
    )

    sessao.add_all(
        Mencao(
            fonte_id=fonte.id,
            mes=mencao.mes,
            data=mencao.data,
            sentimento=mencao.sentimento,
            tier=mencao.tier,
            engajamento=mencao.engajamento,
            cargo=mencao.cargo,
            atributo=mencao.atributo,
            veiculo=mencao.veiculo,
            publico_alvo=mencao.publico_alvo,
            tema_texto=mencao.tema_texto,
        )
        for mencao in leitura.mencoes
    )
    sessao.add_all(
        ScoreMesFonte(
            fonte_id=fonte.id,
            mes=soma.mes,
            sentimento=soma.sentimento,
            tier=soma.tier,
            mencoes=soma.mencoes,
            soma_log=soma.soma_log,
            soma_engajamento=soma.soma_engajamento,
            soma_cargo=soma.soma_cargo,
        )
        for soma in somar(leitura.mencoes)
    )
    sessao.flush()


def ingerir(sessao: Session, fonte: ScoreFonte, conteudo: bytes) -> Resumo:
    """Lê a planilha desta fonte e substitui os meses que ela traz."""
    if fonte.interna:
        raise RegraViolada(
            f"{fonte.nome} é fonte interna: o dado já está neste banco e não se importa."
        )
    if not fonte.ativo:
        raise RegraViolada(f"{fonte.nome} está inativa. Reative-a antes de importar.")
    if len(conteudo) > TAMANHO_MAXIMO:
        raise RegraViolada("A planilha passa de 40 MB.")

    try:
        mapeamento = Mapeamento.de_json(fonte.mapeamento_colunas)
    except ValueError as erro:
        # O mapeamento é cadastro, não entrada de usuário: um mapeamento
        # quebrado é problema de configuração da fonte, e a mensagem precisa
        # dizer isso, senão quem subiu o arquivo procura o defeito no arquivo.
        raise RegraViolada(
            f"O mapeamento de colunas de {fonte.nome} está inválido: {erro}"
        ) from erro

    leitura = ler_planilha(_linhas_da_aba(conteudo, mapeamento), mapeamento)
    if not leitura.mencoes:
        raise RegraViolada(
            "Nenhuma linha da planilha virou menção. "
            f"Lidas {leitura.linhas}; descartes: {dict(leitura.descartes)}."
        )

    _regravar(sessao, fonte, leitura)
    return Resumo(
        fonte=fonte.codigo,
        linhas=leitura.linhas,
        ingeridas=len(leitura.mencoes),
        descartes=leitura.descartes,
        meses=leitura.meses,
    )
