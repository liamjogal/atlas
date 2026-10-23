# One image runs every Atlas command (serve, worker, sync, facilities). See docker-compose.yml.

# --- Web app: build the static bundle ---------------------------------------------------------
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- Runtime -----------------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# osmium-tool builds facilities from Geofabrik extracts (the Debian package of `brew install osmium-tool`).
RUN apt-get update \
 && apt-get install -y --no-install-recommends osmium-tool ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    ATLAS_DATA_DIR=/data

WORKDIR /app
# Dependencies first, so code changes don't re-download them.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY ontology/ ontology/
COPY src/ src/
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist web/dist

# Bake DuckDB's spatial extension into the image instead of downloading it at first sync.
RUN python -c "import duckdb; duckdb.connect().execute('INSTALL spatial')"

# Data (landing files, DuckDB, the ~13 GB OSM extract) lives on a volume; secrets come from the
# environment at run time and are never copied into the image (see .dockerignore).
VOLUME /data
EXPOSE 8000
CMD ["atlas", "serve", "--host", "0.0.0.0"]

# --- Tests: `docker build --target test .` runs the suite on Linux ----------------------------
FROM runtime AS test
RUN uv sync --frozen
COPY tests/ tests/
RUN uv run pytest -q
