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

## Hot-reload development

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

> Requires Docker Compose v2.24.4 or newer; the development overlay uses the `!override` tag.

- Vite dev server with HMR on http://localhost:5173 (`/api` is proxied to the backend container)
- uvicorn runs with `--reload` and `./backend/app` mounted as a volume

## Local tooling (optional)

```sh
# Front end
cd frontend && npm install && npm run build   # typecheck + production bundle
npm run dev                                    # needs a backend on :8000 (or set BACKEND_URL)

# Back end
cd backend && uv sync && uv run uvicorn app.main:app --reload
```

## Structure

```
frontend/   React + TypeScript + Vite · multi-stage Dockerfile → nginx
  Dockerfile      build stage (npm ci + vite build) → runtime (nginx)
  nginx.conf      gzip · /assets caching · /api proxy · SPA fallback
backend/    FastAPI + uvicorn · uv for dependency management
  app/main.py     app factory, CORS, /api docs
  app/routes/     versioned API routers (health)
```
