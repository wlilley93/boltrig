# Boltrig developer + operator targets.
#
# The Python targets prefer a local virtualenv at .venv (create it with
#   python -m venv .venv && .venv/bin/pip install -e ".[durable,inference]" \
#       && .venv/bin/pip install pytest pytest-asyncio aiosqlite ruff
# ). The container targets use docker compose with .env + manifest.yaml.

PY ?= .venv/bin/python
COMPOSE ?= docker compose
PG_USER ?= boltrig
PG_DB ?= boltrig
BACKUP_DIR ?= ./backups
BACKUP ?= $(BACKUP_DIR)/boltrig.dump

.DEFAULT_GOAL := help
.PHONY: help up down logs test lint smoke invariants migrate secure-up backup restore

help: ## List the available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "} {printf "  %-12s %s\n", $$1, $$2}'

up: ## Build + start the whole stack (add ARGS="--profile local" for on-box inference)
	$(COMPOSE) up -d --build $(ARGS)

secure-up: ## Start with the TLS / encrypted-at-rest overlay (deploy/compose.secure.yml)
	$(COMPOSE) -f docker-compose.yml -f deploy/compose.secure.yml up -d --build $(ARGS)

down: ## Stop the stack (keep the postgres volume)
	$(COMPOSE) down

logs: ## Tail logs for every service (SERVICE=kernel to scope it)
	$(COMPOSE) logs -f $(SERVICE)

test: ## Run the test suite (set BOLTRIG_TEST_DATABASE_URL to also run the Postgres tests)
	$(PY) -m pytest -q

lint: ## Run ruff if it is installed (no-op otherwise)
	@$(PY) -m ruff --version >/dev/null 2>&1 && $(PY) -m ruff check boltrig scripts \
		|| echo "ruff not installed; skipping lint"

smoke: ## Offline, in-process smoke test of the kernel guarantees (no docker)
	$(PY) scripts/smoke.py

invariants: ## The K-29/K-30 binding gate: every claimed invariant must have a test
	$(PY) scripts/check_invariants.py

migrate: ## Apply database migrations (alembic). schema.sql is the source of truth.
	$(PY) -m alembic upgrade head

backup: ## Dump durable state to $(BACKUP) (pg_dump custom format). See docs/backup-restore.md
	@mkdir -p $(BACKUP_DIR)
	$(COMPOSE) exec -T postgres pg_dump -U $(PG_USER) -d $(PG_DB) -Fc > $(BACKUP)
	@echo "backup written to $(BACKUP)"

restore: ## Restore durable state from $(BACKUP) (drops + recreates objects)
	$(COMPOSE) exec -T postgres pg_restore -U $(PG_USER) -d $(PG_DB) --clean --if-exists < $(BACKUP)
	@echo "restored from $(BACKUP)"
