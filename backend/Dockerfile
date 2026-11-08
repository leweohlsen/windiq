# Pin uv, Python, and the base image digest for reproducible builds.
FROM ghcr.io/astral-sh/uv:0.13.7-python3.12-trixie-slim@sha256:d4a752dd52f42e0c508bb0b6a912f15922bb32e42f66af30671c3fdc0d759f21

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
