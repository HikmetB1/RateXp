# core - public ingestion service.
#
#   docker build -t ratexp-core --build-context repo=.. .
#
# The docs site at /guide/ is built from the whole repo, which comes in as the extra
# build context named "repo" (see CONTRIBUTING.md).
#
# Every optional adapter is built in, so whatever config.yaml switches on is
# already present. Nothing here is per-environment: config.yaml and the env vars
# pick what actually runs.

FROM ghcr.io/astral-sh/uv:0.5 AS uv

# --- Stage 1: build the docs site from the repo's markdown ---
FROM python:3.12-slim AS guide

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /repo/docs-server
COPY --from=repo docs-server/pyproject.toml docs-server/uv.lock ./
RUN uv sync --frozen
# The whole repo, not only the pages: the build checks that every repo path a page links
# to exists. The repo root's .dockerignore keeps local files, caches and secrets out.
COPY --from=repo . /repo/
RUN uv run --frozen mkdocs build --strict

# --- Stage 2: core itself ---
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
      --extra labeling \
      --extra dynatrace-otlp

# The Presidio adapter loads these per-language spaCy models at runtime; pip won't
# pull them, so fetch them here (see modules/redaction/adapters/redact_with_presidio.py).
RUN python -m spacy download en_core_web_sm && \
    python -m spacy download es_core_news_sm && \
    python -m spacy download fr_core_news_sm && \
    python -m spacy download pt_core_news_sm && \
    python -m spacy download ru_core_news_sm

# The evals core sends to the plugin's hooks at /hook-settings. modules/ carries the
# migration .sql files alongside the code that applies them.
COPY load_config.py config.yaml ./
COPY evals/ ./evals/
COPY api/ ./api/
COPY modules/ ./modules/
# The built docs site, served by api/serve_http.py at /guide/. It sits beside /app, as
# docs-server/ sits beside core/ in the repo, so docker compose's live mount of core/
# over /app leaves it in place.
COPY --from=guide /repo/docs-server/site /docs-server/site
# The plugin's manifest, for the newest plugin version at /hook-settings. It sits
# beside /app as plugins/ sits beside core/ in the repo, for the same reason.
COPY --from=repo plugins/claude-code/.claude-plugin/plugin.json /plugins/claude-code/.claude-plugin/plugin.json

# Non-root runtime user; owns nothing writable in /app or the venv.
RUN useradd -u 10001 -m ratexp && chown -R ratexp:ratexp /app /opt/venv
USER ratexp

EXPOSE 8000

# --proxy-headers + trust all forwarders: behind Azure's TLS-terminating proxy the
# app must honor X-Forwarded-Proto, or any redirect it issues goes out as http and
# the caller breaks. Azure forwards from a non-local IP, hence "*".
CMD ["uvicorn", "api.serve_http:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
