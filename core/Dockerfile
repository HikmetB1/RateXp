# core - public ingestion service.
#
# Build with the Entra extra for cloud (Managed Identity DB auth):
#   docker build --build-arg EXTRAS=entra -t ratexp-core .
# Without it, core uses password auth from DATABASE_URL (local dev).
# EXTRAS is space-separated; add a redaction adapter to enable transcript PII
# redaction: --build-arg EXTRAS="entra redaction-presidio" (or redaction-azure).

FROM ghcr.io/astral-sh/uv:0.5 AS uv

FROM python:3.12-slim

ARG EXTRAS=""

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Lockfile-driven install - same deps every rebuild. EXTRAS may name several
# extras separated by spaces; each becomes its own --extra flag.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev \
      $(for e in $EXTRAS; do echo "--extra $e"; done)

# The Presidio adapter needs per-language spaCy models at runtime; fetch the ones
# it supports, only when that adapter is built in (keeps the image small otherwise).
RUN if echo " $EXTRAS " | grep -q " redaction-presidio "; then \
      python -m spacy download en_core_web_sm && \
      python -m spacy download es_core_news_sm && \
      python -m spacy download fr_core_news_sm && \
      python -m spacy download pt_core_news_sm && \
      python -m spacy download ru_core_news_sm; \
    fi

# ratexp.sh is the hook script core serves at GET /ratexp.sh. modules/ carries the
# migration .sql files alongside the code that applies them.
COPY load_config.py config.yaml ratexp.sh ./
COPY api/ ./api/
COPY modules/ ./modules/

# Non-root runtime user; owns nothing writable in /app or the venv.
RUN useradd -u 10001 -m ratexp && chown -R ratexp:ratexp /app /opt/venv
USER ratexp

EXPOSE 8000

# --proxy-headers + trust all forwarders: behind Azure's TLS-terminating proxy the
# app must honor X-Forwarded-Proto, or any redirect it issues goes out as http and
# the caller breaks. Azure forwards from a non-local IP, hence "*".
CMD ["uvicorn", "api.serve_http:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
