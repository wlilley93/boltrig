# Nankle developer + operator targets.
#
# The Python targets prefer a local virtualenv at .venv (create it with
#   python -m venv .venv && .venv/bin/pip install -e ".[durable,inference]" \
#       && .venv/bin/pip install pytest pytest-asyncio aiosqlite ruff
# ). The container targets use docker compose with .env + manifest.yaml.

PY ?= .venv/bin/python
COMPOSE ?= docker compose

.DEFAULT_GOAL := help
.PHONY: help up down logs test lint smoke invariants migrate

help: ## List the available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "} {printf "  %-12s %s\n", $$1, $$2}'

up: ## Build + start the whole stack (add ARGS="--profile local" for on-box inference)
	$(COMPOSE) up -d --build $(ARGS)

down: ## Stop the stack (keep the postgres volume)
	$(COMPOSE) down

logs: ## Tail logs for every service (SERVICE=kernel to scope it)
	$(COMPOSE) logs -f $(SERVICE)

test: ## Run the test suite (the 34 kernel + security tests)
	$(PY) -m pytest -q

lint: ## Run ruff if it is installed (no-op otherwise)
	@$(PY) -m ruff --version >/dev/null 2>&1 && $(PY) -m ruff check nankle scripts \
		|| echo "ruff not installed; skipping lint"

smoke: ## Offline, in-process smoke test of the kernel guarantees (no docker)
	$(PY) scripts/smoke.py

invariants: ## The K-29/K-30 binding gate: every claimed invariant must have a test
	$(PY) scripts/check_invariants.py

migrate: ## Apply database migrations (alembic). schema.sql is the source of truth.
	$(PY) -m alembic upgrade head
