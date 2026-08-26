# =============================================================================
# API do Painel Reputacional
#
# Duas etapas: a primeira instala as dependências, a segunda só copia o que
# precisa rodar. Sem isso, o compilador de C do `psycopg2` e as ferramentas de
# build ficariam na imagem final — dezenas de megabytes de superfície que só
# servem para quem quiser explorá-la.
# =============================================================================

FROM python:3.13-slim AS dependencias

# `libpq-dev` e `gcc` só existem AQUI. `psycopg2-binary` traz o driver
# compilado, mas `cryptography` (do PyJWT) pode precisar compilar conforme a
# arquitetura.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /instalacao
COPY pyproject.toml ./
COPY app ./app
COPY main.py ./

# `--prefix` para copiar a árvore inteira na etapa seguinte com um `COPY` só.
RUN pip install --no-cache-dir --prefix=/dependencias .


FROM python:3.13-slim AS aplicacao

# Não roda como root.
#
# Um contêiner comprometido rodando como root é root no namespace do host — e
# com montagem de volume, isso alcança arquivo do host. O usuário sem shell
# (`--no-create-home`, `/usr/sbin/nologin`) reduz o que dá para fazer depois de
# entrar.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin painel

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=dependencias /dependencias /usr/local
COPY --chown=painel:painel app /aplicacao/app
COPY --chown=painel:painel main.py /aplicacao/
COPY --chown=painel:painel pyproject.toml /aplicacao/

WORKDIR /aplicacao
ENV PYTHONPATH=/aplicacao \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER painel
EXPOSE 8000

# `/api/saude` não é isenta do limite de taxa — e não precisa ser: o balde é por
# IP, e a sonda faz poucas requisições por minuto contra uma capacidade de
# centenas. Isso foi medido; ver `test_sonda_de_saude_nunca_encosta_no_teto_padrao`.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/api/saude || exit 1

# Um worker só. Com mais de um, o limite de taxa — que guarda estado em memória
# por processo — passa a valer N vezes o configurado, silenciosamente. Em
# produção quem dá o teto de verdade é a borda; aqui, um worker mantém o
# comportamento local igual ao que os testes descrevem.
#
# SEM `--proxy-headers`, e isto é deliberado.
#
# Com ele, o uvicorn reescreve `request.client.host` a partir do
# `X-Forwarded-For`, pegando a PRIMEIRA entrada — justamente a que o cliente
# controla. Isso passaria por cima do tratamento que a aplicação faz:
# `ip_do_cliente` lê da DIREITA e conta os proxies confiáveis declarados.
#
# Pior: com `PROXIES_CONFIAVEIS=0` a aplicação IGNORA o cabeçalho e usa o
# endereço da conexão. Se o uvicorn o tivesse reescrito antes, esse padrão
# seguro deixaria de ser seguro sem nada no código denunciando.
#
# Quem decide o endereço do cliente é `app/seguranca/limite_de_taxa.py`, e é o
# único lugar que deve decidir. Para conferir: `curl -H "X-Forwarded-For:
# 1.2.3.4"` não pode fazer o log de acesso mostrar aquele endereço.
CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
