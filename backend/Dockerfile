# Pin uv, Python, and the base image digest for reproducible builds.
FROM ghcr.io/astral-sh/uv:0.13.5-python3.12-trixie-slim@sha256:9b8477a5f2e2f96fa99eaecb7680c1c4c9f527926430f3b630bfb2c3641f8f20

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app

WORKDIR /app

# Lockfile first for better layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --home-dir /home/app app
ENV HOME=/home/app

COPY --chown=app:app app ./app

EXPOSE 8000

USER app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
