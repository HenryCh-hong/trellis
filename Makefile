# Trellis — dev commands
# Requires: PostgreSQL 16 running locally, Node 20+, uv.

API := apps/api
WEB := apps/web
PY  := $(API)/.venv/bin/python
DB  := opportunity_agent

.PHONY: help setup db api web dev seed reseed test lint fmt typecheck migrate revision clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "};{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install backend + frontend dependencies and create the database
	cd $(API) && uv venv --python 3.12 && uv pip install -e ".[dev]"
	cd $(WEB) && npm install
	@psql -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='$(DB)'" | grep -q 1 \
		|| psql -d postgres -c "CREATE DATABASE $(DB)"
	cd $(API) && .venv/bin/alembic upgrade head

db: ## Start PostgreSQL (Homebrew)
	brew services start postgresql@16

api: ## Run the API on :8000
	cd $(API) && .venv/bin/uvicorn app.main:app --reload --port 8000

web: ## Run the web app on :3000
	cd $(WEB) && npm run dev

dev: ## Run API and web together
	@$(MAKE) -j2 api web

seed: ## Load the real harvested Stanford corpus into Postgres
	cd $(API) && .venv/bin/python -m app.seed

reseed: ## Wipe the loaded corpus and load it again
	cd $(API) && .venv/bin/python -m app.seed --reset

test: ## Run the backend test suite
	cd $(API) && .venv/bin/python -m pytest -q

lint: ## Lint both sides
	cd $(API) && .venv/bin/ruff check app tests
	cd $(WEB) && npx eslint src --max-warnings 0

fmt: ## Format Python
	cd $(API) && .venv/bin/ruff format app tests && .venv/bin/ruff check --fix app tests

typecheck: ## Typecheck the frontend
	cd $(WEB) && npx tsc --noEmit

migrate: ## Apply migrations
	cd $(API) && .venv/bin/alembic upgrade head

revision: ## Autogenerate a migration: make revision m="add x"
	cd $(API) && .venv/bin/alembic revision --autogenerate -m "$(m)"

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf $(WEB)/.next
