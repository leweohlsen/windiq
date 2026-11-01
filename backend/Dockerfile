# Pin uv, Python, and the base image digest for reproducible builds.
FROM ghcr.io/astral-sh/uv:0.13.6-python3.12-trixie-slim@sha256:bf889bda77474aa50c351caf1538b855ef2b7a30add45f26ca50dcb6ade06402

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app

WORKDIR /app

# Lockfile first for better layer caching
COPY pyproject.toml uv.lock ./
COPY packages ./packages
RUN uv sync --locked --no-install-project --no-dev

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --home-dir /home/app app
ENV HOME=/home/app

COPY --chown=app:app app ./app
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic

EXPOSE 8000

USER app

# Run migrations before serving; idempotent and cheap after the first boot.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
