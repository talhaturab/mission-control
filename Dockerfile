# One image for all four processes. The command decides which one a container runs.
FROM python:3.12-slim
WORKDIR /app

# uv installs the exact versions from uv.lock, and nothing from the dev group.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY static ./static

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

# Default: the web process. Workers and the ticker override this in compose or ECS:
#   python -m app.worker
#   python -m app.ticker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
