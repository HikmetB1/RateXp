# app - the dashboard: one image serving the UI and its read-only API from a single origin.
#
#   docker build -t ratexp-app .
#
# Entra (Managed Identity database auth) is built in, so RATEXP_DB_AUTH picks password
# or entra at runtime. Nothing here is per-environment: config.yaml and the env vars
# pick what actually runs.

# --- Stage 1: build the dashboard bundle ---
FROM node:22-alpine AS frontend

WORKDIR /fe
COPY FE/package.json FE/package-lock.json ./
RUN npm ci
COPY FE/index.html FE/vite.config.js ./
COPY FE/src ./src
# Static assets (logo, favicons) - Vite copies public/ into dist/ at build.
COPY FE/public ./public

# Empty base => the bundle calls the API on its own origin (the same host serves both).
ENV VITE_API_BASE=""
RUN npm run build

# --- Stage 2: the API server, also serving the built UI ---
FROM ghcr.io/astral-sh/uv:0.5 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Lockfile-driven install - same deps every rebuild.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev --extra entra

COPY load_config.py config.yaml ./
COPY api/ ./api/
COPY modules/ ./modules/
# The built dashboard, served by api/serve_http.py at "/".
COPY --from=frontend /fe/dist ./static

# Non-root runtime user; owns nothing writable in /app or the venv.
RUN useradd -u 10001 -m ratexp && chown -R ratexp:ratexp /app /opt/venv
USER ratexp

EXPOSE 8000

CMD ["uvicorn", "api.serve_http:app", "--host", "0.0.0.0", "--port", "8000"]
