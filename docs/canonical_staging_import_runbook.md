# Canonical staging Bandai catalogue import — release runbook

**Status: not executed.** This is the sequence the 4D-1 execution gate was
built to support. Nothing in it has been run against canonical staging.

The gate itself is described in
`services/api/app/import_frozen_bandai_to_canonical_staging.py`. The short
version: the generic importer (`app.apply_canonical_print_import`) refuses
`--environment staging` and always will, because it also accepts an arbitrary
`--database-url` and "staging" would then be a label rather than a fact. The
dedicated runner has no `--database-url` at all — it resolves the connection
from the Railway `staging` environment and proves it with the fail-closed
fingerprints in `scripts/staging_db_read_check.py` before the engine sees a
session.

## Credentials

**Prefer the dedicated helpers. Most steps need no connection URL at all.**

`scripts/staging_db_read_check.py` (steps 3, 7, 11) and
`app.import_frozen_bandai_to_canonical_staging` (steps 8, 10) each open,
verify and close their own tunnel. They capture the Railway CLI's stdout and
stderr internally, parse out only the `URL:` line, and print only the
environment, service, redacted `host:port/database` and alembic revision. Run
those steps as written and no credential is ever produced.

Only **steps 4, 5 and 6** — backup, restore-verify and migration — genuinely
need a connection URL, because they drive third-party tools (`pg_dump`,
`pg_restore`, `alembic`) that take one. Step 0 below is the credential-safe
way to obtain it. The rules for those three steps:

- **Never paste a URL from terminal output.** `railway connect` prints the
  password, the full DSN, or both; copying from the scrollback puts it in
  your clipboard and your shell history.
- Capture it by reading the tunnel's own stdout into a shell variable, and
  never `echo`, `printf`, `tee` or `cat` that variable.
- Pass it to child processes **through the environment**, never as an
  argument — an argument is visible in `ps` to every process on the host.
- `set +o history` before you start and `set -o history` after. Never
  `set -x` / `bash -x`: tracing prints every expansion, including this one.
- Never write it to a file, a `.env`, a note, or a committed document.
- `unset` it when you are done, and close the tunnel.

### Step 0 — obtain the URL without displaying it

```bash
set +o history
umask 077

# Reads only the URL line; every other line the CLI prints - including
# "Password:" and "Connection string:" - is consumed and discarded.
exec 3< <(railway connect Postgres --environment staging --tunnel-only 2>&1)
STAGING_URL=""
while IFS= read -r -u 3 line; do
  case "$line" in
    "URL: "*) STAGING_URL="${line#URL: }"; break ;;
  esac
done
[ -n "$STAGING_URL" ] || { echo "FAIL: no tunnel URL reported" >&2; }
export PGURL="$STAGING_URL"          # for the container steps below
echo "tunnel up: ${STAGING_URL##*@}" # host:port/database only - safe to show
```

The tunnel stays open on file descriptor 3 for as long as this shell lives.
Close it in step 13.

## The sequence

### 1. Verify branch and commit

```bash
git -C . status --short
git -C . rev-parse --abbrev-ref HEAD
git -C . rev-parse HEAD
git -C . log -1 --oneline
```

The working tree must be clean and the commit must be the reviewed one. The
runner reads the expected alembic head from this checkout, so the wrong
commit is a refusal in step 8, not a surprise in step 10.

### 2. Open a canonical staging tunnel

```bash
railway status          # read-only: confirms which project is linked
```

**Do not run `railway link`.** Every command in this runbook targets the
environment and service explicitly — `railway connect Postgres --environment
staging --tunnel-only` — so nothing here depends on, or changes, the
checkout's persistent link state. Relinking would silently repoint every
other Railway command you run afterwards.

No long-lived tunnel is opened by hand for the verified steps: 3, 7, 8, 10
and 11 each open their own fresh tunnel and close it, because a cached
`DATABASE_PUBLIC_URL` is what resolved to the wrong (empty) database on
2026-08-21. Steps 4–6 share the one from step 0.

### 3. Read-only staging fingerprint

```bash
python scripts/staging_db_read_check.py
```

Must print `RESULT: PASS`. This is the same authority the runner uses; running
it first means a target problem is found before any of the slower steps.

### 4. Fresh pg_dump

The staging server is PostgreSQL 18 and the local client is 16, so the dump
runs inside a matching image. `PGURL` comes from step 0 and is passed by
**name only** (`-e PGURL`), so the value never appears in the `docker` command
line; the single-quoted `sh -c` means it is expanded inside the container, not
by your shell:

```bash
mkdir -p data/backups/staging
docker run --rm --network host -e PGURL \
  -v "$PWD/data/backups/staging:/out" postgres:18-alpine \
  sh -c 'pg_dump "$PGURL" -Fc -f /out/staging-preimport-$(date +%Y%m%d-%H%M%S).dump'
ls -lh data/backups/staging/
```

### 5. Restore-verify the backup

A dump that has never been restored is not a backup. Restore it into a
throwaway local database and compare:

The verification database is local and disposable, so its password is not a
secret worth protecting — but it is still passed by environment rather than
argument, so the same habit holds everywhere:

```bash
export VERIFY_URL="postgresql://postgres:verify@localhost:5545/postgres"
docker run -d --name staging-restore-check -e POSTGRES_PASSWORD=verify \
  -p 5545:5432 postgres:18-alpine
docker run --rm --network host -e VERIFY_URL \
  -v "$PWD/data/backups/staging:/out" postgres:18-alpine \
  sh -c 'pg_restore -d "$VERIFY_URL" --clean --if-exists /out/<dumpfile>'
DATABASE_URL="$VERIFY_URL" python scripts/staging_db_read_check.py --url-env DATABASE_URL
```

The restored copy must pass the same fingerprints. Then compare row counts
against staging with `ORDER BY id` checksums — string ordering is
collation-dependent and would differ between two servers holding identical
rows. Drop the container afterwards.

### 6. Apply pending migrations

```bash
DATABASE_URL="$STAGING_URL" APP_ENV=staging bash scripts/staging_migrate.sh
```

The URL is in the child's environment, not its argument list. Do not add
`set -x` to debug this step — the trace would print the URL.

### 7. Verify the final migration head

```bash
python scripts/staging_db_read_check.py     # fingerprint D must PASS
cd services/api && python -m alembic heads  # must be the single expected head
```

The runner refuses if staging's revision is not this checkout's head, so this
step is a check, not a formality.

### 8. Dry-run the canonical import

```bash
cd services/api
python -m app.import_frozen_bandai_to_canonical_staging | tee \
  ../../docs/evidence/canonical-staging-import-dryrun.txt
```

Read-only at the server: the session sets `read_only` on connect, so a write
would be rejected by PostgreSQL rather than trusted not to happen.

### 9. Review the expected counts

From the dry-run report, read and agree:

- `pre_counts` — what staging holds now
- `eligible_plans`, `card_prints_created`, `canonical_cards_created`,
  `products_created`
- `skipped_ineligible`, `skipped_needs_review`, `canonical_baseline.excluded`
- `rarity_null_codes` — the codes whose canonical rarity the catalogue does
  not settle
- `snapshot_identity` and `db_revision` — pinned into step 10

### 10. Explicit confirmed apply

```bash
cd services/api
python -m app.import_frozen_bandai_to_canonical_staging \
  --apply \
  --confirm IMPORT_FROZEN_BANDAI_TO_CANONICAL_STAGING \
  --expect-snapshot <snapshot_identity from step 9> \
  --expect-counts '<pre_counts JSON from step 9>' \
  | tee ../../docs/evidence/canonical-staging-import-apply.txt
```

A typo in `--confirm` refuses before anything is connected to. There is no
`--force` and no `--yes`. The `--expect-*` values are what make a stale review
a refusal rather than a surprise.

### 11. Post-import invariants

```bash
python scripts/staging_db_read_check.py
```

Then, from the apply report: `post_counts` minus `pre_counts` equals the
created counts; `source_card_mappings`, `price_observations` and
`market_index_snapshots` are unchanged (the engine asserts this before it
commits); no duplicate active verified identity.

### 12. API and frontend regression

```bash
bash scripts/staging_smoke_test.sh
bash scripts/web_route_smoke.sh
```

Then a visual pass over Discover / Cards / Card detail on the staging alias,
per `docs/ui/ATLAS_LOOP.md`.

### 13. Close the tunnel

```bash
exec 3<&-                       # closes the step 0 tunnel
unset STAGING_URL PGURL VERIFY_URL
docker rm -f staging-restore-check
set -o history
```

The verified steps close their own tunnels in a `finally` block whether the
run committed, refused or raised, so nothing from 3, 7, 8, 10 or 11 is left
behind. Confirm no `railway connect` process survives.

## If anything disagrees

Refuse and stop. There is no fallback to another database, and no step in
this runbook may be reordered to get past a failing check — every one of them
is also enforced in code, so skipping one here does not skip it there.
