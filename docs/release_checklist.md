# Release checklist

A repeatable checklist for cutting and shipping a release of the OPTCG price tracker. Pairs with
`scripts/release_check.sh` (`make release-check`), which automates most of section A, and with
`GET /admin/release-status` / the `/admin/release-status` web page, which automates most of
section D. See `docs/deployment.md` for the full deploy reference and `docs/operations.md` for
day-to-day commands - this document is the checklist that ties them together for a single release.

## A. Pre-release

- [ ] `git status` is clean (no uncommitted changes on the branch being released).
- [ ] All tests pass: `make test-api` and `make test-worker` (or `RUN_TESTS=true
      scripts/release_check.sh` / `RUN_TESTS=true make prod-verify`, which run both).
- [ ] Secret check passes: `make check-secrets` (`scripts/check_secrets.sh`) - fails if git is
      tracking a real `.env`-style file.
- [ ] Production compose config passes: `docker compose -f docker-compose.prod.yml config` and, if
      you're using a reverse proxy, `docker compose -f docker-compose.prod.yml -f
      docker-compose.prod.private.yml config` (see [section 13](deployment.md#13-production-deployment-behind-https-reverse-proxy)
      in docs/deployment.md).
- [ ] A fresh backup exists: `make prod-db-backup` (or `make prod-backup` for a `pg_dump -Fc`) -
      see [Database backup and restore drill](operations.md#database-backup-and-restore-drill).
      Confirm it with `GET /admin/db-backups` or the `/admin/backup` page.
- [ ] Any new Alembic migration has been reviewed (schema change, backfill behavior, whether it's
      reversible, whether it locks a large table).
- [ ] Env validation is checked: `curl -H "X-Admin-Token: $ADMIN_TOKEN"
      http://localhost:8000/admin/env-check` reports `"status": "ok"` (or only expected warnings) -
      see [section 1a](deployment.md#1a-production-required-env-vars--startup-validation) in
      docs/deployment.md.
- [ ] `CHANGELOG.md` is updated with this release's changes (see section 5 of the parent task /
      `CHANGELOG.md` itself for the format).

`scripts/release_check.sh` (`make release-check`) automates the git-status, secret-check, and
compose-config parts of this section in one command - see section "Release script" below.

## B. Build

- [ ] `make prod-build` - builds the production images and tags them with `GIT_COMMIT`
      (`git rev-parse --short HEAD`), `BUILD_TIME` (current UTC timestamp), and `APP_VERSION` (the
      repo-root `VERSION` file) as Docker build args - see "Docker build metadata" below.
- [ ] Record the git commit that was built (`git rev-parse --short HEAD`, or read it back from
      `GET /version` / `GET /admin/release-status` after deploying).
- [ ] Record the version (`cat VERSION`, or `GET /version`).
- [ ] Record the build time (printed by `make prod-build`, or `GET /version`).

Keep these three values somewhere durable (a deploy log, the release's git tag message, a
changelog entry) - they're what section E (Rollback) below needs to identify what to roll back to.

## C. Deploy

- [ ] `make prod-up` - starts (or restarts) the production stack.
- [ ] `make prod-migrate` - applies any pending Alembic migrations (`alembic upgrade head`).
- [ ] Check logs: `make prod-logs` (or a single service, e.g. `docker compose -f
      docker-compose.prod.yml --env-file .env.production logs -f api`) - watch for startup errors
      for at least the first minute.
- [ ] Run the smoke test: `ADMIN_TOKEN=<token> make prod-smoke` (`scripts/prod_smoke_test.sh`) -
      don't consider the deploy live until this passes.

## D. Post-deploy validation

- [ ] `/dashboard` loads.
- [ ] `/collection` loads.
- [ ] `/market/report` loads.
- [ ] `/admin/system-check` passes (`status: "ok"`, or only expected warnings).
- [ ] `/admin/logs` has no new critical errors since the deploy started.
- [ ] Market workflow dry-run works: `POST /admin/actions/run-market-workflow` with `"dry_run":
      true` (or the "Run market workflow" action on `/admin/actions` with Dry run checked) - see
      [Market workflow scheduling](operations.md#market-workflow-scheduling).
- [ ] Backup export works: `GET /admin/backup/export` (or the "Export" button on `/admin/backup`)
      returns a valid backup JSON.

`GET /admin/release-status` (and the `/admin/release-status` web page, linked from the admin nav,
`/admin/system-check`, and `/admin/actions`) is the fastest way to check most of this section in
one call: version/git commit/build time/app env, the latest system check, the latest market
workflow run, the latest backup, the latest error, and a `release_readiness` summary
(`system_check_status`, `critical_logs_last_24h`, `latest_backup_available`).

## E. Rollback

If validation in section D fails, or something else goes wrong shortly after deploying:

1. **Identify the previous commit/image** - the git commit and version recorded in section B for
   the last known-good release (or `git log` if that wasn't recorded).
2. **Stop services**: `make prod-down` (or stop just the misbehaving one - see
   [Rollback](deployment.md#rollback) in docs/deployment.md).
3. **Restore the database backup** taken in section A, *only if* this deploy's migration changed
   data or schema in a way the previous code version can't handle - see [Restore
   Postgres](operations.md#restore-postgres) / `make prod-db-restore
   BACKUP=<path> CONFIRM=RESTORE`. Skip this step if the deploy didn't include a migration.
4. **Redeploy the previous version**: `git checkout <previous-commit-or-tag>`, then `make
   prod-build && make prod-up`.
5. **Run migrations if required** - only if you're rolling back to a commit that expects a
   *different* (usually earlier) schema than what's currently applied: `make prod-migrate` runs
   whatever `alembic upgrade head` resolves to for the checked-out code, which is a no-op if the
   schema already matches.
6. **Smoke test**: `ADMIN_TOKEN=<token> make prod-smoke` - don't consider the rollback done until
   this passes.
7. **Check logs**: `make prod-logs` - confirm no new errors after the rollback.

## F. Emergency notes

Fast references for the most common "something's actively wrong" responses - see the linked
sections in docs/deployment.md / docs/operations.md for the full procedure of each.

- **Rotate `ADMIN_TOKEN`** if it was ever exposed (committed to git, logged, leaked) - see [How to
  rotate ADMIN_TOKEN](deployment.md#1e-how-to-rotate-admin_token).
- **Disable the market workflow** - set `MARKET_WORKFLOW_ENABLED=false` in `.env.production` and
  restart `beat` (`docker compose -f docker-compose.prod.yml --env-file .env.production restart
  beat`) - see [Market workflow scheduling](operations.md#market-workflow-scheduling).
- **Disable the Telegram digest** without disabling the whole workflow - set
  `MARKET_WORKFLOW_SEND_TELEGRAM=false` (same restart as above), or unset
  `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` entirely - see [Telegram
  config](deployment.md#1b-telegram-config).
- **Disable rate limits temporarily** if legitimate traffic is being 429'd (or to rule rate
  limiting out while debugging) - set `RATE_LIMIT_ENABLED=false` in `.env.production` and restart
  `api`. Re-enable once done - see [Temporarily disabling rate
  limits](operations.md#check-rate-limit-status) in docs/operations.md.
- **Restore a DB backup** - `make prod-db-restore BACKUP=<path> CONFIRM=RESTORE` - see [Database
  backup and restore drill](operations.md#database-backup-and-restore-drill).

## Docker build metadata

`GIT_COMMIT`, `BUILD_TIME`, and `APP_VERSION` are Docker build args on `services/api/Dockerfile`,
`services/worker/Dockerfile`, and `apps/web/Dockerfile` - baked in as env vars at build time (not
overridable at runtime without a rebuild), so `GET /version`/`GET /health`/`GET
/admin/release-status`/`GET /api/version` always report exactly what was built, regardless of
which `.env.production` values happen to be set on a given container. `make prod-build` computes
all three automatically (`git rev-parse --short HEAD`, a UTC timestamp, and the repo-root
`VERSION` file) and passes them through to `docker compose build` - no manual steps needed for a
normal release. Override `GIT_COMMIT`/`BUILD_TIME`/`APP_VERSION` on the `make prod-build` command
line only if you need a specific value instead (e.g. reproducing an old build byte-for-byte).

## Release script

`scripts/release_check.sh` (`make release-check`) automates the mechanical parts of section A:
prints the current branch/commit/`VERSION`, fails if `git status` isn't clean (unless
`ALLOW_DIRTY=true`), runs `scripts/check_secrets.sh`, and validates both
`docker-compose.prod.yml` and the `docker-compose.prod.yml` + `docker-compose.prod.private.yml`
combination with `docker compose ... config`. Set `RUN_TESTS=true` to also run the backend and
worker test suites. See the script's own header comment for the full env var reference.
