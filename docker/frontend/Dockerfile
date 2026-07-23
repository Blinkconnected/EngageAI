# syntax=docker/dockerfile:1
#
# Dev-only image: runs the Vite dev server with hot reload. Build context is
# the repository root so it can share a .dockerignore with the backend.

FROM node:22-alpine AS dev
WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
