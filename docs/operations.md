# Operations

How to run, watch, back up and deploy the stack. For the failure modes behind
these procedures see [resilience.md](resilience.md).

## Services

| Service | Role |
| --- | --- |
| `db` | PostgreSQL 17: storage, and the task broker |
| `migrate` | one-shot `alembic upgrade head`; the other services wait for it |
| `backend` | FastAPI: `/api/*`, produces ingest tasks, never consumes them |
| `worker` | taskiq worker: runs the startup sweep and backfill, then syncs |
| `scheduler` | taskiq scheduler: sends `periodic_sync` every 5 minutes |
| `frontend` | nginx: serves the dashboard and proxies `/api/*` to `backend` |

## Configuration

The backend, worker and scheduler read these variables. The local template is
`backend/.env.example`.

| Variable | Purpose |
| --- | --- |
| `WIQ_API_BASE_URL` | WindIQ API base URL |
| `WIQ_CLIENT_ID`, `WIQ_CLIENT_SECRET` | WindIQ credentials; missing values fail loudly when the client is created |
| `WIQ_MAX_ATTEMPTS`, `WIQ_RETRY_BACKOFF`, `WIQ_RETRY_MAX_WAIT` | retry tuning (defaults: 4 attempts, 8 s cap) |
| `DATABASE_URL` | set by Compose; `backend/.env` needs it only for running outside Docker |
| `POSTGRES_PASSWORD` | database password (default `windiq`) |

The base `docker-compose.yml` does not pass the `WIQ_*` variables to the containers.
Locally, use the dev overlay, which loads them from `backend/.env`.

## Day-to-day

```sh
docker compose ps                           # status of all services
docker compose logs -f worker               # one service
docker compose down                         # stop; keeps the windiq-pgdata volume
docker compose exec db psql -U windiq       # database shell
```

Health: `GET /api/health` reports database reachability, the last ingest run and
the age of the newest measurement. It returns `503` with `status: "degraded"` when the
database is down. The dashboard flags data older than 3 hours.

### Tracing an ingest run

Every ingest cycle has a run ID (`run=<id>`) that appears in the logs of the API,
worker and scheduler.

```sh
docker compose logs -f backend worker | grep run=<id>
```

Cron runs get their ID inside the worker, so they only show up in the worker log.

### "Sync now" while the worker is down

`POST /api/ingest/run` returns `{queued: true}` even when no worker is running. Such a
task is never executed. The worker clears these leftovers at its next start. The
"queued…" badge on the dashboard clears only when a newer run appears. After the worker
returns, that happens at the next cron tick, within 5 minutes.

## Backups

```sh
docker compose exec db pg_dump -U windiq -Fc windiq > windiq-$(date +%F).dump
docker compose exec -T db pg_restore -U windiq -d windiq --clean < windiq-<date>.dump
```

Restore into a running stack only after stopping `backend`, `worker` and `scheduler`.

## Deploy

- **CI** (`.github/workflows/ci.yml`) runs on pull requests and pushes to `main`. It typechecks and
  builds the frontend, runs the backend tests against a real Postgres 17, and builds both images.
- **Deploy** (`.github/workflows/deploy.yml`) runs on pushes to `main`. It pushes
  `:latest` and `:sha-<commit>` images to GHCR, then calls the Coolify deploy webhook.
  The webhook is configured through the `COOLIFY_WEBHOOK_URL` secret.
- Production runs `docker-compose.prod.yml` on the VPS with `pull_policy: always`.
  This matters: a plain `docker compose up -d` would otherwise reuse a cached `:latest`.
- **Rollback:** pin the image tag in `docker-compose.prod.yml` to a `sha-<commit>` tag and
  run `docker compose up -d`.
- Deploys never touch the `windiq-pgdata` volume. Schema changes go through Alembic.
  Keep migrations away from `taskiq_messages`, which taskiq-pg manages.
