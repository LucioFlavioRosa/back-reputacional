"""Erros de domínio, e o que cada um pode dizer a quem.

O domínio não conhece HTTP. Ele levanta estes erros; a camada `api` os traduz
para status code em `app/api/erros.py`.

A POLÍTICA DE MENSAGEM, e por que ela não é "seja sempre genérico"

Até aqui, toda mensagem de erro ia inteira para o cliente. Para o time da casa
isso é excelente: "Analista só edita os registros que criou" diz exatamente o
que fazer. Para alguém de fora, a mesma frase é o mapa do modelo de permissão.

Mas tornar tudo genérico quebraria o produto. "UF inválida: 'XX'. Use uma das 27
siglas" é a mensagem que faz o formulário ser usável — trocá-la por "requisição
inválida" transformaria cada erro de digitação num chamado de suporte.

O corte não é por público, é pelo QUE A MENSAGEM DESCREVE:

    o pedido      "essa UF não existe", "essa data é inválida" — específica
                  para todo mundo. Descreve o que a pessoa enviou, e ela já sabe
                  o que enviou.

    o sistema     "analista só edita o que criou", "seu perfil não vê o
                  diretório" — específica para quem é da casa, genérica para
                  quem é de fora. Descreve como as regras funcionam por dentro.

    a existência  "interação X não encontrada" — genérica SEMPRE, e sem eco do
                  identificador. Confirmar que um id existe já é informação.
"""

from __future__ import annotations


class ErroDeDominio(Exception):
    """Raiz de todo erro previsto pelas regras do negócio.

    `publica` é o que qualquer pessoa pode ler. A mensagem completa vai sempre
    para o log — o que muda é o que sai na resposta.
    """

    #: Sobrescrito por quem não pode contar tudo.
    def publica(self, *, externo: bool) -> str:  # noqa: ARG002
        return str(self)


class RegraViolada(ErroDeDominio):
    """Uma invariante do agregado foi quebrada. Vira 422.

    A mensagem é específica para todos, de propósito: ela descreve o que veio no
    pedido, e quem enviou já sabe o que enviou. Esconder isso não protegeria
    nada e tornaria o formulário inutilizável.
    """


class NaoEncontrado(ErroDeDominio):
    """O registro pedido não existe, foi arquivado, ou está fora do alcance.

    As três causas produzem a MESMA resposta, e é isso que faz o 404 não virar
    um oráculo de existência: distinguir "não existe" de "existe e você não
    pode ver" entrega a segunda informação de graça.
    """

    #: Uma frase só, sem eco do identificador.
    #:
    #: Devolver o id que veio na URL parece inofensivo — a pessoa acabou de
    #: digitá-lo. Mas ecoar entrada do usuário numa resposta é hábito que se
    #: paga caro em outro lugar, e aqui não acrescenta nada: quem pediu sabe o
    #: que pediu.
    PUBLICA = "Registro não encontrado."

    def publica(self, *, externo: bool) -> str:
        return self.PUBLICA


class NaoAutorizado(ErroDeDominio):
    """A operação foi recusada. Vira 403.

    É o único erro cuja resposta depende de quem pergunta — e a distinção fina
    está DENTRO dele, porque "403" cobre duas coisas bem diferentes:

    SOBRE O MODELO DE PERMISSÃO (o padrão, `sobre_o_pedido=False`)

        "Analista só edita os registros que criou."
        "Seu perfil não tem acesso aos cadastros de stakeholders."

    Para quem é da casa, é o caminho mais curto para resolver: "peça à
    coordenação" resolve, "acesso negado" gera um chamado. Para quem é de fora,
    a mesma frase descreve quais papéis existem, o que cada um alcança, e que
    há um diretório de stakeholders. Nada disso é secreto isoladamente; junto,
    é o mapa que alguém montaria coletando mensagens de erro.

    SOBRE O PRÓPRIO PEDIDO OU O ESTADO DE QUEM PEDE (`sobre_o_pedido=True`)

        "Token de verificação ausente. Recarregue a página."
        "Sessão ausente ou expirada. Entre novamente."
        "Seu acesso ainda não foi liberado. Peça à coordenação do painel."

    Estas são específicas para TODO MUNDO. Não descrevem como o sistema decide
    nada — descrevem o estado de quem está pedindo, que a pessoa já conhece. E
    são acionáveis: trocá-las por "você não tem permissão" faria alguém com a
    sessão vencida ficar clicando sem nunca pensar em recarregar.

    Esta distinção nasceu de um teste que quebrou: a política inicial engolia a
    mensagem do CSRF e transformava uma instrução útil em beco sem saída.
    """

    PUBLICA = "Você não tem permissão para esta operação."

    def __init__(self, mensagem: str, *, sobre_o_pedido: bool = False) -> None:
        super().__init__(mensagem)
        self.sobre_o_pedido = sobre_o_pedido

    def publica(self, *, externo: bool) -> str:
        if self.sobre_o_pedido or not externo:
            return str(self)
        return self.PUBLICA
