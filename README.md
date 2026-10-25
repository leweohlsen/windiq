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

## CI/CD (GitHub Actions → Coolify)

- **CI** (`.github/workflows/ci.yml`) — every PR and push to `main`: type-checks & builds the frontend, syncs the backend against `uv.lock`, and builds both Docker images.
- **Deploy** (`.github/workflows/deploy.yml`) — on push to `main`: builds and pushes `windiq-backend` / `windiq-frontend` images to GHCR (`ghcr.io/leweohlsen/…:latest` + `:sha-<commit>`), then pings the Coolify deploy webhook so the VPS pulls the fresh images (`docker-compose.prod.yml`).

One-time setup:

1. Coolify: create a **Docker Compose** app from this repo, pointing at `docker-compose.prod.yml`.
2. Coolify: copy the app's **deploy webhook** URL and add it as the GitHub secret `COOLIFY_WEBHOOK_URL` (optional `COOLIFY_API_TOKEN` if you use the API-style webhook).
3. Make sure the repo's GHCR packages (`windiq-frontend`, `windiq-backend`) are visible to Coolify — public packages pull anonymously, private ones need a registry credential.

Rollback: in `docker-compose.prod.yml`, pin the image tags to `sha-<commit>` and redeploy.

## Structure

```
frontend/   React + TypeScript + Vite · multi-stage Dockerfile → nginx
  Dockerfile      build stage (npm ci + vite build) → runtime (nginx)
  nginx.conf      gzip · /assets caching · /api proxy · SPA fallback
backend/    FastAPI + uvicorn · uv for dependency management
  app/main.py     app, /api/health endpoint, /api docs
  app/windiq/     typed client facade for the WindIQ Measurement API (auto-generated client + bearer-token auth)
  packages/
    windiq_client/
                    auto-generated OpenAPI client (openapi-python-client → httpx + attrs). DO NOT edit by hand:
                    regenerate with `uv run scripts/generate-client.sh` from https://windiq-mock-api.sliplane.app/openapi.json

## WindIQ Measurement API client

The backend consumes turbine data from the WindIQ mock API (spec: https://windiq-mock-api.sliplane.app/openapi.json).

The client library in `backend/packages/windiq_client/` is **generated** from that spec with
[openapi-python-client](https://github.com/dynamicalsoftware/openapi-python-client) (pydantic-style typed models + httpx).
To regenerate after the spec changes:

```sh
cd backend && uv run scripts/generate-client.sh
```

Credentials come from the environment (see `backend/.env.example`; copy to `backend/.env` for local dev — it is gitignored):

```
WIQ_API_BASE_URL=https://windiq-mock-api.sliplane.app
WIQ_CLIENT_ID=...
WIQ_CLIENT_SECRET=...
```

`app/windiq/` wraps the generated code with a small facade that handles the
client-credentials token exchange (`POST /auth/token`), token caching and refresh:

```python
from app.windiq import WindIQClient

client = WindIQClient()          # loads WIQ_* from the environment / .env
site = await client.site()       # typed model
page = await client.measurements(limit=100)

while page.next_cursor:          # cursor pagination
    page = await client.measurements(limit=100, cursor=page.next_cursor)
```
```
