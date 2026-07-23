# syntax=docker/dockerfile:1
#
# Build context is the repository root (so this file can also reach
# docker/backend/entrypoint.sh); all backend sources are under backend/.

FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 blinkengage \
    && useradd --uid 1000 --gid blinkengage --shell /bin/bash --create-home blinkengage

# --- builder-runtime: compiles/installs production-only dependencies into a venv ---
FROM base AS builder-runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./
# A stub package satisfies setuptools' package discovery so dependencies can
# be resolved and installed before the real source is copied in, keeping this
# (slow) layer cached across source-only changes.
RUN mkdir -p src/blinkengage && touch src/blinkengage/__init__.py
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip && pip install .

COPY backend/src ./src
RUN pip install --no-deps .

# --- runtime: lean production image, no build toolchain, no dev dependencies ---
FROM base AS runtime
COPY --from=builder-runtime /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY docker/backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && chown -R blinkengage:blinkengage /app

USER blinkengage
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "blinkengage.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

# --- dev: full dependency set (incl. dev/test tools), hot-reload via bind mount ---
FROM base AS dev
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./
RUN mkdir -p src/blinkengage && touch src/blinkengage/__init__.py
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip && pip install -e ".[dev]"

COPY backend/ .
COPY docker/backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "blinkengage.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
