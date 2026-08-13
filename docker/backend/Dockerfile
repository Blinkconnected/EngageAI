# syntax=docker/dockerfile:1
#
# Build context is the repository root (so this file can also reach
# docker/backend/entrypoint.sh); all backend sources are under backend/.

FROM python:3.13-slim AS base
ARG GIT_COMMIT=unknown
ARG BUILD_TIMESTAMP=unknown
ARG DOCKER_IMAGE_TAG=development
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GIT_COMMIT=$GIT_COMMIT \
    BUILD_TIMESTAMP=$BUILD_TIMESTAMP \
    DOCKER_IMAGE_TAG=$DOCKER_IMAGE_TAG
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 blinkengage \
    && useradd --uid 1000 --gid blinkengage --shell /bin/bash --create-home blinkengage

# The interpreter image ships setuptools in its *system* site-packages, and
# it lags: python:3.13-slim carried 70.3.0, which is CVE-2025-47273 (path
# traversal in PackageIndex). Nothing at runtime imports it — the app runs
# from /opt/venv — but it is in the image, so it is in the scan, and
# "unused" is not a property a scanner can verify. Upgraded rather than
# removed: pip's own vendoring expects it to exist.
RUN pip install --no-cache-dir --upgrade "setuptools>=78.1.1"

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

# Set in the same stage as the 4-worker CMD below, deliberately: the two
# belong together. prometheus_client keeps counters per process, so with
# --workers 4 and this unset, /metrics returns whichever worker answered
# and the series appear to jump backwards between scrapes. Declaring it on
# the image rather than in compose means the image cannot be run
# multi-worker with broken metrics by forgetting an environment entry.
#
# /dev/shm because it is tmpfs: the sample files are mmap'd and written on
# every request, and this keeps that off the container's writable layer.
# Docker recreates the mount on `docker restart` as well as on recreate —
# verified by leaving a marker file and restarting — so on this path the
# directory is already empty at start. The entrypoint clears it anyway:
# that is what holds if the variable is ever repointed at a bind mount or
# a named volume, where the files would otherwise outlive the container
# and be read as live workers on the next boot.
ENV PROMETHEUS_MULTIPROC_DIR=/dev/shm/prometheus

# pip has no job here. This stage receives an already-built venv and never
# installs anything, so a package installer in a production container is
# only attack surface.
#
# It is also what the image scan was actually reporting. pip *vendors* its
# own dependencies — `pip/_vendor/vendor.txt` pins `msgpack==1.1.2` and
# `setuptools==70.3.0`, both of which carry advisories — and Trivy reads
# them as installed packages. They are not the application's: the app's
# msgpack is 1.2.1 and it has no setuptools at all. No amount of changing
# our own pins could ever have cleared those two findings, which is worth
# knowing before somebody spends an afternoon trying.
RUN rm -rf /opt/venv/lib/python3.13/site-packages/pip \
           /opt/venv/lib/python3.13/site-packages/pip-*.dist-info \
           /usr/local/lib/python3.13/site-packages/pip \
           /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
           /opt/venv/bin/pip /opt/venv/bin/pip3 /opt/venv/bin/pip3.13 \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY CHANGELOG.md ./CHANGELOG.md
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
