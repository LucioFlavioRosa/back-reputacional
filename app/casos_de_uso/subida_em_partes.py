"""Subir um arquivo em pedaços: as REGRAS, sem o domínio de quem sobe.

O QUE ESTÁ AQUI é o que não depende de QUEM sobe: o tamanho do pedaço, quantos
pedaços um arquivo comporta, e as recusas que impedem um cliente de mandar o
que quiser.

O QUE NÃO ESTÁ, de propósito: a linha no banco, o dono, o caminho no
armazenamento e o que fazer com o arquivo montado. Isso é de cada domínio, e foi
misturar as duas coisas que deixou a Importação de bonds sem o mecanismo
enquanto ele já existia dentro da planilha do Score.

TUDO AQUI É FUNÇÃO PURA: nenhuma lê banco, armazenamento ou relógio, o que torna
cada recusa testável sem subir nada.
"""

from __future__ import annotations

from app.dominio.erros import RegraViolada

#: O PEDAÇO, e o número sai de medição, não de gosto.
#:
#: O TETO QUE MANDA é o do ingress do Container Apps: ~240 s por requisição, e
#: ele NÃO é configurável. Medido pela telemetria do próprio painel, 1,42 MB
#: subiram em 4 s e 1,33 MB em 73 s; 10,53 MB passaram de 212 s e levaram 403
#: três vezes. A banda de subida varia de ~18 KB/s a ~350 KB/s na mesma máquina
#: e na mesma hora, e a 18 KB/s os 10,53 MB precisariam de 390 s.
#:
#: 1 MB DÁ ~57 s NO PIOR CASO MEDIDO, quatro vezes de margem. Pedaço maior gasta
#: justamente a margem que não existe; pedaço menor multiplica idas sem comprar
#: segurança que já está em 4x.
TAMANHO_DA_PARTE = 1 * 1024 * 1024


def partes_esperadas(tamanho_declarado: int) -> int:
    """Quantas partes um arquivo daquele tamanho tem, para o teto do índice."""
    return -(-tamanho_declarado // TAMANHO_DA_PARTE)


def partes_maximas(teto_do_arquivo: int) -> int:
    """O máximo de partes que uma subida pode ter, derivado e não escolhido.

    EXISTE PORQUE `partes` VEM DO CLIENTE: sem este limite,
    `partes=1_000_000_000` na conferência faz o processo construir a lista de
    blocos ANTES de falar com o Azure, e uma requisição derruba a réplica.

    FUNÇÃO E NÃO CONSTANTE porque `TAMANHO_DA_PARTE` é trocado nos testes, e uma
    constante calculada no import ficaria com o valor antigo — o teto deixaria de
    valer exatamente onde se quer provar que ele vale.

    `teto_do_arquivo` VEM DE FORA porque é regra de quem sobe: a planilha do
    Score tem um teto de bytes, a de bonds tem o dela, e este módulo não deve
    conhecer nenhuma das duas.
    """
    return teto_do_arquivo // TAMANHO_DA_PARTE + 1


def conferir_a_parte(*, indice: int, dados: bytes, tamanho_declarado: int) -> None:
    """Recusa a parte que não cabe no que a subida declarou.

    OS DOIS TETOS: a rota da parte é isenta do limite genérico de corpo — tem de
    ser, senão a primeira parte seria recusada — e o servidor lê a parte inteira
    na memória. Sem eles, uma sessão autorizada manda partes de qualquer tamanho
    e acumula além do teto:

      * cada parte cabe em `TAMANHO_DA_PARTE`;
      * o índice cabe no que o TAMANHO DECLARADO comporta.

    Juntos, limitam o arquivo montado a pouco mais do que foi declarado — e o
    declarado já foi conferido contra o teto do domínio na abertura. A
    conferência final ainda mede os bytes de verdade, que é o que de fato
    autoriza.

    A PARTE VAZIA É RECUSADA: o Blob aceita bloco de zero byte, e um deles no
    meio da lista produz um `.xlsx` truncado que só falha na leitura, longe da
    causa.
    """
    esperadas = partes_esperadas(tamanho_declarado)
    if not dados:
        raise RegraViolada("A parte chegou vazia. Mande os bytes dela.")
    if indice < 0 or indice >= esperadas:
        raise RegraViolada(
            "Esta parte está fora do tamanho que a subida declarou. "
            "Comece a subida de novo."
        )
    #: PARTE CHEIA, EXCETO A ÚLTIMA — é o que faz a aritmética do teto fechar:
    #: com ela, o arquivo montado não passa de
    #: `partes_esperadas * TAMANHO_DA_PARTE`, que é o declarado arredondado para
    #: cima. Sem ela, partes menores permitiriam mais partes que o esperado e o
    #: total voltaria a ser ilimitado. O servidor dita o tamanho na abertura, e a
    #: recusa diz o número para quem estiver escrevendo outro cliente.
    ultima = indice == esperadas - 1
    if len(dados) > TAMANHO_DA_PARTE or (not ultima and len(dados) != TAMANHO_DA_PARTE):
        raise RegraViolada(
            f"Cada parte tem {TAMANHO_DA_PARTE} bytes, menos a última. "
            "Comece a subida de novo."
        )


def conferir_a_contagem(*, partes: int, tamanho_declarado: int, teto_do_arquivo: int) -> None:
    """Recusa a contagem de partes que não corresponde ao que foi declarado.

    `partes` VEM DO CLIENTE, e por isso tem dois tetos: `partes_maximas`, que
    deriva do teto do arquivo, e `partes_esperadas`, que é o que o tamanho
    DECLARADO desta subida comporta.
    """
    if partes <= 0:
        raise RegraViolada("Diga quantas partes o arquivo tem.")
    if partes > partes_maximas(teto_do_arquivo) or partes > partes_esperadas(tamanho_declarado):
        raise RegraViolada(
            "Esta contagem de partes não corresponde ao tamanho que a subida "
            "declarou. Comece a subida de novo."
        )
