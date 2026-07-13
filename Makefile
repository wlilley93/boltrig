# Boltrig developer + operator targets.
#
# The Python targets prefer a local virtualenv at .venv (create it with
#   python -m venv .venv && \
#     .venv/bin/python -m pip install --require-hashes -r requirements-dev-lock.txt
# ). The container targets use docker compose with .env + manifest.yaml.

PY ?= .venv/bin/python
# Absolute interpreter for the Playwright e2e webServer (it cds into ui/ first, so
# a relative PY would break). A PY that contains a slash is a path: absolutise it
# lexically so a venv symlink is preserved (never readlink -f, that would follow
# the venv to the base interpreter and lose the boltrig install). A bare PY (CI
# passes PY=python) is a PATH command: resolve it with command -v, already absolute.
ifeq (,$(findstring /,$(PY)))
E2E_PYTHON := $(shell command -v $(PY))
else
E2E_PYTHON := $(abspath $(PY))
endif
COVERAGE_MIN ?= 75
PLAYWRIGHT_INSTALL_ARGS ?= chromium
COMPOSE ?= docker compose
COMPOSE_VALIDATE_ENV ?= .env.example
COMPOSE_VALIDATE_POSTGRES_PASSWORD ?= boltrig-compose-validation-only
GITLEAKS_IMAGE ?= zricethezav/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f
ACTIONLINT_IMAGE ?= rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667
PG_USER ?= boltrig
PG_DB ?= boltrig
BACKUP_DIR ?= ./backups
BACKUP ?= $(BACKUP_DIR)/boltrig.dump

.DEFAULT_GOAL := help
.PHONY: help up down logs test lint structure typecheck check python-quality ui-install ui-quality site-install site-quality ui-e2e compose-validate doctor-fixture migration-parity python-audit sast secret-scan actionlint security-source quality live-check lockfile-policy dependency-audit smoke invariants doctor migrate secure-up backup backup-schedule restore

help: ## List the available targets
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
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

lint: ## Run ruff over the Python source, scripts, and tests
	$(PY) -m ruff check boltrig scripts tests

structure: ## Enforce Python file/function size limits and expiring debt ratchets
	$(PY) scripts/check_structure.py

typecheck: ## Module-by-module strict mypy gate (see [tool.mypy])
	$(PY) -m mypy

check: invariants lint structure typecheck test ## Run the local Python gates CI enforces

python-quality: invariants lint structure typecheck ## Run Python tests on Postgres with coverage enforcement
	scripts/with_test_postgres.sh $(PY) -m pytest -q \
		--cov=boltrig --cov-report=term:skip-covered --cov-report=xml \
		--cov-fail-under=$(COVERAGE_MIN)

ui-install: lockfile-policy ## Install the UI from its frozen pnpm lockfile
	cd ui && corepack enable && pnpm install --frozen-lockfile --ignore-scripts
	cd ui && pnpm rebuild esbuild

ui-quality: ui-install ## Audit, typecheck, test with coverage, and build the UI
	cd ui && pnpm audit --audit-level=high
	cd ui && pnpm run typecheck
	cd ui && pnpm run test:coverage
	cd ui && pnpm run build

site-install: lockfile-policy ## Install the site from its frozen pnpm lockfile
	cd site && corepack enable && pnpm install --frozen-lockfile --ignore-scripts
	cd site && pnpm rebuild esbuild

site-quality: site-install ## Audit, lint, test with coverage, and build the site
	cd site && pnpm audit --audit-level=high
	cd site && pnpm run lint:strict
	cd site && pnpm run test:coverage
	cd site && pnpm run build

ui-e2e: ui-install ## Run Chromium Playwright against the built UI and real in-memory kernel
	cd ui && pnpm exec playwright install $(PLAYWRIGHT_INSTALL_ARGS)
	@set -- $$($(PY) -c 'import socket; sockets = [socket.socket() for _ in range(2)]; [item.bind(("127.0.0.1", 0)) for item in sockets]; print(*(item.getsockname()[1] for item in sockets))'); \
		cd ui && \
		BOLTRIG_E2E_PYTHON=$(E2E_PYTHON) \
		BOLTRIG_E2E_KERNEL_PORT=$$1 \
		BOLTRIG_E2E_UI_PORT=$$2 \
		pnpm exec playwright test

compose-validate: ## Validate base and secure Compose configurations
	BOLTRIG_ENV_FILE=$(COMPOSE_VALIDATE_ENV) \
		POSTGRES_PASSWORD=$(COMPOSE_VALIDATE_POSTGRES_PASSWORD) \
		$(COMPOSE) -f docker-compose.yml config --quiet
	BOLTRIG_ENV_FILE=$(COMPOSE_VALIDATE_ENV) \
		POSTGRES_PASSWORD=$(COMPOSE_VALIDATE_POSTGRES_PASSWORD) \
		$(COMPOSE) -f docker-compose.yml -f deploy/compose.secure.yml config --quiet

doctor-fixture: ## Prove the secure production-doctor fixture has no failures
	$(PY) -m pytest -q tests/unit/test_doctor.py::test_production_doctor_has_no_failures_for_secure_posture

migration-parity: ## Compare Alembic head with schema.sql on disposable PostgreSQL
	scripts/with_test_postgres.sh $(PY) -m pytest -q tests/integration/test_migration_parity.py

python-audit: ## Audit every shipped Python dependency graph
	$(PY) -m pip_audit --strict --progress-spinner off --require-hashes \
		-r requirements-lock.txt
	$(PY) -m pip install --dry-run --no-deps --require-hashes \
		-r deploy/browser-cli-requirements.txt
	$(PY) -m pip_audit --strict --progress-spinner off --no-deps --disable-pip \
		-r deploy/browser-cli-requirements.txt
	$(PY) -m pip_audit --strict --progress-spinner off \
		-r services/pi_sidecar/requirements.txt

sast: ## Run the blocking medium/high-confidence Python SAST gate
	$(PY) -m bandit -q -r boltrig -ll -ii

secret-scan: ## Scan complete Git history with narrow test-fixture exceptions
	docker run --rm --volume "$(CURDIR):/repo:ro" $(GITLEAKS_IMAGE) \
		git /repo --config /repo/.gitleaks.toml --redact=100 --no-banner

actionlint: ## Lint GitHub Actions with the pinned actionlint image
	docker run --rm --volume "$(CURDIR):/repo:ro" --workdir /repo \
		$(ACTIONLINT_IMAGE) -color

security-source: python-audit sast secret-scan actionlint ## Run SCA, SAST, secret, and workflow gates

quality: python-quality ui-quality site-quality compose-validate doctor-fixture ui-e2e migration-parity security-source ## Run the complete local release gate

lockfile-policy: ## Enforce pnpm as the only JavaScript package manager
	@locks="$$(git ls-files '*yarn.lock' '*package-lock.json')"; \
		test -z "$$locks" || { echo "unsupported JavaScript lockfiles:"; echo "$$locks"; exit 1; }
	@test -f ui/pnpm-lock.yaml -a -f site/pnpm-lock.yaml

dependency-audit: lockfile-policy ## Fail on high/critical UI and site dependency advisories
	cd ui && pnpm audit --audit-level=high
	cd site && pnpm audit --audit-level=high

live-check: ## Run opt-in live integration legs; requires services and credentials
	BOLTRIG_LIVE_SMOKE=1 $(PY) -m pytest -q -rs \
		tests/adapters/test_live_smoke.py \
		tests/integration/test_hatchet_live.py \
		tests/integration/test_cognee_engine.py \
		tests/integration/test_pgvector_engine.py \
		tests/integration/test_rls.py

smoke: ## Offline, in-process smoke test of the kernel guarantees (no docker)
	$(PY) scripts/smoke.py

invariants: ## The K-29/K-30 binding gate: every claimed invariant must have a test
	$(PY) scripts/check_invariants.py

doctor: ## Static readiness checks (ARGS="--production" for deploy-blocking posture)
	$(PY) -m boltrig.api.cli doctor --env-file .env --manifest manifest.yaml $(ARGS)

migrate: ## Apply the authoritative ordered Alembic migration chain
	$(PY) -m alembic upgrade head

backup: ## Dump durable state to $(BACKUP) (pg_dump custom format). See docs/backup-restore.md
	@mkdir -p $(BACKUP_DIR)
	$(COMPOSE) exec -T postgres pg_dump -U $(PG_USER) -d $(PG_DB) -Fc > $(BACKUP)
	@echo "backup written to $(BACKUP)"

backup-schedule: ## Start the scheduled off-box backup sidecar (M10; needs BACKUP_* in .env)
	$(COMPOSE) --profile backup up -d backup
	@echo "backup sidecar started (loops scripts/backup.sh; see docs/backup-restore.md)"

restore: ## Restore durable state from $(BACKUP) (drops + recreates objects)
	$(COMPOSE) exec -T postgres pg_restore -U $(PG_USER) -d $(PG_DB) --clean --if-exists < $(BACKUP)
	@echo "restored from $(BACKUP)"
