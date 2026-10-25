# WindIQ

Modern, dockerized full-stack scaffold: **React (TypeScript) + Vite** front end built and served by **nginx**, **FastAPI** back end, wired together in Docker Compose.

## Quickstart

```sh
docker compose up --build
```

Then open:

- **App:** http://localhost:8080 — nginx serves the React build, gzips assets, and reverse-proxies `/api/*` to the backend (single host entrypoint)
- **API health:** http://localhost:8080/api/health
- **Interactive docs (Swagger):** http://localhost:8080/api/docs

The backend container is never exposed to the host — all traffic flows through nginx.

Useful Compose commands: `docker compose up --build` (foreground), add `--detach` to run in the background, `docker compose logs --follow` for logs, and `docker compose down` to stop and remove.

## Development (hot reload, no Docker)

Run the two halves directly with your local toolchain:

```sh
# Terminal 1 — API on http://localhost:8000 (reload on edit)
cd backend && uv sync && uv run uvicorn app.main:app --reload

# Terminal 2 — UI on http://localhost:5173 (HMR on edit)
cd frontend && npm install && npm run dev
```

Open http://localhost:5173; the Vite dev server proxies `/api/*` to the backend, so the app is same-origin just like in production. Swagger docs are at http://localhost:8000/api/docs. The API base URL is configurable via `BACKEND_URL` in the frontend (defaults to `http://localhost:8000`).

Production builds are still exercised with Docker (above) — that's where Docker earns its keep: a real nginx-served bundle instead of the dev server.

## Structure

```
frontend/   React + TypeScript + Vite · multi-stage Dockerfile → nginx
  Dockerfile      build stage (npm ci + vite build) → runtime (nginx)
  nginx.conf      gzip · /assets caching · /api proxy · SPA fallback
backend/    FastAPI + uvicorn · uv for dependency management
  app/main.py     app, /api/health endpoint, /api docs
```
