# syntax=docker/dockerfile:1
#
# Production image: builds the frontend SPA and serves it via NGINX,
# reverse-proxying /api, /metrics and /ws to the backend service.
# Build context is the repository root.

FROM node:22-alpine AS frontend-build
WORKDIR /app
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_WS_BASE_URL=/api/v1/ws
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_WS_BASE_URL=$VITE_WS_BASE_URL
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY --from=frontend-build /app/dist /usr/share/nginx/html
COPY docker/nginx/nginx.prod.conf /etc/nginx/conf.d/default.conf

# 127.0.0.1, not localhost: this image's /etc/hosts maps "localhost" to
# ::1 only (no IPv4 entry) and nginx.prod.conf's `listen 80;` is IPv4-only
# — so `wget http://localhost/` always fails with connection-refused, and
# this healthcheck always reports unhealthy despite nginx actually working
# correctly. Confirmed live during M36's production-stack verification
# (docs/ROADMAP.md).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1
