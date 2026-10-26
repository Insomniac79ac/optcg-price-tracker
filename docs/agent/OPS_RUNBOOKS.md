# Ops runbooks (GitHub Actions)

Since 2026-10-15 agents work in Claude Code cloud sessions. They can reach GitHub (REST only;
GraphQL is blocked) but not Postgres or the Railway API, and they hold no staging credential.
GitHub Actions holds the staging credentials (`staging-delivery` Environment). So data-lane
reads and writes run as allowlisted runbooks in two workflows, and agents trigger them and read
the results over the GitHub REST API without ever seeing a secret.

| Workflow | Approval | Credentials | Runbooks |
|---|---|---|---|
| `ops-readonly` | none | `staging-delivery` | read-only, below |
| `ops-write` | owner (Environment `staging-ops`, required reviewer) | `staging-delivery`, only after approval | `enqueue-remaining-50`, `approve-f1-batch`, `enqueue-capture-batch`, `plan-refresh-backfill`, `apply-migration`, `collector-redeploy`, `collector-sibling-on`, `collector-sibling-off`, `catalogue-import`, `yuyu-source-probe` |

Code: `scripts/ops/` (`run.py` holds the allowlist `RUNBOOKS`), SQL: `scripts/diagnostics/`,
tests: `scripts/tests/test_ops_runbooks.py` (in CI `agent-state-tests`, with a Postgres service).
Both workflows run only when dispatched on `staging`.
The default branch is `main`, which does not carry them, and GitHub dispatches only workflows it
has registered. A push to `staging` that changes a workflow file registers it; that push run skips
every job. A dispatch that returns 404 means the workflow is not registered yet.

## Read-only runbooks (`ops-readonly`)

Every database read goes through `scripts/ops/db.py`: the pinned staging project and environment,
the Postgres service's single TCP proxy, the `staging_db_read_check` schema fingerprint, and
`default_transaction_read_only=on` with a statement timeout. The Postgres password is masked in
the log (`::add-mask::`) and never written. Before upload, `run.py` deletes every output if any
file contains a known secret value.

| `runbook` | Inputs | What it does | Main output |
|---|---|---|---|
| `staging-state` | - | One live read feeds `generate_staging_state` and `check_raw_health` | `CURRENT_STATE.yaml`, `evidence/staging-state-*.json`, `raw-health.json` |
| `verify-lossless` | `ledger_floor` (exclusive) | Every daily-v1 ledger row above the floor decoded twice (independent zstd + package decoder) | `verify-lossless-from-<floor>.json` (`next_floor_exclusive`) |
| `verify-lossless` | `ledger_floor=sample` | Sibling-encoding gate (`scripts/ops/encoding_sample.py`): newest plaintext rows per parser paired as the writer would with `RAW_DICTIONARY_SIBLING=true`, encoded in memory only. `gate_pass` needs >=10 pairs and median encoded <=10 KB (Yuyu listings) and <=16 KB (SNKRDUNK discovery) | `encoding-sample.json` |
| `storage-rates` | `transients` (comma list; empty = all named) | Planning and stress (worst rolling 24 h) since the current collector code, as observed, with named steps removed, and with named transients excluded (`scripts/ops/storage_events.json`) | `storage-rates.json`, `volume-series.json` |
| `official-series-index` | none | Bandai's JP Card List series picker plus, for uncoded and missing series, up to 8 series pages broken down by the product each entry names (requests 2 s apart, honest User-Agent, stops on 401/403/429/451) against the catalogue's release products: every Bandai series, imported or not, prints per imported series, and catalogue products absent from the index | `official-series-index.json` |
| `snkr-page-check` | none | SNKRDUNK product pages the collector already stored (no SNKRDUNK request): the newest `identity_refusal` pages since 2026-10-26 08:00Z and the newest captured pages before it, decoded through their dictionary bases; per page HTTP status, size, `<img>` with a class ending `__mainImage`, image-related class tokens, gallery props present, short excerpt around `mainImage` | `snkr-page-check.json` |
| `fleet-vs-receipt` | `receipt` (comma-separated committed receipts; empty = PR #103 then PR #173 rollouts) | All 10 collectors, each against the newest receipt that deployed it: live deployment, status, exact-commit marker, image digest, cron and deployment records after that receipt | `fleet-vs-receipt.json` |
| `official-images-status` | - | Last 5 `official-images-mirror` runs and the `check_official_images` database check (no R2 or Bandai request) | `official-images-status.json` |
| `db-diagnostic` | `diagnostic` (file name) | One reviewed SQL file from `scripts/diagnostics/` | `diagnostic-<name>.json` |
| `web-smoke` | - | Signed-out Playwright smoke of the staging site (`scripts/staging_web_smoke.py`); also runs after every delivery | `web-smoke.json` |
| `capture-batch-preview` | `count` (up to; empty = 50) | The `enqueue-capture-batch` plan with every candidate judged, read-only: exclusion breakdown, the batch, its SHA-256 and storage fit | `plan.json`, `replan.json`, `approved-list.json`, `storage-fit.json` |

The `ops-summary` annotations carry what a check needs without the artifact: `staging-state`
adds `quarantined_refresh_work` (count, oldest blocked-since), `official-images-status` adds
`recent_runs` (status and start time of each of the last 5 mirror runs), and `db-diagnostic` adds
`rows` (each statement as `columns` plus `rows`, in file order while they fit 18,000 characters;
the rest are named in `rows_omitted` and stay in the artifact).
`identity-capture-work` gives Yuyu identity-capture work totals by state (with id range), the newest
100 items (state, attempts, denials, transient failures) and the last 24 h of their attempt
outcomes: the post-enqueue progress check. Older items (500+ on staging) stay out of the summary.

Nothing here is collector-affecting or a write, so no quiet window applies.

## Write runbooks (`ops-write`)

`enqueue-remaining-50` (PR #116 tool `scripts/yuyu_identity_capture_enqueue.py`):

1. Re-plans the NEW100 plan on live digests (`scripts/ops/replan.py`, every #116 guard).
2. Builds the approved list (first `count` eligible, default 50) and its SHA-256.
3. Reports the batch's storage fit at planning, stress A and stress B (information; the owner's
   rule is fit at planning AND stress).
4. Runs the #116 tool: dry run by default (read-only session, rolled back). `apply=true` writes,
   and only when `expected_sha256` equals this run's list, i.e. the list from a dry run the owner
   reviewed. A moved digest changes the list, and the apply refuses. The summary lists
   `written_work_ids`.

`enqueue-capture-batch` (`scripts/ops/capture_batch.py`): the next identity-capture batch after
NEW100 (work ids 3678 to 3777 are done and never replayed), planned live instead of from a file.

1. Population, read-only: Yuyu-Tei listings whose current proposal is ambiguous and pending.
   Each is excluded for one reason, first match wins: `reviewed_decision`, `capture_blocked`,
   `already_captured` (a capture scope with an attempt), `capture_queued` (a scope never
   attempted). The rest are uncaptured, oldest candidate first.
2. One live resolver run (F1 included) over every uncaptured listing. A listing it now resolves
   exactly (`exact_now:<rule>`) or otherwise (`resolved_since:<status>`) drops out, so no capture
   is spent on a listing an `approve-f1-batch` run can map; so do `unbounded_siblings` (outside
   2..12) and `no_release`. Every remaining bounded ambiguous family is planned.
3. Every #116 guard per planned candidate, then the shared-print guard in plan order (eligible
   candidates never share a print). `count` means up to (default 50, at most 100): the batch is
   the first min(count, eligible) eligible, pinned by SHA-256, with the storage fit and the #116
   tool's checks. The dry run and apply judge candidates until `count` are eligible, which gives
   the same batch as judging all of them.
4. It refuses only when nothing is eligible (`status` REFUSED, the breakdown kept). `apply=true`
   needs `expected_sha256` and refuses only when its re-planned list differs from it.

The summary carries `requested`, `batch_size`, `breakdown` (the counts above plus
`first_failed_guard`, one line per reason) and `batch` (candidate id, card code, official
siblings). Until 2026-10-19 the batch size also bounded who was judged (the first `2 * count`),
so a smaller count found fewer eligible: 12 of 100 at count 50, then 9 of 24 at count 12 (dry
run 39255746139). `capture-batch-preview` (ops-readonly, no approval) is the same plan with every
candidate judged; its SHA-256 equals a dry run's on unchanged state, and the apply still needs the
owner's approval in `staging-ops`.

`approve-f1-batch` (D9 F1, `scripts/ops/f1_approve.py`): approves current exact Yuyu-Tei
proposals made by the F1 rule (reason `unique_listing_kind_resolves_one_release_sibling`) in
batches of about 500 (`count`, default 500, at most 600), through the admin page's own
`approve_exact_proposal`, so every admin guard applies.

1. Selects the batch read-only, oldest proposal first. Each proposal is re-checked against a fresh
   resolver run (same evidence digest, resolver version and sole recommended print), the candidate
   state it recorded, the listing's mapping (none or the same print, never rejected) and the print
   (active, verified, no other current Yuyu-Tei mapping, claimed by no other proposal in the
   batch). Failures are left out and counted under `excluded`.
2. Pins the first `count` as the approved list (SHA-256) and writes `approved-list.json`,
   `batch-detail.json` (every proposal with card code, print rarity/variant/kind, listing title,
   rarity token, kind, price and URL) and `sample.json`. The summary carries every
   `proposal_group_ids`, a 20-row random `sample` (seeded by the SHA, so the same list gives the
   same sample), the listing-kind to print-kind counts, an apply-time estimate and the storage
   room and days to the 3 GiB reserve now.
3. Dry run by default: nothing is written. `apply=true` rebuilds the list, refuses unless it hashes
   to `expected_sha256`, then approves each proposal in its own transaction (as the admin page
   does) under reviewer `ops-write:approve-f1-batch:<run id>`. It stops at the first refusal, or
   when the collector quiet window starts; what was approved stays approved and is listed in
   `approved_group_ids`. Approval is collector-affecting (new mappings join the collectors' own
   schedule), so an apply never starts 02:00-06:00 UTC. Each approval plans the new mapping's raw
   refresh work through the shared approval path (`ensure_refresh_work`, below); the runbook never
   fetches a source or touches a collector service. The owner's rule: a 48 h storage check after
   each batch.

`plan-refresh-backfill` (`scripts/ops/refresh_backfill.py`): raw refresh work for approved
mappings that have none. A collector prices only a mapping with a `refresh` row; since #189
every approval path plans it (`app.services.mapping_refresh.ensure_refresh_work`, guarded by
`scripts/tests/test_mapping_refresh_guard.py`), and this plans it once for mappings approved
before (the 97 of F1 batch 1 among them).

1. Lists, read-only, every mapping in the operational-health population (active, current,
   approved, verified print, SNKRDUNK manually verified) with no refresh work, oldest mapping
   first; the first `count` (default 500, at most 1000) are pinned by SHA-256 over mapping id,
   source, print and listing identity.
2. Dry run by default: the summary carries `approved_list_sha256`, `by_source`, every
   `mapping_ids`, a 10-row `sample` (seeded by the SHA) and `storage` (ESTIMATE: the measured
   planning MB/day per existing refresh row times the new rows, and days to the reserve before and
   after).
3. `apply=true` rebuilds the list, refuses unless it hashes to `expected_sha256`, and plans each
   mapping in one transaction: raw only (Yuyu-Tei `sell`, SNKRDUNK `floor`, never PSA10), existing
   work untouched. A mapping it cannot plan (lineage conflict) is listed in `skipped_mapping_ids`
   and the run reports not ok. No source request. Collector-affecting (the collectors pick the new
   rows up), so an apply never starts 02:00-06:00 UTC.

`apply-migration` (`scripts/ops/apply_migration.py`): the only way a schema migration reaches
staging. Nobody runs `alembic upgrade` against staging by hand, and agents never do.

1. Inputs `revision` and `parent`. Only allowlisted pairs (`ALLOWED`, a reviewed code change)
   are accepted: today exactly `7a52e9b48e8a` on parent `3b7d9c1a5e20` (new-sources S1, #181).
   The checkout on `staging` must carry that migration as its single Alembic head on top of
   `parent`, so dispatch it only after the migration's PR has merged. Anything else is refused at
   dispatch (preflight) and again in the runbook job.
2. Before any write, and on the dry run too: the newest Railway backup of the staging Postgres
   volume must be younger than 24 h (`scripts/staging_backup_age.py`), the read-only staging
   fingerprint must pass, and the live `alembic_version` must be exactly `parent`. Already
   applied, any other live revision, no backup or a stale one: refused, nothing written. With no
   backup the refusal names the Railway setting: staging project, Postgres service, its
   `postgres-volume` volume, Backups (turn on a schedule or create one now).
3. Dry run (default) writes nothing. The summary carries `sql_plan_sha256` (SHA-256 of the
   offline Alembic SQL for that one step, saved as `migration-plan.sql` in the artifact),
   `existing_tables_locked` (each existing table and the locks the plan takes on it),
   `new_tables`, `row_counts` (MEASURED by `count(*)`, or the planner estimate labelled ESTIMATE
   above 1,000,000 rows), `lock_budget` and the `backup` it checked.
4. `apply=true` with `expected_sha256=<sql_plan_sha256 from the reviewed dry run>` rebuilds the
   plan and refuses unless it hashes the same, re-checks backup, fingerprint and live revision,
   then runs only that revision in one transaction with `lock_timeout` 5 s and
   `statement_timeout` 120 s, holding the `alembic_version` row so a second run waits and then
   refuses as already applied. Any error rolls the whole step back, `alembic_version` included.
   It reads `alembic_version` back and records it in `migration-receipt.json`
   (`alembic_version_after`). No source request.
   - Locks are held until the one commit: a table under ACCESS EXCLUSIVE (for #181:
     `price_observations`, through its CHECK VALIDATE scan) blocks its readers and writers for
     the whole step. A lock not granted in 5 s, or a statement over 120 s, rolls everything back.
   - Collector-affecting (collectors read these tables), so an apply never starts 02:00-06:00 UTC,
     nor 19:30-20:30 UTC.
5. After the apply, verify staging on its head (`staging-state`, or a `Verify staging merge`
   re-run): until the migration is applied, verification fails on the revision by design.

`collector-redeploy` (`scripts/ops/collector_redeploy.py`): a new deployment of every staging
collector on its own verified image, so it picks up rotated shared variables (added 2026-10-22,
after the Postgres password was rotated following Railway's security incident). A restart or a
cron run keeps the variables of the deployment it runs, and Railway's dashboard offers only
"Deploy latest commit" on a collector, which builds from the branch and loses the verified upload.

1. For each of the 10 collectors, in name order, the fleet pin in `docs/agent/STAGING_FLEET.json`
   gives the commit (`snkr_component` for `snkrdunk-collector`, `yuyu_reader_component` for the
   shards), the same pins Verify staging merge checks. Committed rollout receipts are not used:
   only some deliveries committed theirs (on 2026-10-22 the receipt chain still named the PR #103
   SNKR image after PR #180 had delivered SNKR, and the first apply restored the older image).
2. Dry run (default): per collector, the redeploy source (the newest redeployable deployment with
   that exact-commit marker and an image), its digest and the live deployment. The summary
   carries `plan_sha256` over service, commit, digest and live deployment, so any deployment in
   between refuses the apply. A collector with no source fails the dry run.
3. `apply=true` with `expected_sha256=<plan_sha256>` runs `collector_variables.restore` per
   collector: stages `APP_ENV=staging` with `--skip-deploys` (a value every collector already
   carries), redeploys the source with the previous image tag, waits for SUCCESS and checks
   digest, cron schedule, start command and read-back. Stops at the first failure and before
   02:00 UTC. The summary lists each new deployment id and digest. No build, no code change, no
   source job. Collectors already on their pin are redeployed too (same image), which is harmless.
4. Afterwards `fleet-vs-receipt` reports the new deployment ids as records after the receipts,
   by design. Verify staging merge then needs one natural cron run per collector on the new
   deployment (its SNKR check waits up to 30 minutes for that receipt).

`collector-sibling-on` / `collector-sibling-off` (`scripts/ops/collector_flag.py`): set
`RAW_DICTIONARY_SIBLING` to `true` / `false` on every collector and make it live (owner decision
2026-10-24, after the #197 encoding sample passed). A collector reads variables only on a new
deployment and Railway no longer redeploys their images, so each one is re-uploaded on its
fleet-pinned commit.

1. Dry run: every collector's active deployment must be a SUCCESS exact-commit upload of its
   fleet pin; the plan lists current and target values and `plan_sha256` over service, commit,
   live deployment and values. Every collector is re-uploaded, even one already showing the target
   (a staged value says nothing about what its running deployment read), so a re-run is safe.
2. `apply=true` with the plan SHA, per collector in its safe slot: stage the value with
   `--skip-deploys` and prove no deployment started; re-upload the pinned commit
   (`deploy_staging_collectors.reupload`, with a one-off nonce in the build-only marker so Railway
   does not skip it; the runtime REVISION stays the commit); refuse a skipped upload; check the new
   deployment is active, SUCCESS, exact marker, unchanged schedule and start command, and writer
   flags as before except the switch, and refuse a collector deployed since the dry run. About 7
   minutes per collector plus slot waits; the job allows 360 minutes.
3. A collector starts only with enough job time and time before the next quiet window (02:00 or
   19:30 UTC) for itself plus a revert (80 minutes), so start early in the day. On a failure it
   stops; if that collector's value was already staged it is put back (previous value, re-upload).
   Re-measure storage (`storage-rates`) 24 hours later.

`catalogue-import` (`scripts/ops/catalogue_import.py`, input `scope`): add Bandai JP catalogue
prints to staging through the existing import engine (`app.import_frozen_bandai_to_canonical_staging`:
`print_import_planner` plans, `CanonicalImportApplier` writes, every pin unchanged). Phase 2 of the
catalogue-gap request (owner 2026-10-26).

1. Scope: a name in `docs/agent/CATALOGUE_IMPORT_SCOPES.json` (changed by PR). Coded series go to
   the importer's `--series`. Uncoded products (named, or every product inside an `uncoded_series`
   filtered by `product_pattern` / `exclude_pattern` / `exclude_products`) go to
   `--uncoded-product` when they pass `app.services.uncoded_product_evidence` with the step C
   amendments (owner 2026-10-26): per-product Asia-EN agreement (equal code set agrees, no shared
   code is a recorded Japan-only release, partial overlap is refused for review unless the owner
   cleared that exact overlap in `uncoded_product_evidence.ASIA_EN_OWNER_CLEARED`), the
   single-product catch-all (Family Deck Set), and a repeated code when each occurrence is its own
   Bandai entry at its own image address (base and holo reprints). The rest are reported, grouped
   by rule. `report_only` scopes (`promos-limited-measure`) never import. Family batches:
   `flagship-battle`, `standard-battle`, `promotion-packs`, `premium-card-collections`,
   `magazines`, `events-and-prizes`, `other-limited`, `family-deck-set`.
2. Capture: a fresh Bandai JP snapshot in the run directory, every six-digit series page plus the
   images of the scope's entries only; with uncoded products, also Bandai's Asia-EN picker and
   every one of its uncoded series pages (at most six; any failure refuses, so a missing page can
   never read as "Japan-only"), written beside it as `bandai_asia_en/current`; 1 request per second, honest User-Agent, stop on
   401/403/429/451. Bandai's link labels in 入手情報 (カードリスト, 商品情報) are dropped by the
   parser (`official_cardlist.OBTAIN_INFO_LINK_LABELS`).
3. Target: the importer's `verified_staging_target` with only `open_tunnel` rerouted
   (`canonical_staging_target.ReroutedChecker` around the real checker) to the pinned staging
   Postgres TCP proxy (`ops/db.py`) instead of a `railway connect` tunnel. All fingerprints and
   the revision-equals-head check still run. The dry run's session is read-only at the server.
4. Dry run: per-print rows (code, outcome, product, artwork variant, flags), outcome counts, the
   engine's dry-run report and `plan_sha256` over the scope, every whole planned print (identity,
   official metadata, proposed card and product), the entry record it was planned from, the
   uncoded products the importer is told to establish and the Asia-EN evidence file.
5. `apply=true` with that SHA: refuses without a Railway backup of the staging Postgres volume
   under 24 hours old (the recovery point, as for `apply-migration`); re-captures, re-checks the
   quiet windows and re-plans; the importer refuses before the applier
   runs unless the plan is identical. Then the engine writes in one transaction with its own
   checks (untouched price tables, import lock, pre-count preflight). Keeps the collector quiet
   windows (collectors match listings against `card_prints`).

`yuyu-source-probe` (`scripts/ops/yuyu_probe.py`): after a Yuyu-Tei challenge pauses every shard
(`source_dispatch_budgets.pause_reason = source_denial`, no timer), authorize ONE probe instead of
clearing the pause blindly (owner decision 2026-10-26, perfectionist).

1. Dry run (read-only): the Yuyu-Tei budget (must be paused for a denial), the latest denial
   attempt (from ordinary refresh work, or from an earlier probe after a 6-hour cool-down), the
   probes already recorded for it (all closed, at most 3 per denial), and the probe mapping: the
   approved, active Yuyu-Tei mapping whose refresh last captured cleanly. The request bound is that
   mapping's refresh cost plus a homepage warm-up allowance (60 to 200). `plan_sha256` covers
   source, denial, probe number, mapping, print, product identity and bound.
2. `apply=true` with that SHA: re-reads the facts on a fingerprinted connection, refuses unless
   identical, then `app.services.source_recovery.plan_yuyu_probe` records one authorized,
   unattempted validation scope in one transaction. No request, no reservation.
3. The next scheduled Yuyu shard turn (any shard; one claim wins) serves it instead of its
   ordinary work (`yuyutei_collector.recovery`): one metered product capture from the collectors'
   own network, identity validated, no price written. Only a completed, identity-verified HTTP 200
   capture of that mapping's product page clears the pause (`resume_after_yuyu_probe`). Every probe
   is closed afterwards whatever happened, and stale ones (newer denial, manual unpause, mapping no
   longer eligible, lease expired) are closed at the next turn, so none can be served twice or
   stall ordinary claims. After a challenge the pause stays; a new probe needs a new dry run and
   approval after the cool-down. Check the outcome with `ops-readonly staging-state` (Yuyu no
   longer BLOCKED) or `db-diagnostic work-by-state`.

Every run waits for the owner's approval in `staging-ops` before it gets credentials. Checked at
dispatch and again right before the runbook runs:

- no collector-affecting runbook 02:00-06:00 UTC, no write runbook 19:30-20:30 UTC (a dry run
  is neither);
- no staging delivery running or queued (`staging-automerge`, `staging-credential-presence`,
  `Verify staging merge`). `Serialized staging delivery` is `workflow_call` only and has no runs
  of its own; a workflow that calls it is the one to list.

Collector releases are not runbooks: they stay on the CI delivery path. `collector-redeploy` is
not a release: it puts each collector back on the image of its fleet pin.

## Commands (cloud session, REST only)

```bash
R=repos/Insomniac79ac/optcg-price-tracker
ID=state-$(date -u +%Y%m%dT%H%M%SZ)          # any unique text; it becomes part of the run name

# 1. Dispatch (inputs are strings; omit the ones a runbook does not use)
gh api -X POST $R/actions/workflows/ops-readonly.yml/dispatches -f ref=staging \
  -f 'inputs[runbook]=staging-state' -f "inputs[request_id]=$ID"
#   verify-lossless:  -f 'inputs[ledger_floor]=59328'
#   encoding sample:  -f 'inputs[runbook]=verify-lossless' -f 'inputs[ledger_floor]=sample'
#   db-diagnostic:    -f 'inputs[diagnostic]=freshness-not-met'
#   capture-batch-preview: -f 'inputs[count]=50'
#   storage-rates:    -f 'inputs[transients]=2026-10-14-04z'

# 2. Find the run by its name
RUN=$(gh api "$R/actions/workflows/ops-readonly.yml/runs?branch=staging&event=workflow_dispatch&per_page=20" \
  --jq ".workflow_runs[] | select(.display_title | contains(\"$ID\")) | .id" | head -1)

# 3. Wait for it (status, conclusion)
gh api $R/actions/runs/$RUN --jq '{status, conclusion, html_url}'

# 4. Read the summary: notice annotations titled "ops-summary i/n" on the job's check run
JOB=$(gh api $R/actions/runs/$RUN/jobs --jq '.jobs[] | select(.name=="runbook") | .id')
gh api $R/check-runs/$JOB/annotations \
  --jq '[.[] | select(.title | startswith("ops-summary"))] | sort_by(.title) | map(.message) | join("")' | jq .

# 5. Artifact (full outputs): list it; the zip download is blocked from cloud sessions
gh api $R/actions/runs/$RUN/artifacts --jq '.artifacts[] | {id, name, size_in_bytes}'
```

- The artifact zip (`gh api $R/actions/artifacts/<id>/zip`) and the job log redirect to blob
  storage, which the cloud-session proxy blocks. Use the annotations (the summary is chunked
  into up to 9 notices), or the GitHub MCP `get_job_logs` tool, which prints the same summary
  JSON. The owner can download the artifact from the run page.
- `ops-write`: dispatch the same way with `ops-write.yml`, `inputs[runbook]=enqueue-remaining-50`
  (or `approve-f1-batch`, `enqueue-capture-batch`, `plan-refresh-backfill`, `apply-migration`), `inputs[apply]=false`; `inputs[count]` is optional (empty is the
  runbook's default). The run waits for the owner. Read `approved_list_sha256` from the dry run;
  for an apply the owner (or an agent the owner asked) dispatches again with `inputs[apply]=true`
  and `inputs[expected_sha256]=<that sha>`, and the owner approves it.
  `apply-migration` takes `inputs[revision]` and `inputs[parent]` instead of `count`, and its
  sha is `sql_plan_sha256`:
  `-f 'inputs[runbook]=apply-migration' -f 'inputs[revision]=7a52e9b48e8a' -f 'inputs[parent]=3b7d9c1a5e20'`.
- Agents never approve a waiting run (`pending_deployments` is blocked by `.claude/hooks/guard.py`).
- Is a staging delivery running? The same check the runbooks use:
  `gh api "$R/actions/workflows/ci.yml/runs?status=in_progress" --jq '.workflow_runs[].id'`, then
  for each id `gh api $R/actions/runs/<id>/jobs --jq '.jobs[] | select(.name|test("staging-")) | {name,status}'`,
  plus `staging-verify.yml` runs with `status=in_progress`.
- DATA-lane PR mission: `python scripts/staging_mission.py digest --base origin/staging` prints the
  PR's one added mission file, the files its impacts must cover and the `diff_sha256` to write into
  it. What a delivery will act on: `python scripts/staging_mission.py compose --base <merge>^1
  --head <merge> --output /tmp/m.json` (add `--allow-none` for a PRODUCT-lane merge).

## Adding a runbook or diagnostic

- Diagnostic: add `scripts/diagnostics/<name>.sql` (statements introduced by `-- name`, SELECT/WITH
  only; `{{ELIGIBLE}}` expands to the operational-health population) and its name to the
  `diagnostic` choice in `ops-readonly.yml`. The tests run every file on a real schema in a
  read-only session.
- Runbook: a module in `scripts/ops/` with `run(out_dir, ...) -> summary`, an entry in
  `RUNBOOKS` (kind, collector-affecting), and the workflow choice. Tests keep the workflow choices
  equal to `RUNBOOKS`. Both are DATA-lane PRs.
