.PHONY: install test integration check build demo

install:
	uv sync --all-extras

test:
	uv run --no-sync pytest

integration:
	uv run --no-sync pytest tests/integration -m integration -rs

check:
	uv run --no-sync ruff check .
	uv run --no-sync ruff format --check .
	sh scripts/check_no_internal_refs.sh

build:
	uv build

demo:
	uv run --no-sync python -m examples.sqlite_mirror.demo demo.db
