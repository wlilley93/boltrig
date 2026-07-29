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
# Floor raised 75 -> 82 (2026-07-17): actual is 84.43%, so 75 let coverage
# silently regress ~9 points. 82 locks in the gain with a small honest headroom.
COVERAGE_MIN ?= 82
PLAYWRIGHT_INSTALL_ARGS ?= chromium
COMPOSE ?= docker compose
COMPOSE_VALIDATE_ENV ?= .env.example
COMPOSE_VALIDATE_POSTGRES_PASSWORD ?= boltrig-compose-validation-only
GITLEAKS_IMAGE ?= zricethezav/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f
ACTIONLINT_IMAGE ?= rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667
TRIVY_CONFIG_IMAGE ?= aquasec/trivy:0.72.0@sha256:cffe3f5161a47a6823fbd23d985795b3ed72a4c806da4c4df16266c02accdd6f
PG_USER ?= boltrig
PG_DB ?= boltrig
BACKUP_DIR ?= ./backups
BACKUP ?= $(BACKUP_DIR)/boltrig.dump
RELEASE_ENV ?= .env
RELEASE_IMAGES_ENV ?= boltrig-images.env
RELEASE_VALIDATE_IMAGES_ENV ?= tests/fixtures/release-images.env
RELEASE_PROFILES ?= --profile backup

.DEFAULT_GOAL := help
.PHONY: help gate-status relock fleet-drift-all up down logs test lint architecture structure codex-protocol unwired-claims reachability prose-references commit-trailers refresh-canon-citations refresh-opbox-surface fleet-drift gate-coverage health-claims order-directives typecheck check python-quality ui-install ui-quality site-install site-quality ui-e2e compose-validate release-validate release-up doctor-fixture migration-parity python-audit sast iac-scan secret-scan actionlint security-source quality live-check lockfile-policy dependency-audit smoke invariants doctor migrate secure-up backup backup-schedule restore

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

# WITHOUT BOLTRIG_TEST_DATABASE_URL this skips ~156 tests, including the RLS
# fence-drift guard, migration parity, tenancy and store parity - they run only
# against a real Postgres. For a long time CI was the ONLY place that happened,
# which is how a Postgres-only foreign-key defect survived a green local suite.
# Point it at a THROWAWAY database, never one a running stack serves from; these
# tests write. On the dev box:
#   psql -h <pg> -U boltrig -d postgres -c 'CREATE DATABASE boltrig_test;'
#   make test BOLTRIG_TEST_DATABASE_URL="$$(scripts/test-dsn.sh)"
# scripts/test-dsn.sh DERIVES the address from Docker rather than remembering it.
# The dev container publishes no host port and its compose-network IP changes on
# every restart, which has twice produced ~137 connection errors that read like
# real failures. Do not reach for 127.0.0.1:5432 instead: on a box like this one
# that is a DIFFERENT Postgres, and pointing the store suite at the wrong server
# is the kind of mistake that only fails loudly by luck.
test: ## Run the test suite (set BOLTRIG_TEST_DATABASE_URL to also run the Postgres tests)
	$(PY) -m pytest -q

lint: ## Run ruff over the Python source, scripts, and tests
# The version check is the gate, and the lint is what it protects.
#
# `$(PY) -m ruff` runs whatever happens to be in the venv, and on 2026-07-27 that had drifted
# to 0.16.0 while requirements-dev-lock.txt pins 0.15.21. The newer ruff invented 800 findings
# in files nobody had touched, so `make lint` failed on a MAIN that CI reported green. A local
# gate that fails on clean main is worse than no local gate: it teaches everyone to skip the
# step, and then it is not there on the day it would have caught something.
#
# The drift is dangerous in both directions. A newer ruff cries wolf; an older one would pass
# code CI rejects, and you would only learn that from a red CI run after pushing.
	@LOCKED=$$(grep -oP '^ruff==\K[0-9.]+' requirements-dev-lock.txt | head -1); \
	HAVE=$$($(PY) -m ruff --version 2>/dev/null | awk '{print $$2}'); \
	if [ -z "$$HAVE" ]; then \
	  echo "make lint: no ruff in $(PY). Install the dev lock: uv pip sync requirements-dev-lock.txt"; exit 1; \
	elif [ "$$HAVE" != "$$LOCKED" ]; then \
	  echo "make lint: ruff $$HAVE is installed, requirements-dev-lock.txt pins $$LOCKED."; \
	  echo "           This is NOT the linter CI runs, so its verdict does not mean what it looks like."; \
	  echo "           Fix:  uv pip sync requirements-dev-lock.txt"; \
	  echo "           Or run the pinned one directly:  uvx ruff@$$LOCKED check boltrig scripts tests"; \
	  exit 1; \
	fi
	$(PY) -m ruff check boltrig scripts tests

architecture: ## Enforce inward-only thin-orchestration dependencies
	$(PY) scripts/check_architecture.py

structure: ## Enforce Python file/function size limits and expiring debt ratchets
	$(PY) scripts/check_structure.py

codex-protocol: ## Verify the exact checked-in stable Codex App Server protocol pin
	$(PY) scripts/check_codex_protocol.py

unwired-claims: ## Fail when the record names a mechanism no production path constructs
	$(PY) scripts/check_unwired_claims.py

reachability: ## Reachability is TRANSITIVE: report every function unreachable from every root
	$(PY) scripts/check_reachability.py

prose-references: ## Every path, test id, make target, env var and order citation in prose must resolve
	$(PY) scripts/check_prose_references.py

# Re-vendor the canon citator. Run deliberately when a NEW canon ruling is cited
# here; the gate resolves against the committed file, never against a checkout on
# one machine, which is how the first cut passed locally and reddened CI.
CANON_REPO ?= $(HOME)/Projects/vibe-justice-system
OPBOX_REPO ?= $(HOME)/Projects/opbox-prod
DRIFT_HOST ?= jellytot-prod
DRIFT_PROJECT ?= boltrig
DRIFT_COMPOSE ?= $(HOME)/Projects/boltrig-main/docker-compose.yml
DRIFT_OVERLAY ?= $(HOME)/Projects/opbox-prod/boltrig-tenants/boltrig-io.override.yml
refresh-canon-citations: ## Re-vendor .vjs/canon-citations.txt from the canon register
	$(PY) scripts/refresh_canon_citations.py --canon $(CANON_REPO)

refresh-opbox-surface: ## Re-vendor tests/fixtures/opbox-model-surface.txt from the opbox schema
	$(PY) scripts/refresh_opbox_surface.py --opbox $(OPBOX_REPO)

user-authority: ## Does EVERY active user resolve to usable authority? (needs a tenant DSN; not a CI gate)
	@# Fail-closed is right; fail-SILENT is the bug. A user in no org/workspace
	@# resolves to the empty grant set, and a role absent from chat.skills_by_role
	@# loads no skills - so their turns complete, apologise, and record nothing
	@# wrong. Found exactly that on a live client. DSN=... MANIFEST=... make user-authority
	$(PY) scripts/check_user_authority.py

fleet-drift: ## Is what is RUNNING what we pinned? (needs a box; not a CI gate)
	$(PY) scripts/check_fleet_drift.py --host $(DRIFT_HOST) --project $(DRIFT_PROJECT) \
		--compose $(DRIFT_COMPOSE) --overlay $(DRIFT_OVERLAY)

# Both prod tenants in one command. `fleet-drift` alone only ever asked about
# app.boltrig.io, so the CLIENT tenant was never checked by the default
# invocation - a drift tool that answers for one of two boxes reads as answering
# for the fleet. Fails on the FIRST tenant that drifts, deliberately: a partial
# answer here is the thing being fixed.
fleet-drift-all: ## Drift + bind-mount staleness for EVERY prod tenant
	@$(MAKE) --no-print-directory fleet-drift \
		DRIFT_PROJECT=boltrig \
		DRIFT_OVERLAY=$(HOME)/Projects/opbox-prod/boltrig-tenants/boltrig-io.override.yml
	@echo
	@$(MAKE) --no-print-directory fleet-drift \
		DRIFT_PROJECT=cv-boltrig \
		DRIFT_OVERLAY=$(HOME)/Projects/opbox-prod/boltrig-tenants/cv/compose.override.yml

override-locks: ## A security override that did not reach the lock is not an override
	$(PY) scripts/check_override_locks.py

claim-inventory: ## Rebuild docs/claim-inventory.tsv from the sources (Tier 0)
	$(PY) scripts/build_claim_inventory.py

claims: ## The Tier 0 ratchet: the inventory is current and the residue has not grown
	$(PY) scripts/check_claim_inventory.py

gate-coverage: ## Every compose manifest is validated and every `quality` component runs in CI
	$(PY) scripts/check_gate_coverage.py

health-claims: ## No service may report healthy while unable to serve
	$(PY) scripts/check_health_claims.py

order-directives: ## Every binding court directive is bound to a test or recorded
	$(PY) scripts/check_order_directives.py

commit-trailers: ## Every path cited in a commit Refs:/See: trailer existed when cited
	$(PY) scripts/check_commit_trailers.py
	$(PY) scripts/check_commit_trailers_selftest.py

typecheck: ## Module-by-module strict mypy gate (see [tool.mypy])
	$(PY) -m mypy

gate-status: ## Is the gate on the default branch actually green right now?
	@./scripts/gate-status.sh

check: invariants lint architecture structure codex-protocol unwired-claims reachability typecheck test ## Run the local Python gates CI enforces

python-quality: invariants lint architecture structure codex-protocol unwired-claims reachability prose-references commit-trailers gate-coverage health-claims order-directives claims override-locks typecheck ## Run Python tests on Postgres with coverage override-locks typecheck
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
	# The dev / in-process / opbox-link overlays. They reached NO validation step
	# until 2026-07-26, while compose.dev.yml is what genesis.sh and dev-up.sh
	# actually run - a broken one would have been found by a developer, not a gate.
	# They use !override and !reset, so only `docker compose config` can read them.
	BOLTRIG_ENV_FILE=$(COMPOSE_VALIDATE_ENV) \
		POSTGRES_PASSWORD=$(COMPOSE_VALIDATE_POSTGRES_PASSWORD) \
		$(COMPOSE) -f docker-compose.yml -f deploy/compose.dev.yml config --quiet
	BOLTRIG_ENV_FILE=$(COMPOSE_VALIDATE_ENV) \
		POSTGRES_PASSWORD=$(COMPOSE_VALIDATE_POSTGRES_PASSWORD) \
		$(COMPOSE) -f docker-compose.yml -f deploy/compose.inprocess.yml config --quiet
	BOLTRIG_ENV_FILE=$(COMPOSE_VALIDATE_ENV) \
		POSTGRES_PASSWORD=$(COMPOSE_VALIDATE_POSTGRES_PASSWORD) \
		$(COMPOSE) -f docker-compose.yml -f deploy/compose.opbox-link.yml config --quiet
	$(PY) scripts/validate_release_images.py $(RELEASE_VALIDATE_IMAGES_ENV)
	BOLTRIG_ENV_FILE=$(COMPOSE_VALIDATE_ENV) \
		POSTGRES_PASSWORD=$(COMPOSE_VALIDATE_POSTGRES_PASSWORD) \
		$(COMPOSE) --env-file $(COMPOSE_VALIDATE_ENV) \
		--profile backup --profile local --profile legacy \
		--env-file $(RELEASE_VALIDATE_IMAGES_ENV) \
		-f docker-compose.yml -f deploy/compose.release.yml config --format json \
		| $(PY) scripts/validate_release_compose.py
	BOLTRIG_ENV_FILE=$(COMPOSE_VALIDATE_ENV) \
		POSTGRES_PASSWORD=$(COMPOSE_VALIDATE_POSTGRES_PASSWORD) \
		$(COMPOSE) --env-file $(COMPOSE_VALIDATE_ENV) \
		--profile backup --profile local --profile legacy \
		--env-file $(RELEASE_VALIDATE_IMAGES_ENV) \
		-f docker-compose.yml -f deploy/compose.release.yml \
		-f deploy/compose.secure.yml config --format json \
		| $(PY) scripts/validate_release_compose.py --secure

release-validate: ## Validate a downloaded digest-pinned release environment
	$(PY) scripts/validate_release_images.py $(RELEASE_IMAGES_ENV)
	BOLTRIG_ENV_FILE=$(RELEASE_ENV) \
		$(COMPOSE) --env-file $(RELEASE_ENV) --env-file $(RELEASE_IMAGES_ENV) \
		$(RELEASE_PROFILES) -f docker-compose.yml -f deploy/compose.release.yml \
		-f deploy/compose.secure.yml config --format json \
		| $(PY) scripts/validate_release_compose.py --secure

release-up: release-validate ## Pull and start signed release images (secure + backup)
	BOLTRIG_ENV_FILE=$(RELEASE_ENV) \
		$(COMPOSE) --env-file $(RELEASE_ENV) --env-file $(RELEASE_IMAGES_ENV) \
		$(RELEASE_PROFILES) -f docker-compose.yml -f deploy/compose.release.yml \
		-f deploy/compose.secure.yml pull
	BOLTRIG_ENV_FILE=$(RELEASE_ENV) \
		$(COMPOSE) --env-file $(RELEASE_ENV) --env-file $(RELEASE_IMAGES_ENV) \
		$(RELEASE_PROFILES) -f docker-compose.yml -f deploy/compose.release.yml \
		-f deploy/compose.secure.yml up -d --no-build

doctor-fixture: ## Prove the secure production-doctor fixture has no failures
	$(PY) -m pytest -q tests/unit/test_doctor.py::test_production_doctor_has_no_failures_for_secure_posture

migration-parity: ## Compare Alembic head with schema.sql on disposable PostgreSQL
	scripts/with_test_postgres.sh $(PY) -m pytest -q tests/integration/test_migration_parity.py

python-audit: ## Audit every shipped Python dependency graph
	# Via the wrapper, not pip_audit directly: it enforces the EXPIRY on
	# docs/security/accepted-advisories.json (dependency-policy item 6), so an
	# accepted advisory cannot outlive its review, and it prints what is being
	# suppressed so a green audit still says what it is not checking.
	$(PY) scripts/python_audit.py requirements-lock.txt
	$(PY) -m pip install --dry-run --no-deps --require-hashes \
		-r deploy/browser-cli-requirements.txt
	$(PY) -m pip_audit --strict --progress-spinner off --no-deps --disable-pip \
		-r deploy/browser-cli-requirements.txt

sast: ## Run the blocking medium/high-confidence Python SAST gate
	$(PY) -m bandit -q -r boltrig -ll -ii

iac-scan: ## Run pinned, offline high/critical IaC misconfiguration checks
	docker run --rm --volume "$(CURDIR):/repo:ro" --workdir /repo \
		$(TRIVY_CONFIG_IMAGE) config --skip-check-update --skip-version-check \
		--ignorefile /repo/.trivyignore.yaml --skip-dirs .git --skip-dirs .venv \
		--skip-dirs .claude --severity HIGH,CRITICAL --exit-code 1 /repo

secret-scan: ## Scan complete Git history with narrow test-fixture exceptions
	docker run --rm --volume "$(CURDIR):/repo:ro" $(GITLEAKS_IMAGE) \
		git /repo --config /repo/.gitleaks.toml --redact=100 --no-banner

actionlint: ## Lint GitHub Actions with the pinned actionlint image
	docker run --rm --volume "$(CURDIR):/repo:ro" --workdir /repo \
		$(ACTIONLINT_IMAGE) -color

security-source: python-audit sast iac-scan secret-scan actionlint ## Run SCA, SAST, IaC, secret, and workflow gates

quality: python-quality ui-quality site-quality compose-validate doctor-fixture ui-e2e migration-parity security-source ## Run the complete local release gate

# The ONE npm-locked package, and why it is not pnpm. The whatsapp bridge depends
# on `baileys`, a GIT-HOSTED package that both runs build scripts on install and
# itself pulls `libsignal` over git. pnpm 11 refuses each by default (allowBuilds,
# blockExoticSubdeps), so converting it would mean switching OFF two supply-chain
# protections to satisfy a lockfile-FORMAT rule - strictly worse than leaving this
# one package on npm. Exempt, not forgotten: it ships behind the `channels`
# profile and receives NO `pnpm audit` coverage, so audit it by hand whenever the
# bridge is next touched.
LOCKFILE_POLICY_EXEMPT := services/channel_gateway/whatsapp_bridge/package-lock.json

# UPGRADE= is empty by default, which REUSES the existing pins: `uv pip compile`
# reads its own output file and holds what is already there, so a bare `make relock`
# is a no-op on an up-to-date tree and only re-solves what a source change forces.
# `make relock UPGRADE=--upgrade` takes every available upgrade AS ONE RESOLUTION,
# which is the difference that matters: dependabot edits a compiled lock line by
# line (every pin in a uv output is flat and looks direct to it) and has twice
# produced a file pip refuses outright - pydantic-core against the pydantic that
# pins it exactly, then protobuf against its sibling. A lock is DERIVED. Change the
# constraints, re-solve, commit the solution; never patch the solution.
UPGRADE ?=
relock: ## Recompile every Python lock from its source (UPGRADE=--upgrade to take upgrades)
	uv pip compile pyproject.toml --extra durable --extra inference \
		--extra sql-adapters --extra cognee --generate-hashes $(UPGRADE) -o requirements-lock.txt
	uv pip compile pyproject.toml --extra durable --extra inference \
		--extra sql-adapters --group dev --generate-hashes $(UPGRADE) -o requirements-dev-lock.txt
	uv pip compile deploy/browser-cli-requirements.in \
		--overrides deploy/browser-cli-overrides.txt --generate-hashes \
		--python-platform linux $(UPGRADE) -o deploy/browser-cli-requirements.txt

lockfile-policy: ## Enforce pnpm as the JavaScript package manager (one recorded exemption)
	@locks="$$(git ls-files '*yarn.lock' '*package-lock.json' | grep -vxF '$(LOCKFILE_POLICY_EXEMPT)' || true)"; \
		test -z "$$locks" || { echo "unsupported JavaScript lockfiles:"; echo "$$locks"; exit 1; }
	@test -f '$(LOCKFILE_POLICY_EXEMPT)' || { \
		echo "stale exemption: $(LOCKFILE_POLICY_EXEMPT) no longer exists;"; \
		echo "drop it from LOCKFILE_POLICY_EXEMPT in the Makefile"; exit 1; }
	@test -f ui/pnpm-lock.yaml -a -f site/pnpm-lock.yaml -a -f sdks/node/pnpm-lock.yaml
	@# Runs BEFORE the frozen install, deliberately: a shadowed exclusion entry
	@# surfaces as ERR_PNPM_MINIMUM_RELEASE_AGE_VIOLATION, which reads as "the
	@# exemption is being ignored" rather than "your second entry disabled your
	@# first". That misreading cost most of 2026-07-28. Refuse the list here, where
	@# the message can name the actual cause.
	@# `python3`, NOT $(PY). $(PY) defaults to .venv/bin/python, which does not
	@# exist in the ui-build or site-build-test-lint jobs - they never set up
	@# Python, so make exits 127 (command not found) and the whole target dies
	@# before it checks anything. I shipped exactly that and turned
	@# site-build-test-lint red. The stdlib is all this script needs.
	@python3 scripts/check-release-age-exclusions.py

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
