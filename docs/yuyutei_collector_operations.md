# Yuyu-Tei collector — operating behaviour

Reference doc for `services/yuyutei_collector`, the permanent (non-spike)
Yuyu-Tei price collector, and its scheduled `--approved-mappings` batch mode.
See `docs/market_index.md` for how the prices this collector writes feed the
Market Index, and `docs/print_centric_pricing.md` for how they're read back
per collectible print.

## Schedule

The `yuyutei-collector` Railway service runs on a Railway Cron Schedule:

```
20 18 * * *
```

That is **once per day**, interpreted as:

| Timezone | Time |
|---|---|
| UTC | 18:20 |
| JST (Japan) | 03:20 (next day) |
| Malaysia (MYT) | 02:20 (next day) |

Each scheduled tick starts a fresh container, runs one bounded batch to
completion (or to an early stop - see below), and exits. The service has no
public domain, no HTTP server, and `restartPolicyType=NEVER` - Railway does
not restart it on its own; only the cron schedule (or a manual redeploy)
starts a new run. Per Railway's own cron semantics, a scheduled invocation
is skipped if the previous invocation is still running, so a hung collector
can never overlap itself or stay alive indefinitely.

**Do not increase the cron frequency until this schedule has been stable in
production for a meaningful review period.** Once-daily is the deliberate
starting cadence for a collector making live third-party requests; moving to
multiple times a day is a separate, explicitly-scoped decision, not a
default to drift into.

## What one run does

Effective start command:

```
python -m yuyutei_collector.collect --approved-mappings
```

See `services/yuyutei_collector/yuyutei_collector/batch.py` for the full
implementation. Each run:

1. **Selects eligible mappings** directly from database state - never a
   hardcoded id/card list. A `source_card_mappings` row is eligible only if:
   - its source is `yuyutei`
   - it is `is_active=true` and `review_status=approved`
   - it carries a `card_print_id` (an exact-print mapping, never a
     legacy-card-only one)
   - its linked `card_prints` row is itself `is_active=true` and
     `verification_status=verified`

   A newly approved+verified mapping is picked up automatically on the next
   run; a demoted/unverified one drops out automatically.

2. **Processes mappings sequentially**, never in parallel: one mapping is
   fully resolved (written, mapping-level failure, or operational error)
   before the next mapping's first request is made, with a conservative
   fixed delay between them.

3. **Writes at most one new `price_observations` row per mapping per run**,
   only on a fully validated success (see "Validation" below) - never zero
   or more than one.

## Validation / fail-closed behaviour

Every mapping goes through the same fail-closed checks as a manual single-
mapping run (`--mapping-id`, see `yuyutei_collector/writer.py`):

- the mapping must still be active, approved, and linked to a verified
  `card_print`
- the fetched page must classify as a normal product page
- price must independently agree between the page's JSON-LD and DOM content
  (see `yuyutei_collector/extractor.py`) - disagreement or either side being
  indeterminate fails closed, writing nothing
- the page's own displayed card code and treatment must match the mapping's
  expected identity

A validation failure (identity mismatch, price disagreement, missing price
data) writes **zero observations for that mapping**, is recorded in the run's
structured result, and the batch continues to the next mapping - it never
stops the whole run.

## Stock is not required

Product decision: Yuyu-Tei stock/availability is not required market
evidence. A Yuyu-Tei displayed sell price remains useful market evidence
whether or not the retailer currently reports the item in stock.

- Stock is **not** part of fail-closed validation. Missing, unknown,
  disagreeing-between-JSON-LD-and-DOM, or entirely absent (a future Yuyu-Tei
  layout) stock never invalidates an otherwise-verified price - see
  `yuyutei_collector/extractor.py`'s stock-agreement block and
  `yuyutei_collector/writer.py`'s write gates, both diagnostic-only for stock.
- Stock is **not** used for Market Index eligibility (see
  `docs/market_index.md` "Source eligibility") - an out-of-stock observation
  is exactly as eligible as an in-stock one of the same age.
- Stock is **not** a launch product field - the print-centric public API
  (`GET /prints/...`, see `docs/print_centric_pricing.md`) carries no
  stock/inventory field at all.
- Stock is still persisted internally as incidental metadata
  (`price_observations.stock_status`) when the extractor could resolve it,
  and the collector makes no extra request and adds no new stock-specific
  parsing to obtain it - it is opportunistic, never required.

## Source-wide denial behaviour

A page classified as an HTTP 403, or as a challenge/CAPTCHA/HTTP 429
response, is treated as a signal that Yuyu-Tei is denying this client
outright - not a per-mapping data problem. On that signal the collector:

- stops the remainder of the batch immediately
- writes no observation for the denied mapping
- never attempts any mapping after it in that run
- makes no retry and no bypass attempt of any kind

Observations already written earlier in the same run are preserved as-is.
The run's exit status is `source_wide_failure` in that case (see "Exit
status" below).

## Exit status

Each run reports one of three statuses (and a matching process exit code),
visible in the batch's final `batch_complete` log line:

| Status | Exit code | Meaning |
|---|---|---|
| `success` | 0 | Every selected mapping was attempted and wrote an observation (or there were zero eligible mappings to process). |
| `partial_failure` | 2 | The batch ran to completion (or was stopped by its own total-runtime watchdog) but at least one mapping failed at the mapping level. |
| `source_wide_failure` | 1 | A 403/429/CAPTCHA denial stopped the batch before every selected mapping was attempted. |

## Evidence retention

Every written observation carries full lineage: `card_print_id`,
`source_card_mapping_id`, `card_id`, `source_id`, plus a `raw_snapshot_id`
pointing at the actual fetched HTML (`raw_snapshots.raw_content`), the
extractor's selector version, and the observation's own `observed_at`. A
run's own `batch_run_id` (a short random id, generated fresh per invocation)
appears on every structured log line for that run, but is not persisted to
the database - it exists purely to correlate one run's log lines, not as
queryable state.

## Inspecting the last run

The collector logs one compact JSON object per event to stdout (Railway
deploy logs). Look for, in order:

- `batch_start` - `batch_run_id`, start timestamp
- `batch_mappings_selected` - the exact mapping ids this run selected, and
  the count
- `collection_start` / `homepage_result` / `product_result` /
  `extraction_result` / `collection_written` (or `collection_no_write`) -
  one full set per mapping
- `batch_mapping_result` - one line per mapping, with `stage`, `written`,
  `source_denied`, and `reasons`
- `batch_mappings_skipped` (only present if the batch stopped early) - which
  mapping ids were never attempted, and why
- `batch_complete` - final `status`, `exit_code`, and per-run counts

To confirm what actually landed in the database for a given day, query
`price_observations` by `observed_at` and cross-reference `card_print_id`
against the five (or, as the trusted print set grows, more) verified prints;
each real observation's `raw_snapshot_id` resolves to the actual page
content that was fetched.

## Disabling the cron

To stop scheduled runs without touching any code: clear the service's cron
schedule (Railway dashboard → the collector service → Settings → Cron
Schedule, or the equivalent `deploy.cronSchedule` config value set to empty)
and leave the start command as-is. The service will simply never start on
its own again; a manual redeploy is still possible for an on-demand run
(see "Running a manual batch" below) and remains subject to every fail-
closed/denial rule above.

## Running a manual batch (outside the schedule)

The same effective start command works for a one-off manual run - trigger a
redeploy of the collector service with `deploy.startCommand` set to
`python -m yuyutei_collector.collect --approved-mappings`. This is the exact
mechanism the daily cron itself uses; there is no separate "manual mode."
Do this sparingly - each run makes real requests to Yuyu-Tei - and never to
work around a `source_wide_failure` result from the previous run without
first understanding why it was denied.
