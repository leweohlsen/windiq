from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api import router as api_router
from app.db.engine import ping as db_ping
from app.db.engine import SessionLocal
from app.db.repo import ingest_health
from app.worker import broker

load_dotenv()

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """The API only produces tasks: connect the broker, no listening loop."""
    await broker.startup()
    try:
        yield
    finally:
        await broker.shutdown()


app = FastAPI(
    title="WindIQ API",
    version=VERSION,
    # Docs live under /api so nginx proxies them straight through
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.include_router(api_router)


@app.get("/api/health")
async def health() -> JSONResponse:
    """Liveness/readiness probe used by the Docker healthcheck and the UI."""
    db_ok = False
    db_detail: dict = {}
    try:
        db_ok = await db_ping()
        if db_ok:
            async with SessionLocal() as s:
                db_detail = await ingest_health(s)
    except Exception as exc:  # health must report, never crash
        db_detail = {"error": str(exc)} if db_ok else {"error": _brief(exc)}

    ingest_db = db_detail.get("last_run") or {}
    last_data_update = db_detail.get("last_data_update")
    status = "ok" if db_ok else "degraded"

    return JSONResponse(
        {
            "status": status,
            "service": "windiq-backend",
            "version": VERSION,
            "database": {"ok": db_ok, **_jsonable(db_detail)},
            "time": datetime.now(timezone.utc).isoformat(),
            "last_run_status": ingest_db.get("status"),
            "last_data_update": _iso(last_data_update),
        }
    )


def _brief(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _jsonable(value):
    """Row values are datetimes/timedeltas; JSON only takes ISO strings/numbers."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return round(value.total_seconds())
    return value


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value
