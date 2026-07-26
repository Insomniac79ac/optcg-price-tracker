# Staging dataset

Documents the small, representative catalogue/pricing dataset loaded into the Railway staging
database on 2026-07-26, so the deployed prototype (Vercel frontend + Railway API) can be exercised
with real requests instead of an empty catalogue. Pairs with
[docs/staging_deployment.md](staging_deployment.md) (architecture) and
[docs/staging_checklist.md](staging_checklist.md) (deploy runbook - see its 2026-07-26 entry for
the checklist-level summary of this same work).

This is additive data-loading only - no scraping (live or otherwise), no invented prices, no
schema/validation changes. `SCRAPING_MODE` remains `mock` throughout.

## 1. Dataset source

Two existing, already-reviewed mechanisms, run in this specific order:

1. **`python -m app.seed --demo-data`** (`services/api/app/seed.py`) - an existing, documented
   command. Seeds 10 cards explicitly labeled in its own source comment as "Sample/demo data only
   - not real catalog data" (`seed.py:13-17`), spanning sets OP01-OP05, rarities `L`/`SR`/`R`/`SEC`,
   variants `base`/`alt_art`, all `language=jp`. Also seeds 4 source mappings for 2 of those cards
   (`OP01-001`, `OP01-013`), using placeholder Yuyu-Tei/SNKRDUNK URLs that are **not** real
   listings (e.g. `https://yuyu-tei.jp/sell/opc/card/OP01-001`) - chosen because their
   `source_card_id` matches the only two keys present in the mock adapters' fixture JSON (see
   section 3).
2. **`python -m app.import_watchlist data/watchlists/opcg_watchlist.csv`** - imports the repo's
   existing real watchlist file: 6 rows, `manual_verified=true` on every row, genuine Yuyu-Tei
   product URLs and genuine-looking SNKRDUNK listing URLs (with real-shaped UUID query params),
   covering 2 card codes (`OP01-001` "Roronoa Zoro", `OP01-002` "Trafalgar Law"), both set `OP01`.
   This file was committed to the repo on 2026-07-10 (commit `d2b18d2`, "feat: add card catalog
   audit backend") as this feature's own reference data - not scraped or fabricated for this task.

**Why this order matters**: `app.seed.seed_demo_data`'s mapping step looks up a card by
`card_code` alone (`db.query(Card).filter_by(card_code=...).one_or_none()`, `seed.py:71`), with no
disambiguation by rarity/variant. If the watchlist import runs *first* and creates its own
`OP01-001` row, a subsequent `seed --demo-data` run would find **two** rows with `card_code=
"OP01-001"` (the demo one and the watchlist one) and crash with `MultipleResultsFound` inside the
mapping loop - after already flushing its 10 card rows, so the whole operation would then roll
back on session close (fails safe, but wastes a cycle and needs re-running). Running `seed
--demo-data` first, while `OP01-001` doesn't exist yet, avoids this entirely. `import_watchlist`'s
own card lookup uses `.first()` and includes `variant` in its filter, so it is not vulnerable to
the same issue and was safe to run second, and to re-run afterward for the idempotency check.

No other verified or fixture dataset exists in the repo big enough to reach the 20-50 card target
without fabricating anything - see section 6.

## 2. What was actually loaded

Rehearsed first against a disposable local Postgres 18 container (migrated to the exact same
Alembic head via the real `deploy/railway/api.Dockerfile` image), then repeated identically against
the real Railway staging database. Both runs produced identical counts.

- **12 canonical cards** (`cards` table), from a starting baseline of 0.
- **5 sets**: OP01 (7 cards), OP02 (2), OP03 (1), OP04 (1), OP05 (1).
- **5 rarities**: `L`, `SR`, `R`, `SEC` (all from the demo seed) and `Parallel` (from the real
  watchlist import).
- **3 variants**: `base`, `alt_art` (demo seed), `Leader` (watchlist import) - `OP01-001` itself
  exists as two distinct canonical rows (`L`/`base` from the demo seed, `Parallel`/`Leader` from
  the watchlist), which is the schema's own way of representing multiple prints/variants of one
  physical card, so this also satisfies "at least one card with multiple variants."
- **Language**: all 12 cards are `jp` - no verified or fixture English-language data exists in the
  repo to add without fabricating it.
- **16 source mappings** (`source_card_mappings`): 12 from the real watchlist import
  (`manual_verified=true`, `review_status=approved`), 4 from the demo seed
  (`manual_verified=false`, `review_status=approved` - the app's own default, not something this
  pass changed).
- **0 SNKRDUNK candidates** - none imported; no live SNKRDUNK collection occurred, per the task's
  data-integrity rules. The candidate review queue (`GET /snkrdunk/candidates`) is confirmed
  reachable and correctly empty (`200`, `"items": []`), not broken.

This is below the 20-50 card target in the task brief. That target could only be reached by either
inventing card metadata or fabricating "verified" Yuyu-Tei/SNKRDUNK source URLs for cards that
don't have any - both explicitly forbidden. 12 cards across 5 sets/5 rarities/3 variants was judged
the largest dataset obtainable from this repo's actual verified+documented sources without doing
either.

### Known, pre-existing data-shape quirk (not introduced by this pass)

The watchlist CSV's 4 `OP01-001` rows (Base, Parallel, Parallel, Parallel/Foil Stamping) and 2
`OP01-002` rows (Base, Parallel) all reuse the literal `variant` value `"Leader"` rather than a
distinct value per print/rarity. `import_watchlist.py`'s card-matching key is
`(card_code, variant, language)` - it does **not** include `rarity` - so all 4 `OP01-001` rows
collapse onto a single canonical card row (whichever row is processed last wins for scalar fields
like `name_en`/`rarity`/`image_url`), while all 4 distinct source URLs still get their own
`source_card_mappings` row pointing at that one collapsed card. This is why `GET
/cards/11/prices` returns 20 rows (4 mappings x up to 5 price points each from the shared
`OP01-001` mock fixture entry) instead of a cleaner 5 - every one of those price points is
legitimate (a real mapping, a real mock-fixture value, correctly attached to the correct canonical
card), just visually redundant. This is a characteristic of the existing watchlist file + importer
combination, not a bug introduced here, and not something this pass silently patched - doing so
would have meant either reinterpreting the "verified" CSV's `variant` column (risky, since the
task requires treating that file as authoritative as-is) or modifying `import_watchlist.py`'s
matching logic (out of scope - not requested, not touched). Flagged here for whoever next touches
either the watchlist file or the importer.

## 3. Mock price observations

Prices are the existing worker mock adapters' output (`services/worker/worker/adapters/
mock_yuyutei.py`, `mock_snkrdunk.py`), never real Yuyu-Tei/SNKRDUNK data - `SCRAPING_MODE=mock` the
entire time, and was never changed. Both adapters look up a fixture JSON keyed by
`source_card_id`:

- `services/worker/fixtures/yuyutei_sample.json` - only has keys `OP01-001` (sell 1200 / buy
  800 JPY, in stock) and `OP01-013` (sell 450 / buy 300 JPY, out of stock).
- `services/worker/fixtures/snkrdunk_sample.json` - only has keys `OP01-001` (floor 1500 JPY, 12
  listings, 2 historical `sold` prices at fixed timestamps) and `OP01-013` (floor 600 JPY, 3
  listings, no sold history).

Any mapping whose `source_card_id` isn't one of those two strings gets a `404`/empty parse with
zero observations - silently, by design, not an error. This repo's fixture files were **not**
extended in this pass (would have been a reasonable, low-risk follow-up, but was kept out of scope
to avoid changing more than the task asked for). Consequently:

- Only 3 of the 12 canonical cards can ever show a mock price under the current fixtures:
  `OP01-001` (both the demo `L`/`base` row and the watchlist `Parallel`/`Leader` row) and
  `OP01-013` (demo `SR`/`base`).
- `OP01-002` and the other 8 demo-only cards (`Nami`, `Usopp`, `Sanji`, `OP02-013` Trafalgar Law,
  `Nico Robin`, `Yamato`, `Shanks`, `Kaido`) will always show 0 prices unless the fixture JSON is
  extended in a future pass - confirmed via `GET /cards/12/prices` returning `[]` with `200`, not
  an error.

### Refresh run performed

Triggered via `POST /admin/actions/refresh-prices` (`{"source": "all", "limit": 20, "dry_run":
...}`) - a synchronous one-off Celery enqueue that only needs the `worker` service (confirmed
healthy), never `beat`. Sequence: dry run (preview) -> one real run -> a second dry run (to
confirm no retry/looping behavior without inserting duplicate data - see below for why a second
*real* run was deliberately not performed).

| | run 1 (preview) | run 2 (real) | run 3 (preview) |
|---|---|---|---|
| `run_id` | 1 | **2** | 3 |
| `dry_run` | true | **false** | true |
| `mappings_checked` | 16 | 16 | 16 |
| `snapshots_created` (raw, pre-parse) | 16 | 16 | 16 |
| `observations_parsed` | 28 | 28 | 28 |
| `observations_inserted` | 0 (rolled back) | **28** | 0 (rolled back) |
| `observations_skipped_duplicate` | 0 | 0 | 0 |
| `mappings_failed` | 0 | 0 | 0 |
| duration | ~125ms | ~150ms | ~99ms |

Raw snapshots are always persisted (and flushed) before parsing is attempted, structurally, not
just by convention (`refresh_prices.py` writes/flushes the `raw_snapshots` row before calling
`parse_snapshot`). All 16 mappings were attempted regardless of whether their `source_card_id` had
fixture data - the 4 mappings for `OP01-002` correctly parsed to 0 observations each and did not
count as failures.

**Why only one real run**: `price_observations` has no unique constraint and no active dedup check
in the current code (`refresh_prices.py` inserts every parsed observation unconditionally -
confirmed by reading the insert loop directly) - it's an intentional append-only time series, not
a bug. The mock `snkrdunk` fixture's `sold_prices` entries carry **fixed, hard-coded timestamps**
(`2026-07-01T00:00:00Z`, `2026-07-03T00:00:00Z`), not real-time ones. Running the real refresh a
second time would therefore insert byte-for-byte duplicate `sold` rows (same card, source,
price_type, price, and timestamp) with no dedup to catch it - not useful, and not something the
task's "bounded, one-time" instruction called for. The two dry runs (which fetch/parse but always
`db.rollback()` afterward) were used instead to confirm the job completes cleanly and doesn't
retry/loop on repeated invocation, without touching real data a second time.

## 4. Validation performed

All against the live deployment (`https://optcg-price-tracker-staging.up.railway.app`,
`https://optcg-price-tracker-staging.vercel.app`):

- `GET /cards` returns all 12 cards with correct fields.
- `GET /cards/{id}/prices` returns the correct observations per card - `[]` (200, not an error)
  for unmapped/unfixtured cards, populated correctly for the 3 that have fixture data. Currency is
  JPY throughout (`price_jpy`, an integer column - there is no separate currency field to get
  wrong). `price_type` correctly distinguishes `sell`/`buy` (yuyutei) from `floor`/`sold`
  (snkrdunk) - `sold` entries carry the mock fixture's fixed historical timestamps, `sell`/`buy`/
  `floor` carry the real refresh-run timestamp.
- `GET /admin/catalog-coverage`: `total_cards: 12`, `sets_count: 5`, `cards_with_yuyutei_mapping:
  4`, `cards_with_snkrdunk_mapping: 4`, `cards_without_any_mapping: 8` - matches the import exactly.
- `GET /admin/source-mappings/quality`: `total_mappings: 16`, correctly flags the 4 watchlist-
  imported `OP01-002` mappings as `active_without_recent_price` (true - no fixture data for that
  code) and the 4 demo mappings as `unverified_mapping` (true - `manual_verified=false` by design).
  No mapping is flagged as pointing at the wrong card (spot-checked the full mapping-to-card
  listing manually).
- `GET /admin/price-source-health`: reports `total_active_mappings: 16`,
  `mappings_with_recent_price: 12`, `missing_price_count: 4` (the 4 `OP01-002` mappings, correctly
  enumerated with `suggested_action: "run_refresh_or_review_mapping"`) - matches exactly.
- `GET /admin/refresh-runs`: shows all 3 runs (1 real, 2 preview) with correct stats.
- `GET /admin/system-check`: `status: "warning"` (was `critical` before any sources/cards
  existed) - `checks_passed: 29/33`, `critical: 0`. Every FK-integrity check
  (`source_mappings_valid_card_id`, `collection_items_valid_card_id`,
  `wishlist_items_valid_card_id`, `market_signal_events_valid_card_id`, etc.) passes, and
  `duplicate_cards` independently reports "No exact/likely duplicate cards detected" - the system's
  own duplicate-detection logic (used by the admin card-merge tooling) agrees with the manual
  analysis in section 2.
- `GET /snkrdunk/candidates`: `200`, `{"items": [], "total": 0}` - review queue reachable and
  correctly empty.
- CORS preflight from the exact Vercel origin still returns the correct
  `access-control-allow-origin`; an unrelated origin is still rejected. `/health` unaffected by the
  data load (`status: ok`, `database_connected: true`, `redis_connected: true`).
- `scripts/staging_smoke_test.sh` re-run with `STAGING_API_URL`, `STAGING_WEB_URL`, and
  `ADMIN_TOKEN` (injected via a `railway variables --kv` pipe, never displayed) - **passed in
  full**, including all 6 web-page checks (previously only API checks had real data behind them).
- Frontend pages (`/`, `/dashboard`, `/market/movers`, `/cards/1`, `/cards/11`, `/admin/catalog-
  ops`, `/admin/price-source-health`, `/admin/snkrdunk-candidates`) all return `200`; `/wishlist`
  and other protected routes still correctly redirect for an unauthenticated session (`307`), same
  as before any data existed. **Caveat**: this app's catalogue/price/card-detail pages are
  client-rendered (data is fetched in the browser after the initial HTML loads, not embedded in
  server-rendered markup) - no browser automation tool was available in this session, so the
  *data* was verified directly against the API the frontend calls (above), and the *page shell* was
  verified to load/return 200, but the final rendered DOM (e.g. "does the card name visually
  appear on the page") was not directly observed. Client-side search, set/rarity/language filter
  controls, and the command-palette (Ctrl/Cmd+K) are also browser-interaction-only and were not
  exercised this pass for the same reason - same caveat the checklist already carried for these
  before Vercel existed at all.
- Did not attempt Google sign-in (no credentials exist) and did not create any collection/wishlist
  records by bypassing auth.

## 5. How to repeat this import safely

```bash
# 1. Take a backup first (see docs/operations.md's backup/restore drill).
# 2. Seed reference data + demo cards (safe to re-run, upserts by identity):
railway run --service optcg-price-tracker python -m app.seed --demo-data
# 3. Import the real watchlist (safe to re-run, upserts by identity):
railway run --service optcg-price-tracker python -m app.import_watchlist \
  data/watchlists/opcg_watchlist.csv
```

If `railway run` can't reach `data/watchlists/` from inside the deployed `api` service (its
Docker image only copies `services/api/.`, not the repo-root `data/` directory - see
`deploy/railway/api.Dockerfile`), build the same image locally instead and mount the data
directory, connecting to `DATABASE_PUBLIC_URL` with a `+psycopg` scheme prefix:

```bash
docker build -f deploy/railway/api.Dockerfile -t opcg-api-local .
docker run --rm -e DATABASE_URL="postgresql+psycopg://<rest-of-DATABASE_PUBLIC_URL-after-postgresql://>" \
  opcg-api-local python -m app.seed --demo-data
docker run --rm -e DATABASE_URL="postgresql+psycopg://..." \
  -v "$(pwd)/data:/repo_data:ro" \
  opcg-api-local python -m app.import_watchlist /repo_data/watchlists/opcg_watchlist.csv
```

Do **not** run the real (`dry_run=false`) price refresh more than once without a reason - see
section 3 for why a repeat run duplicates the mock `sold` history rows.

## 6. How to remove only this staging fixture data

There's no single "unseed" command. To remove just what this pass added (not collection/wishlist
data a real staging user may have since created):

```sql
-- Remove the mock price observations and raw snapshots created by the refresh runs:
DELETE FROM price_observations WHERE raw_snapshot_id IN (SELECT id FROM raw_snapshots);
DELETE FROM raw_snapshots;
DELETE FROM price_refresh_runs;

-- Remove the demo + watchlist mappings and cards (cascades to their mappings):
DELETE FROM cards WHERE card_code IN (
  'OP01-001','OP01-013','OP01-024','OP01-034','OP01-041',
  'OP02-013','OP02-025','OP03-013','OP04-004','OP05-119','OP01-002'
);
```

Take a fresh backup first. This does not touch `sources` (`yuyutei`/`snkrdunk` are meant to exist
permanently) or any real user-created `collection_items`/`wishlist_items` rows (none existed at
the time of writing - `users: 0` at baseline).

## 7. Remaining data gaps

- Only 12 of the 20-50 targeted cards exist - no more verified/documented data source exists in
  the repo to safely go further (section 1/2).
- Only 3 of the 12 cards can ever show a mock price, because the mock fixture JSON only covers 2
  `source_card_id` values (section 3). Extending
  `services/worker/fixtures/{yuyutei,snkrdunk}_sample.json` with more synthetic entries (clearly
  still mock, still non-fabricated-as-real) would let more of the catalogue show prices, but was
  kept out of scope for this pass.
- No English-language (`language=en`) cards exist - no verified/fixture source has any.
- No SNKRDUNK candidates exist (by design - no live collection was performed).
- Google OAuth remains unconfigured - authenticated flows (collection, wishlist, grading, saved
  views under a real session) remain untested against this dataset.
- Beat remains blocked by the Railway free-plan resource provision limit - unaffected by this pass.
- Client-side-only UI behavior (search box, set/rarity/language filter controls, command palette)
  was not exercised - see the caveat in section 4.
