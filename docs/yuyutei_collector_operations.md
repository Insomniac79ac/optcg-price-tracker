# Yuyu-Tei collector — operating behaviour

Reference doc for `services/yuyutei_collector`, the permanent (non-spike)
Yuyu-Tei price collector, and its scheduled `--approved-mappings` batch mode.
See `docs/market_index.md` for how the prices this collector writes feed the
Market Index, and `docs/print_centric_pricing.md` for how they're read back
per collectible print.

## Current staging shards and schedules

The current Railway staging deployment has nine services, shards 0 through
8. The shard index in each service's start command must match the shard number
in that service's name, and every service must use `--shard-count 9`. Changing
the shard count is a deployment topology change, not a routine service edit.

Each shard retains its own existing UTC Railway Cron Schedule. The
authoritative expression is the individual service's **Settings → Cron
Schedule** value; this document deliberately does not copy the nine
expressions. Verify that value against the service's established schedule
rather than reconstructing or standardising schedules from memory.

Each scheduled tick starts a fresh container, runs one bounded shard batch to
completion (or to an early stop - see below), and exits. The services have no
public domain or HTTP server. A deployment and a collector execution are
different events: redeploying a cron service may or may not cause the
collector to execute immediately, so deployment success is not run success.

**Do not increase any shard's cron frequency until the current schedules have
been stable for a meaningful operational review period.** The established
cadence is deliberate for a collector making live third-party requests;
changing it is a separate, explicitly-scoped decision, not a default to drift
into.

## Required Railway networking

Every Yuyu-Tei collector shard in the current Railway staging deployment must
have all of the following:

- deployment region **US West**
- **Static Outbound IPs** enabled
- the current **HA** Static IP configuration enabled
- exactly **3 assigned outbound IPs** in the current Railway setup
- a deployment created after Static Outbound IPs were enabled or changed

Do not record the assigned IP addresses in this runbook. Verify their presence
and count in Railway instead.

Treat networking rollout as three separate states:

1. **Assigned:** Railway shows Static Outbound IPs enabled and three addresses
   assigned to the shard.
2. **Redeployed/effective:** a successful deployment exists whose timestamp is
   after the networking assignment or change. An assignment without this
   deployment remains configuration-pending.
3. **Operationally validated:** a normal collector execution after that
   qualifying deployment reports homepage HTTP 200 / `normal_product`, no
   source-wide abort, the expected shard workload completed, and exit code 0.

A successful deployment alone does not validate access to Yuyu-Tei. Wait for
and inspect a qualifying collector execution. At the time of this update
(2026-09-18), Static Outbound IP configuration is complete for all staging
shards (9/9), all shards have a qualifying deployment (9/9), and all shards
have passed operational validation (9/9 PASS). The original Yuyu HTTP 403
incident is operationally resolved.

## What one run does

Effective start-command pattern for shard `N`:

```text
python -m yuyutei_collector.collect --approved-mappings \
  --shard-index N --shard-count 9
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

### Observed networking incident signatures

The Static Outbound IP incident established these operational signatures:

| Signal | Dynamic-egress failure | Successful static egress |
|---|---|---|
| Homepage | HTTP 403 / `static_403` | HTTP 200 / `normal_product` |
| Batch behaviour | First mapping attempted; source-wide protection aborts; remaining mappings skipped | No source-wide abort; expected shard mappings are attempted and written |
| Process result | `source_wide_failure`, non-zero exit | `success`, exit 0 |

Multiple identical collector builds failed through dynamic outbound egress and
succeeded after Static Outbound IPs became effective. This isolates the
observed 403 incident to the outbound networking path. A homepage 403 does
not, by itself, demonstrate a parser failure, Playwright initialisation
failure, or PostgreSQL capacity failure.

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
against the shard's selected verified prints; each real observation's
`raw_snapshot_id` resolves to the actual page content that was fetched.

## Incident triage order

Use this sequence for suspected Yuyu-Tei access failures:

1. Verify the Railway project, environment, and exact shard service. Never
   infer environment from a service name alone.
2. Verify US West and the required Static Outbound IP/HA configuration,
   including all three assigned addresses.
3. Confirm that a successful deployment occurred after the networking
   assignment or change.
4. Inspect the first eligible collector run's logs for homepage HTTP status
   and classification.
5. Check whether source-wide failure protection fired and skipped the rest of
   the batch.
6. Investigate browser or parser logic only if a run using effective static
   egress also fails in a way that supports that diagnosis.
7. Do not manually run multiple shards simultaneously merely to test
   connectivity. Let their existing schedules provide isolated evidence.

Keep the project → environment → service → deployment scope explicit in notes
and screenshots. Do not use a temporary start-command override on a live
collector service for diagnostics: a prior attempt showed that the persistent
Railway start command can still win and launch the normal collector.

## Separate database-capacity incident

A separate incident found a very small PostgreSQL volume at about 95% usage,
with `raw_snapshots` dominating storage. That capacity condition did not cause
the shard-2 or shard-3 homepage 403 failures. Raw snapshot retention and
archive work is tracked separately; do not delete raw snapshots as an
emergency networking response without first reviewing their provenance and
retention obligations.

## New-shard verification checklist

- [ ] Staging/production environment verified
- [ ] Correct region
- [ ] Static Outbound IP enabled
- [ ] HA/IP assignment present (3 assigned IPs in the current setup)
- [ ] Correct shard index/count
- [ ] Expected start command
- [ ] Expected UTC cron
- [ ] Intended commit
- [ ] Redeployed after networking assignment
- [ ] First post-deploy run HTTP 200 / `normal_product`
- [ ] No source-wide abort
- [ ] Expected mappings completed
- [ ] Exit 0

## Schedule and manual-run safety

Changing or clearing a shard's cron is a separate, explicitly authorised
configuration action; it is not part of connectivity triage. Preserve each
shard's established schedule and start command during diagnosis.

Do not assume redeploy equals collector run, and do not use a temporary
start-command override on a live shard to manufacture a diagnostic run. A
manual collector trigger is also an explicit operational action, not a
default troubleshooting step. Prefer the next scheduled run, then correlate
its `batch_run_id` and `batch_complete` line with the qualifying deployment.
