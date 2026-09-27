# core - public ingestion service.
#
#   docker build -t ratexp-core .
#
# Every optional adapter is built in, so whatever config.yaml switches on is
# already present. Nothing here is per-environment: config.yaml and the env vars
# pick what actually runs.

FROM ghcr.io/astral-sh/uv:0.5 AS uv

FROM python:3.12-slim

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Lockfile-driven install - same deps every rebuild. entra is Managed Identity DB
# auth, the two redaction- extras are the PII adapters, dynatrace-otlp the OTLP
# destinations. All four so a config.yaml change never needs a matching rebuild.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev \
      --extra entra \
      --extra redaction-presidio \
      --extra redaction-azure \
      --extra dynatrace-otlp

# The Presidio adapter loads these per-language spaCy models at runtime; pip won't
# pull them, so fetch them here (see modules/redaction/adapters/redact_with_presidio.py).
RUN python -m spacy download en_core_web_sm && \
    python -m spacy download es_core_news_sm && \
    python -m spacy download fr_core_news_sm && \
    python -m spacy download pt_core_news_sm && \
    python -m spacy download ru_core_news_sm

# One hook script per coding agent; core serves each at its own name.
# modules/ carries the migration .sql files alongside the code that applies them.
COPY load_config.py config.yaml ./
COPY ratexp-claude.sh ratexp-cursor.sh ./
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
