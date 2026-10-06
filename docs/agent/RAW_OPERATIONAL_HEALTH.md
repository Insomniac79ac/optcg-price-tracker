# RAW operational health contract

Schema: `raw-operational-run-v1`, JSON Schema in
[raw-operational-run.schema.json](raw-operational-run.schema.json). All timestamps
are UTC, prices retain JPY, target remains 24h and dispatch remains 23h.
The shared pure classifier is `app.services.operational_health`.

## Authoritative inventory

| Evidence | Existing authority | Meaning and limitations |
| --- | --- | --- |
| Legacy batch/population | `source_collection_attempts.batch_run_id`, ordinal, selected/start/finish, status | One retained attempt per selected mapping; standalone manual mapping CLI is not a batch. |
| Admitted RAW execution | `freshness_attempts.claimed_by`, claim/start/finish, category outcomes | Unique execution suffix joins claims to retained structured start/finish events. Old owner strings lack a provable execution boundary. |
| Capture | `raw_snapshots` and attempt capture FK | Persisted before parsing; raw payload never copied into health. Retention can remove older payloads. |
| Accepted price | `price_observations`, exact mapping/print/capture lineage | Acceptance is separate from listing availability, check freshness and promotion visibility. |
| Claims and retries | `freshness_work`, `freshness_price_states`, `freshness_attempts` | Token-fenced ownership, TTL, unchanged deadlines, bounded retry/backoff, RAW category success. |
| Budget | `source_dispatch_budgets`, attempts' reserved/actual/charged costs and admitted request ordinals | Source-wide headroom; charges may conservatively include crashes. Window counters are not a measured throughput guarantee. |
| Singleton | SNKRDUNK session advisory lock plus pinned backend ownership checks | Runtime checks prove the owning execution; no historical `pg_locks` inference. Lost lock stops writes. |
| Identity quarantine | work blocked state + identity-refusal attempt | Guarded refusal isolates an item; it does not prove a wrong identity was accepted. Never relax approval/artwork/exact-print guards. |
| Discovery | `freshness_work` kinds discovery/validation, attempts, existing `yuyutei_discovery_runs` / `snkrdunk_discovery_runs` | Separate from refresh; discovery progress is not a price check. |
| Execution boundary | existing `app_log_events`, `raw_execution_started/finished` | Retained, sanitized run envelope; metrics derive from the authorities above. No parallel queue, price store or migration. |

Natural `--due-work` executions emit start and finish events automatically in the
pinned staging environment. Individual claims remain independently durable if
telemetry fails or the process dies. A start with no finish remains incomplete;
it cannot be HEALTHY. An in-progress execution inside its declared runtime envelope is shown separately from the prior completed verdict; normal start events do not manufacture degradation or human-facing noise. An overdue/incomplete execution does trigger fix-forward. Event retention follows existing log retention, while claim
and capture retention remain unchanged. Run reconstruction joins execution ID to
`freshness_attempts.claimed_by`; final counters never replace those records.

The schema explicitly uses null for unknown scheduled time, image, OS exit code,
optional evidence and unavailable observations. A Python function return is not an
OS exit receipt. The rollout bakes a build-only revision module into the installed collector package, so the receipt reports the actual uploaded source revision rather than a potentially stale environment variable. Railway environment variables establish deployment identity, not
cron provenance. `trigger=unknown` remains unknown unless the caller has retained,
authoritative natural/manual provenance. Seeing a cron schedule is not proof of
one run's trigger. Operational validation observes subsequent scheduled cycles
without Run Now; it reports that provenance limitation explicitly.

## Source semantics and decisions

HEALTHY requires terminal, bounded, accounted execution evidence; settled claims
and reservations; guarded identity/promotion rules; no deadline deficit or denial.
No-listing with exact identity evidence is successful, retaining the old price's
capture time. Missing/malformed evidence is never promoted to no-listing.

Settled discovery/validation `completed` outcomes and discovery progress are
accounted separately from listed/no-listing price checks. They never contribute
to RAW successful-check or fresh-price coverage. Older retained receipts with
unknown counters remain unknown; no historical execution evidence is rewritten.

DEGRADED emits `action=autonomous_fix_forward`, with reasons, under the active
mission's GREEN/AMBER authority. It includes bounded transient/parsing/optional
failures, capacity pressure, retry/backoff, deadline misses and guarded item
quarantine. Settled expired attempts remain degraded evidence. Recovery supersedes
only that service's earlier receipt; a healthy shard cannot hide a failed shard.

BLOCKED emits `action=stop_affected_path`: denial/challenge, lost singleton,
wrong-shard routing, known duplicate requests, cost overruns, stuck expired claims,
unsettled completed runs, accepted identity/promotion integrity violation or
production/security/RED impact. Existing request admission continues to pause on
403/429 and stop the execution. The classifier never weakens those controls.

Yuyu `listed` includes captured listed prices; `promotional_hidden` reports the
internal sale subset. Existing public/history/index/Market Value policy remains
binding; no struck former price substitution. Captures and observation lineage
allow independent reconstruction. Destination-pinned delivery verifies public
promotion exclusion. Optional failures are reported when directly observed;
unobserved optional evidence stays null. Optional evidence cannot invent a price
or override a valid guarded price outcome.

SNKRDUNK honors `BATCH_MAX_MAPPINGS_PER_RUN` in admitted execution, not just each
inner chunk. Runtime and source-wide budgets still bound every request. One product
claim may serve RAW and future PSA10 demand; RAW summaries count RAW category
outcomes and observations without double-counting product captures. Exact identity,
artwork and manual verification gates are unchanged.

## State and autonomous mission interface

`generate_staging_state.py --live` reads current eligible RAW mappings with a
left join to planned work: missing planning stays visible, rather than disappearing
from coverage. It exposes due, overdue, claims/backoff/quarantine, never checked,
<=23h / 23–24h / >24h, age percentiles, oldest actionable due item, observed maximum
successful revisit gap over retained seven-day attempts and budget utilization /
headroom. A missing prior success cannot establish a revisit gap; null remains null.
Due means the successful-check age is due, even when retries or quarantine currently
prevent dispatch. Oldest actionable due excludes blocked/claimed/backoff work.

`operational_health` in CURRENT_STATE contains concise current source/shard
aggregates and latest retained execution identity. `latest_natural_run` stays null
when provenance is unknown. Hash-linked sanitized state artifacts retain the full
run summaries; CURRENT_STATE does not contain historical logs.

Mission tools can run:

```sh
python scripts/check_raw_health.py --live --output /tmp/raw-health.json
```

Exit 0: silent healthy update. Exit 1: autonomous fix-forward actions. Exit 2:
stop affected paths and diagnose under policy. The artifact's `mission_actions`
contains source, status, reasons and required action. This tool is read-only: it
never dispatches a collector, changes a mapping, sends notifications or pretends
to be an autonomous agent scheduler. Active missions must consume these actions,
regression-test bounded defects, deploy, observe recovery and regenerate state.
No intermediate human approval for GREEN/AMBER defects. RED remains a decision gate.

Human reports are reserved for meaningful milestones, DEGRADED fix-forward,
BLOCKED and final outcome. Healthy natural events update retained evidence without
notifications. No new collector or source schedule is introduced.

Provider documentation checked 2026-10-05:
[Railway cron lifecycle](https://docs.railway.com/cron-jobs),
[CLI staging deployment](https://docs.railway.com/cli/up).
Installed CLI help and live Deployment/DeploymentDeploymentInstance schema were
inspected; neither an execution trigger nor scheduled timestamp is assumed.

## Least-privilege delivery capability gate

The staging Environment secret remains a staging Railway Project Token. The
2026-10-05 correction verifies `projectToken { projectId environmentId }` with
`Project-Access-Token`, requiring the exact pinned project and staging environment.
CLI capability uses `RAILWAY_TOKEN` and `railway status --project ... --environment
... --json` with the same destination IDs. No account/workspace identity query or
temporary link is required. Delivery metadata and live state generation use that
same documented scoped status operation; raw status bodies are never published.
Destination mismatch or an unavailable required operation stops delivery. An
unsupported administrative query is not evidence that a Project Token is invalid.
Persistent source pauses are derived from budget state without exposing free-text
reasons; paused SNKRDUNK remains BLOCKED even after its prior denial receipt ages out.

Official references checked against installed Railway 5.62.1 help on 2026-10-05:
[Project Token identity](https://docs.railway.com/integrations/api),
[scoped CLI status](https://docs.railway.com/cli/status).
