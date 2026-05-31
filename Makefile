.PHONY: install demo test lint typecheck quality

install:
	uv sync --extra dev

demo:
	uv run quant-research demo

test:
	uv run pytest

lint:
	uv run ruff check .

typecheck:
	uv run mypy src

quality: lint typecheck test
