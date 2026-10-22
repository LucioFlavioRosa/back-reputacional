"""O leitor de planilha da plataforma: os DOIS caminhos entregam o mesmo dado.

POR QUE ESTA SUÍTE EXISTE. O mecanismo é "calamine primeiro, openpyxl de
reserva". Isso só é honesto se os dois concordarem sobre o conteúdo do arquivo
— senão a MESMA planilha produz dados diferentes conforme o leitor rápido
aceite ou recuse o arquivo, e ninguém consegue reproduzir a diferença.

O QUE JÁ DIVERGIU, e é o que estes testes trancam: a célula de ERRO do Excel.
O openpyxl entrega a string que o Excel escreveu (`'#N/A'`); o calamine entrega
vazio. Achado de revisão em 22/10/2026.
"""

from __future__ import annotations

import io
import re
import zipfile

from openpyxl import Workbook, load_workbook

from app.casos_de_uso.leitor_de_planilha import celulas_pelo_calamine, sem_erro_do_excel


def _com_celulas_de_erro() -> bytes:
    """Um `.xlsx` de verdade com duas células de ERRO.

    O openpyxl NÃO escreve célula de erro — ele escreveria a string. Então o
    arquivo é montado normalmente e a aba é reescrita dentro do ZIP, trocando
    duas células pela forma que o Excel usa: `<c r="B1" t="e"><v>#N/A</v></c>`.
    É a única maneira de reproduzir no teste o que vem de uma planilha real com
    fórmula quebrada.
    """
    livro = Workbook()
    folha = livro.active
    folha["A1"] = "AEGEBZ31"
    folha["B1"] = "vira erro"
    folha["A2"] = 10
    folha["B2"] = "vira erro"
    bruto = io.BytesIO()
    livro.save(bruto)

    saida = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(bruto.getvalue())) as entrada:
        with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as novo:
            for item in entrada.infolist():
                dados = entrada.read(item.filename)
                if item.filename == "xl/worksheets/sheet1.xml":
                    texto = dados.decode("utf-8")
                    texto = re.sub(
                        r'<c r="B1"[^>]*>.*?</c>', '<c r="B1" t="e"><v>#N/A</v></c>', texto
                    )
                    texto = re.sub(
                        r'<c r="B2"[^>]*>.*?</c>', '<c r="B2" t="e"><v>#DIV/0!</v></c>', texto
                    )
                    dados = texto.encode("utf-8")
                novo.writestr(item, dados)
    return saida.getvalue()


def _pelo_openpyxl(conteudo: bytes) -> list[tuple]:
    """O caminho de reserva, como `ingerir_bonds` e `ArquivoLido` o usam."""
    pasta = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    try:
        folha = pasta[pasta.sheetnames[0]]
        return [sem_erro_do_excel(linha) for linha in folha.iter_rows(values_only=True)]
    finally:
        pasta.close()


def test_a_celula_de_ERRO_sai_igual_pelos_DOIS_leitores():
    """ACHADO DE REVISÃO. Medido antes do conserto, no mesmo arquivo:

        openpyxl   '#N/A'   '#DIV/0!'    (a string, como o Excel a escreveu)
        calamine   ''       ''           (vazio — o erro não sobrevive)

    O ESTRAGO ERA SILENCIOSO: um ticker com `#N/A` no catálogo dos bonds some
    pelo caminho rápido e vira um papel de ticker "#N/A" pelo de reserva — a
    mesma planilha, dois cadastros diferentes.

    O ACERTO É PARA `None`, e não para a string, porque o calamine não diz QUAL
    erro era: não há como fazer o rápido parecer com o antigo. E é o sentido
    certo de qualquer forma — célula que deu erro não tem valor.
    """
    conteudo = _com_celulas_de_erro()

    assert celulas_pelo_calamine(conteudo) == _pelo_openpyxl(conteudo)


def test_o_ERRO_vira_NADA_e_nao_o_texto_do_erro():
    """O teste acima passaria se os dois entregassem a string — esta asserção
    fixa QUAL dos dois lados venceu."""
    conteudo = _com_celulas_de_erro()

    linhas = _pelo_openpyxl(conteudo)

    assert linhas[0] == ("AEGEBZ31", None)
    assert linhas[1] == (10, None)


def test_a_linha_SEM_erro_volta_a_MESMA_tupla():
    """`sem_erro_do_excel` roda uma vez por linha em arquivos de 50 mil linhas.
    Reconstruir toda tupla seria lixo para o coletor sem necessidade: quase
    nenhuma linha tem erro."""
    linha = ("Valor Econômico", 10, None, "texto")

    assert sem_erro_do_excel(linha) is linha


def test_o_TEXTO_que_so_PARECE_erro_nao_e_apagado():
    """`#VALUE!` no meio de uma frase é texto, não célula de erro.

    A comparação é com a célula INTEIRA justamente por isso: uma busca por
    `"#N/A" in valor` apagaria o título de uma matéria que mencione o termo.
    """
    linha = ("A planilha mostrava #N/A em toda a coluna", "#N/A")

    assert sem_erro_do_excel(linha) == ("A planilha mostrava #N/A em toda a coluna", None)
