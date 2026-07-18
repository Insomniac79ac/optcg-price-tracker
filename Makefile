.PHONY: help dev-up dev-down test-api test-worker migrate seed import-watchlist \
	refresh-yuyutei-dry refresh-yuyutei-live logs-api logs-worker logs-beat check-secrets \
	smoke-test prod-build prod-up prod-down prod-logs prod-migrate prod-smoke prod-verify \
	prod-backup prod-db-backup prod-db-restore prod-db-backup-prune prod-db-backup-prune-apply \
	release-check final-audit

# Override on the command line, e.g. `make import-watchlist WATCHLIST=path/to.csv`
WATCHLIST ?= data/watchlists/opcg_watchlist.csv

# Release/build metadata for prod-build - see docs/release_checklist.md and
# app/core/version.py (GET /version, GET /health, GET /admin/release-status).
# Recomputed fresh on every `make prod-build` invocation, not cached, so each
# build's ${GIT_COMMIT}/${BUILD_TIME} reflect what was actually checked out
# at build time. Override GIT_COMMIT/BUILD_TIME/APP_VERSION on the command
# line if you need a specific value instead (e.g. reproducing an old build).
GIT_COMMIT ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)
BUILD_TIME ?= $(shell date -u +%Y-%m-%dT%H:%M:%SZ)
APP_VERSION ?= $(shell cat VERSION 2>/dev/null || echo 0.0.0-unknown)

# All prod-* targets read the same production env file - see
# docs/deployment.md. Compose does NOT auto-load a file not literally named
# `.env`, so every prod-* target below passes --env-file explicitly.
PROD_COMPOSE = docker compose -f docker-compose.prod.yml --env-file .env.production

help:
	@echo "make dev-up               - start the local dev stack (docker compose up -d)"
	@echo "make dev-down             - stop the local dev stack"
	@echo "make test-api             - run the API test suite"
	@echo "make test-worker          - run the worker test suite"
	@echo "make migrate              - apply database migrations (alembic upgrade head)"
	@echo "make seed                 - seed reference data (sources table)"
	@echo "make import-watchlist     - import the card watchlist CSV (WATCHLIST=path/to.csv)"
	@echo "make refresh-yuyutei-dry  - dry-run a Yuyu-Tei price refresh"
	@echo "make refresh-yuyutei-live - run a real Yuyu-Tei price refresh"
	@echo "make logs-api             - tail api logs"
	@echo "make logs-worker          - tail worker logs"
	@echo "make logs-beat            - tail beat logs"
	@echo "make check-secrets        - fail if git is tracking any real .env file"
	@echo "make smoke-test           - verify a running (dev) stack is healthy (ADMIN_TOKEN required)"
	@echo "make release-check        - pre-release readiness check - see docs/release_checklist.md"
	@echo "make final-audit          - final production readiness audit - fails fast (SKIP_TESTS=true to skip pytest)"
	@echo ""
	@echo "Production (docker-compose.prod.yml + .env.production) - see docs/deployment.md:"
	@echo "make prod-build           - build the production images (tags GIT_COMMIT/BUILD_TIME/APP_VERSION)"
	@echo "make prod-up              - start the production stack"
	@echo "make prod-down            - stop the production stack"
	@echo "make prod-logs            - tail all production service logs"
	@echo "make prod-migrate         - apply database migrations against production"
	@echo "make prod-smoke           - run scripts/prod_smoke_test.sh (ADMIN_TOKEN optional - gates admin checks)"
	@echo "make prod-verify          - pre-deploy sanity check (config/secrets/build, no real secrets needed)"
	@echo "make prod-backup          - pg_dump the production database to ./opcg-backup-<timestamp>.dump"
	@echo "make prod-db-backup       - gzipped pg_dump to data/backups/db/ (scripts/db_backup.sh)"
	@echo "make prod-db-restore      - restore a backup (BACKUP=<path> CONFIRM=RESTORE required)"
	@echo "make prod-db-backup-prune - dry-run: show which old backups would be deleted (keeps newest 14)"
	@echo "make prod-db-backup-prune-apply - actually delete old backups beyond the retention count"

dev-up:
	docker compose up -d

dev-down:
	docker compose down

test-api:
	cd services/api && python3 -m pytest

test-worker:
	cd services/worker && python3 -m pytest

migrate:
	docker compose exec api alembic upgrade head

seed:
	docker compose exec api python -m app.seed

import-watchlist:
	docker compose exec api python -m app.import_watchlist $(WATCHLIST)

refresh-yuyutei-dry:
	docker compose exec worker python -m worker.jobs.refresh_prices --source yuyutei --dry-run

refresh-yuyutei-live:
	docker compose exec worker python -m worker.jobs.refresh_prices --source yuyutei

logs-api:
	docker compose logs -f api

logs-worker:
	docker compose logs -f worker

logs-beat:
	docker compose logs -f beat

check-secrets:
	./scripts/check_secrets.sh

smoke-test:
	./scripts/smoke_test.sh

release-check:
	./scripts/release_check.sh

final-audit:
	./scripts/final_audit.sh

# --- Production (docker-compose.prod.yml) -----------------------------------

prod-build:
	GIT_COMMIT=$(GIT_COMMIT) BUILD_TIME=$(BUILD_TIME) APP_VERSION=$(APP_VERSION) $(PROD_COMPOSE) build
	@echo "Built version $(APP_VERSION) (commit $(GIT_COMMIT), built $(BUILD_TIME))"

prod-up:
	$(PROD_COMPOSE) up -d

prod-down:
	$(PROD_COMPOSE) down

prod-logs:
	$(PROD_COMPOSE) logs -f

prod-migrate:
	$(PROD_COMPOSE) exec api alembic upgrade head

prod-smoke:
	./scripts/prod_smoke_test.sh

prod-verify:
	./scripts/prod_verify.sh

# pg_dump's custom format (-Fc) is compressed and lets pg_restore do
# selective/parallel restores - see "Restore Postgres" in docs/operations.md.
prod-backup:
	$(PROD_COMPOSE) exec postgres sh -c 'pg_dump -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -Fc -f /tmp/opcg-backup.dump'
	$(PROD_COMPOSE) cp postgres:/tmp/opcg-backup.dump ./opcg-backup-$$(date +%Y%m%d-%H%M%S).dump

# --- Automated DB backup/restore/retention (scripts/db_*.sh) ----------------
# See "Database backup and restore drill" in docs/operations.md.

prod-db-backup:
	./scripts/db_backup.sh

# Requires both BACKUP (the file to restore) and CONFIRM=RESTORE (a second,
# make-level confirmation on top of the script's own CONFIRM_RESTORE check)
# - prints usage and refuses to run without both.
prod-db-restore:
	@if [ -z "$(BACKUP)" ] || [ "$(CONFIRM)" != "RESTORE" ]; then \
		echo "Usage: make prod-db-restore BACKUP=<path-to-backup.sql.gz> CONFIRM=RESTORE"; \
		exit 1; \
	fi
	CONFIRM_RESTORE=RESTORE ./scripts/db_restore.sh $(BACKUP)

prod-db-backup-prune:
	./scripts/db_backup_prune.sh

prod-db-backup-prune-apply:
	./scripts/db_backup_prune.sh --apply
