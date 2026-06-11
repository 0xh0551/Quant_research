.PHONY: install setup lang demo test lint typecheck quality web

install:
	uv sync --extra dev

# Full first-run setup: installs deps and prompts for the dashboard language.
setup:
	./scripts/setup.sh

# Re-pick the default dashboard language without reinstalling.
lang:
	QR_DEFAULT_LANG= ./scripts/setup.sh

demo:
	uv run quant-research demo

test:
	uv run pytest

lint:
	uv run ruff check .

typecheck:
	uv run mypy src

quality: lint typecheck test

web:
	uv run uvicorn src.web.app:app --host 0.0.0.0 --port 8000 --reload
