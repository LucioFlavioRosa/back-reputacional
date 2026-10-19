"""O fornecedor traz UM nível da árvore; o resto é derivado do cadastro.

A DECISÃO DE PRODUTO (dono do produto, 18/10/2026), que é o que este módulo
existe para cumprir:

    o fornecedor vai trazer o N1 OU o N2 OU o N3;
    se trazer o N3, o N2 e o N1 são derivados do cadastro;
    se trazer o N2, o N1 é derivado do cadastro.

Nunca o contrário: um N1 não inventa o N2 nem o N3 dele. `bloco_tema`
(N1) tem 7 filhos diretos em média e `macro_tema` (N2) tem 2,5 — descer seria
escolher um por sorteio, e a escolha apareceria nos gráficos como fato.

== POR QUE ISTO NÃO É A REDUNDÂNCIA QUE A 0069 TIROU ==

A `0069` tirou `atributo` do mapeamento da Bites, e a `0079` mediu o motivo: na
planilha consolidada da Bites a coluna `Atributo` CONTRADIZ a coluna `N1` em
1.418 das 2.842 linhas — metade. Aquele defeito nasceu de LER DOIS NÍVEIS DO
MESMO ARQUIVO e guardar os dois como afirmação.

A regra acima torna isso impossível por construção, e não por vigilância: um
nível por fornecedor entra como afirmação, os de cima saem da árvore. Dois
valores do mesmo nível nunca coexistem, então não há o que divergir.

== E O N1 DA CLIPEI PASSA A VALER, porque foi medido ==

`test_niveis_do_fornecedor.py` registrava a pendência com a frase certa: "se
este teste quebrar, há uma decisão a tomar, não um número a atualizar". A
medição que faltava (base local, 104.670 menções, 18/10/2026):

    onde a menção tem os DOIS N1 (o derivado do N3 e o do `Atributo`):
        clipei               27.315 concordam, 2 DISCORDAM   (99,993%)
        clipei_investidores     330 concordam, 0 discordam

    onde a menção tem SÓ o N1 do fornecedor (não casou N3 no cadastro):
        clipei               72.590 menções
        clipei_investidores   1.338 menções

Ou seja: o `Atributo` da Clipei não é um segundo N1 que contradiz o derivado —
é o ÚNICO N1 de 73.928 menções, 71% da base. A Clipei não fala o vocabulário do
N3 (71 dos 326 assuntos distintos dela casam no cadastro), e descartar o
`Atributo` como a Bites fez deixaria 71% do volume fora de todo recorte por
pilar. As 2 linhas que discordam perdem para o derivado, pela regra abaixo.

A diferença entre os dois fornecedores é real e é essa: a Bites fala N3
(92 de 92 assuntos casam) e por isso não precisa declarar N1; a Clipei fala N1.

== A CHAVE DE COMPARAÇÃO ==

`chave_do_nivel` é a terceira chave derivada de nome deste código, e é
DELIBERADAMENTE diferente das outras — ver `dominio/texto.py`:

    normalizar              escrita e unicidade          (a base desta)
    achatar_para_comparar   semelhança
    codigo_estavel          endereço em URL e SQL

Esta é `normalizar` MAIS a remoção do prefixo numerado que os exports carregam,
e o prefixo é a razão de ela existir. Medido: `Atributo` tem 15 grafias para os
7 N1 do cadastro, porque metade do volume vem numerada:

    Eficiência Operacional e Qualidade      47.872     casa no cadastro
    2. Eficiência Operacional e Qualidade   11.591     NÃO casa
    Governança                               4.799     casa
    1. Governança                            4.602     NÃO casa
    ...                                     (mais 5 pares)

São 26.603 menções (26% das que têm atributo) do lado de fora do cadastro por
causa de um `"2. "`. É a mesma falha de classe da `0097` — duas grafias do
mesmo nome coexistindo, uma barra virando duas em todo gráfico e todo filtro —,
agora no eixo do N1 e com 100 mil linhas atrás.

Tirando o prefixo, 100.331 das 101.245 casam (99,1%). As 914 que sobram são
`Marca empregadora` (733) e `Outros` (181): não são grafia errada de um N1, são
valores que o cadastro não tem. Ficam sem N1, e é o certo — inventar um pilar
para elas seria afirmar o que ninguém afirmou.

NÃO É `prefixo_a_remover` DO MAPEAMENTO. Aquele é convenção declarada de UM
fornecedor ("Aegea - " na frente da unidade) e vale para o rótulo que vai para a
tela. Este é a forma de COMPARAR com o cadastro, vale para todo fornecedor, e
não muda o texto guardado: `mencao.atributo` continua tendo a palavra exata que
a planilha trouxe, porque é contra ela que a carga é auditável.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.dominio.texto import normalizar

#: O "2. " de `2. Eficiência Operacional e Qualidade`.
#:
#: "7. X", "7) X", "7 - X", "7 – X": o número do pilar com qualquer separador
#: que um export à mão costuma ter, com ou sem espaço antes dele.
#:
#: ESTE REGEX NÃO É NOVO: ele vinha de `consulta_profundidade.sem_prefixo`, que
#: resolve o pilar pelo atributo na LEITURA desde que a tela de aprofundamento
#: existe. Mudou de casa para cá e lá passou a importar daqui, porque com a
#: `0098` a mesma regra também decide o que é GRAVADO — e duas cópias de uma
#: regra de chave é exatamente o que as `0097`/PR #92 existiram para acabar.
#:
#: E EU QUASE O REESCREVI MAIS ESTRITO. A primeira versão deste módulo exigia o
#: separador (`\d{1,2}\s*[.)-]\s+`), o que é defensável em teoria — `Lei 14.026`
#: não perderia o número — e teria mudado em silêncio o pilar de toda menção na
#: tela de aprofundamento, que é o que o regex de verdade já decide em
#: produção. O shipped manda; uma regra melhor é mudança de comportamento, com
#: medição e decisão, não efeito colateral de uma mudança de casa.
_PREFIXO_NUMERICO = re.compile(r"^\s*[0-9]+\s*[.)\-–]?\s*")


def sem_numeracao(texto: str) -> str:
    """'7. Prosperidade Compartilhada' vira 'Prosperidade Compartilhada'.

    O EXPORT REAL NUMERA O PILAR e o mock não. Sem tirar o número, nenhum
    atributo real casaria com o cadastro — e todo o mês cairia em "sem pilar"
    com a conta certa e a árvore vazia, o pior jeito de errar porque parece
    funcionar.

    PÚBLICA porque são três leitores: a leitura (`consulta_profundidade`), a
    gravação (`temas_da_mencao.Arvore`) e o backfill da `0098`, que faz o mesmo
    recorte em SQL. O teste compara os três sobre o mesmo corpus — foi assim que
    a `0097` descobriu que a sua versão SQL divergia em 67 de 87 valores reais.
    """
    return _PREFIXO_NUMERICO.sub("", texto)


def chave_do_nivel(texto: object) -> str:
    """A forma de procurar um nome de nível no cadastro. Vazio se não há nome.

    Devolve `""` para nulo e para branco, e quem chama trata `""` como ausência
    — é o mesmo contrato de `temas_da_mencao.por_nome`, que nunca tem `""` entre
    as chaves porque nenhum nome do cadastro normaliza para vazio.
    """
    return normalizar(sem_numeracao(str(texto or "")))


@dataclass(frozen=True, slots=True)
class Niveis:
    """Onde a menção caiu na árvore do cadastro. Nulo é "o cadastro não sabe".

    OS TRÊS SÃO INDEPENDENTEMENTE NULOS, e cada combinação quer dizer uma coisa:

        n1, n2, n3    o fornecedor falou N3 e o cadastro reconheceu
        n1, n2        falou N2 (ou falou um N3 que o cadastro não tem, e o N1
                      veio do campo de N1 — a Clipei)
        n1            falou só N1
        nada          o cadastro não reconheceu nada do que ele falou
    """

    n1_id: int | None = None
    n2_id: int | None = None
    n3_id: int | None = None

    @property
    def nivel_mais_fundo(self) -> str | None:
        """`"n3"`, `"n2"`, `"n1"` ou `None` — o que de fato se sabe da menção.

        É O QUE A TELA PRECISA PARA NÃO MENTIR NO RÓTULO: uma menção ligada só
        ao pilar não pode aparecer sob "Subtema", e hoje `causa_da_lente` chama
        `tema_texto` de "Pilar (N1)" para todo fornecedor — inclusive para a
        Bites, cujo `tema_texto` é o N3.
        """
        if self.n3_id is not None:
            return "n3"
        if self.n2_id is not None:
            return "n2"
        if self.n1_id is not None:
            return "n1"
        return None
