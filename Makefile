.PHONY: check lint format-check typecheck test format dashboard evals record deploy

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

# Golden Scenarios against real free-tier models (needs keys in .env.local). Not part of check.
# Pass options through ARGS, e.g. make evals ARGS="--tag quarantine --no-judge".
evals:
	uv run --env-file .env.local python -m retail_ops_agent.evals $(ARGS)

# Record Ops Days for Replay Mode into src/retail_ops_agent/recordings/. Uses free-tier keys from
# .env.local when present, else the offline scripted model. Pass options through ARGS, e.g.
# make record ARGS="--only 01-defect-day".
record:
	uv run $(if $(wildcard .env.local),--env-file .env.local,) python -m retail_ops_agent.replay $(ARGS)

# Interactive wizard for deploying the dashboard to Streamlit Community Cloud.
deploy:
	uv run python -m retail_ops_agent.deploy_wizard
