.PHONY: install dev web worker ticker test lint
install: ; uv sync
dev:     ; uv run python -m app.dev
web:     ; uv run uvicorn app.main:app --reload --port 8000
worker:  ; uv run python -m app.worker
ticker:  ; TICK_FOREVER=1 uv run python -m app.ticker
test:    ; uv run pytest -q
lint:    ; uv run ruff check . && uv run ruff format --check .
