# core — public ingestion service.
#
# Build with the Entra extra for cloud (Managed Identity DB auth):
#   docker build --build-arg EXTRAS=entra -t ratexp-core .
# Without it, core uses password auth from DATABASE_URL (local dev).

FROM ghcr.io/astral-sh/uv:0.5 AS uv

FROM python:3.12-slim

ARG EXTRAS=""

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Lockfile-driven install — same deps every rebuild.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev \
      $( [ -n "$EXTRAS" ] && echo "--extra $EXTRAS" )

COPY server.py models.py migrate.py atif.py config.py config.yaml db.py store.py ratelimit.py ./
COPY prompt/ ./prompt/
COPY scripts/ ./scripts/
COPY migrations/ ./migrations/

# Non-root runtime user; owns nothing writable in /app or the venv.
RUN useradd -u 10001 -m ratexp && chown -R ratexp:ratexp /app /opt/venv
USER ratexp

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
