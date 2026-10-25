import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse

VERSION = "0.1.0"

app = FastAPI(
    title="WindIQ API",
    version=VERSION,
    # Docs live under /api so nginx proxies them straight through
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


@app.get("/api/health")
async def health() -> JSONResponse:
    """Liveness/readiness probe used by the Docker healthcheck and the UI."""
    return JSONResponse(
        {"status": "ok", "service": "windiq-backend", "version": VERSION}
    )
