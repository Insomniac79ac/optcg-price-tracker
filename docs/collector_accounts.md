# Collector accounts (v1, API)

Status: **dark**. Built in collector-v1 session S3. Plan:
`docs/agent/plans/collector-v1/PLAN.md` (branch `plan/collector-v1`), sections B and C.

## Switch

`COLLECTOR_ACCOUNTS_ENABLED` on the Railway API service, read by
`services/api/app/accounts/config.py` on every request. Unset or anything other
than `1`/`true`/`yes`/`on` means off. While off, every `/me` route answers 404
before authentication, so no token is checked and no user row is created.
The flag is turned on in S5, not before.

The setting lives in `app/accounts/config.py`, not `app/settings.py`, because both
collectors import `app.settings`; a new field there would be a collector release.

## Tables (migration `3b7d9c1a5e20`, additive)

| Table | Purpose |
|---|---|
| `collection_entries` | What a collector owns: exact `card_print_id`, quantity, optional price paid, date, note. `resolution='unresolved'` rows (from legacy copy only) have no print and are never priced. One row per user and print. |
| `collection_entry_events` | Append-only holdings ledger (`quantity_before` → `quantity_after`), so a card added later is never a gain. |
| `watchlist_entries` | Watched versions with an optional target price. |
| `user_preferences` | `currency` (JPY only) and `collection_visibility` (private only). No row = defaults. |
| `collection_value_points` | One value per user per completed market day, written by the S4 daily stage (below). |

All reference `users.id` with ON DELETE CASCADE and `card_prints.id` with RESTRICT.
The package is not imported by `app.models`; `alembic/env.py` and `app/main.py`
import it. `tests/test_accounts_import_graph.py` proves no collector reaches it.

Apply: `alembic upgrade head` against staging (as for every migration,
`docs/railway_staging.md` section 3). Rollback: `alembic downgrade 6c2242f6f439`.
The downgrade **refuses** if any of the five tables holds a row: once collectors
have data there, dropping it is deleting user data and needs a human decision.

## Endpoints (all under `/me`, bearer JWT, `Cache-Control: private, no-store`)

| Method and path | What |
|---|---|
| `GET /me/collection` | Entries with value per card and in total, coverage, `as_of` |
| `POST /me/collection` | Add an exact, active print (409 if already held) |
| `PATCH/DELETE /me/collection/{id}` | Change or remove; each quantity change writes a ledger event |
| `GET /me/collection/value?window=7d\|30d\|all` | Coverage, what moved it, by set, what you paid, recorded history (`history`) and the day-one preview (`preview`) |
| `GET/POST /me/watchlist`, `PATCH/DELETE /me/watchlist/{id}` | Watchlist with value and distance to target |
| `GET/PUT /me/preferences` | JPY and private only (422 otherwise) |
| `GET /me/export`, `GET /me/export/{collection,watchlist}.csv` | Everything stored about the user, generated on request |
| `DELETE /me?confirm=delete my account` | Deletes the user and every row it owns. Legacy `saved_views` and `search_history` rows (SET NULL foreign keys, not CASCADE) and legacy `file_jobs` rows (`user_id` without a foreign key) are deleted explicitly, with the job's stored CSV files |

Another user's entry id answers 404, exactly like a missing id. After `DELETE /me`,
no table holds that user's id (`test_after_delete_me_no_table_carries_the_users_id`
finds every `user_id` column and foreign key to `users` from the live schema).

## Value rules (PLAN C1, C2, C4)

- Per-card value = archived `market_index_snapshots.index_value_jpy` for the exact
  print, positive only, on the latest day whose completion receipt verifies
  (`as_of`). Same print eligibility as Market Value (active, verified, JP, with a
  release). Yuyu-Tei sale prices and struck prices are already excluded by the
  archive; nothing is forward-filled or taken from a live price.
- Unpriced or unresolved entries count in coverage ("priced 41 of 48 cards") and
  never add 0. No priced entry means `value_jpy: null`, never 0.
- Movers compare units held at both ends of the window (from the ledger), with
  the Market Value comparability rule and the 80% comparable-value guard at both
  ends, no minimum card count (owner decision Q4). Any day without a receipt in
  the window makes it unavailable with a reason and the missing dates. Per-card
  impacts sum to the window's comparable change.
- By set groups on `CardPrint.release_product_id`, never a code prefix.
- What you paid compares only entries with both a price paid and a price today.

## Recorded history (PLAN B3, C3; S4)

**Daily stage.** `app.accounts.value_history.run_stage` is the last stage of
`python -m app.market_index_daily_pipeline` (the `market-index-snapshot` cron,
20:00 UTC). It runs only after the receipt gate, and after Market Value and the
Card Pirate Index, in its own session, REPEATABLE READ transaction and job lock
(`collection_value_history`), still under the coordinator's shared guard on the
producer lock. Its failure is reported as `collection_value` in the JSON report
(exit 1, or 2 if its lock is held); it cannot block or change the earlier
stages. With no users it reports `no_op`, 0 rows.

- One row per user holding at least one exact card, for the receipted day only.
  Holdings come from the ledger as of that day's receipt `completed_at`, so a
  rerun computes the same rows; later changes belong to the next day.
- Insert-only: `ON CONFLICT DO NOTHING`, then every stored field must equal the
  recomputed draft or the stage fails and rolls back (like the Market Value
  writer). A missed day stays missing; nothing is backfilled.
- `value_jpy` uses the same per-card values as above (`null` when nothing is
  priced, never 0). The step to the previous day is computed only when that day
  has a verified receipt (else `prior_day_missing`): units held on both days,
  the Market Value comparability rule, `P > 0` and the 80% comparable-value guard
  at both ends, no minimum card count (Q4). `P`/`Q` are stored only when `P > 0`.
- `segment_number` starts at 1 and increments after any break.

**Read (`history`).** 7D/30D chain the stored daily `Q/P` ratios over every day
of the window (integer products, one division, 50-digit Decimal). ALL runs from
the user's first point. A day without a point (`history_missing`, with the
dates), a step that is not publishable (its reason and `failed_step_date`) or a
window older than the first point (`not_enough_history`) makes the change
unavailable; it is never 0%. `points` lists the stored points in the window.
Movers for `window=all` compare the first recorded day with today.

**Day-one preview (`preview`, Q5).** Derived on read, never stored: the cards
held now, valued on each of the last 30 receipted days, with the same step rule
for its change. Days without a verified receipt are absent (the line breaks
there). It carries `kind: "preview"` and a label saying it is not the
collection's recorded history; the UI (S7) must show it visually separate.

**Rollback.** Revert the code; delete the private, non-published rows with
`DELETE FROM collection_value_points WHERE methodology_version = 1`.

## Legacy copy

`python -m app.accounts.migrate_legacy --dry-run` (default) or `--write`. A legacy
row maps to a print only when its legacy card reaches exactly one active print
through current, active, approved mappings; otherwise it is copied unresolved.
Idempotent on the legacy ids. Staging on 2026-10-13: 0 collection items and 0
wishlist items, so nothing to copy; the 25 legacy cards split 10 exact, 6 with
several prints, 9 with none.

## Known gaps (later sessions)

- No web UI yet (S5-S8). No price alerts (v2).
