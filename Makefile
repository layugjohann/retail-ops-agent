.PHONY: check lint format-check typecheck test format dashboard

check: lint format-check typecheck test

lint:
	uv run ruff check .

format-check:
	uv run ruff format --check .

typecheck:
	uv run pyright

test:
	uv run pytest

format:
	uv run ruff format .
	uv run ruff check --fix .

dashboard:
	uv run streamlit run dashboard/app.py
