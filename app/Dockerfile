# The "app" web app: one image that serves the dashboard UI and its read-only
# API from a single origin. Build from the app/ directory:
#   docker build -f Dockerfile -t ratexp-app .
# Add the Entra extra for cloud (Managed Identity DB auth):
#   docker build --build-arg EXTRAS=entra -f Dockerfile -t ratexp-app .

# --- Stage 1: build the dashboard bundle ---
FROM node:22-alpine AS frontend

WORKDIR /fe
COPY app-fe/package.json app-fe/package-lock.json ./
RUN npm ci
COPY app-fe/index.html app-fe/vite.config.js ./
COPY app-fe/src ./src

# Empty base => the bundle calls the API on its own origin (same host as app-be).
ENV VITE_API_BASE=""
RUN npm run build

# --- Stage 2: the API server, also serving the built UI ---
FROM ghcr.io/astral-sh/uv:0.5 AS uv
FROM python:3.12-slim

ARG EXTRAS=""

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY app-be/pyproject.toml app-be/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev \
      $( [ -n "$EXTRAS" ] && echo "--extra $EXTRAS" )

COPY app-be/server.py app-be/models.py app-be/config.py app-be/config.yaml app-be/db.py ./
# The built dashboard, served by app-be at "/" (see server.py).
COPY --from=frontend /fe/dist ./static

RUN useradd -u 10001 -m ratexp && chown -R ratexp:ratexp /app /opt/venv
USER ratexp

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
