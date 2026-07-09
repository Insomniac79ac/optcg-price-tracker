.PHONY: help dev-up dev-down test-api test-worker migrate seed import-watchlist \
	refresh-yuyutei-dry refresh-yuyutei-live logs-api logs-worker logs-beat check-secrets

# Override on the command line, e.g. `make import-watchlist WATCHLIST=path/to.csv`
WATCHLIST ?= data/watchlists/opcg_watchlist.csv

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
