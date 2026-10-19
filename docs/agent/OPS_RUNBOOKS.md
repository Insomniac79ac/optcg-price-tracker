# Ops runbooks (GitHub Actions)

Since 2026-10-15 agents work in Claude Code cloud sessions. They can reach GitHub (REST only;
GraphQL is blocked) but not Postgres or the Railway API, and they hold no staging credential.
GitHub Actions holds the staging credentials (`staging-delivery` Environment). So data-lane
reads and writes run as allowlisted runbooks in two workflows, and agents trigger them and read
the results over the GitHub REST API without ever seeing a secret.

| Workflow | Approval | Credentials | Runbooks |
|---|---|---|---|
| `ops-readonly` | none | `staging-delivery` | read-only, below |
| `ops-write` | owner (Environment `staging-ops`, required reviewer) | `staging-delivery`, only after approval | `enqueue-remaining-50`, `approve-f1-batch`, `enqueue-capture-batch` |

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
| `storage-rates` | `transients` (comma list; empty = all named) | Planning and stress (worst rolling 24 h) since the current collector code, as observed, with named steps removed, and with named transients excluded (`scripts/ops/storage_events.json`) | `storage-rates.json`, `volume-series.json` |
| `fleet-vs-receipt` | `receipt` (comma-separated committed receipts; empty = PR #103 then PR #173 rollouts) | All 10 collectors, each against the newest receipt that deployed it: live deployment, status, exact-commit marker, image digest, cron and deployment records after that receipt | `fleet-vs-receipt.json` |
| `official-images-status` | - | Last 5 `official-images-mirror` runs and the `check_official_images` database check (no R2 or Bandai request) | `official-images-status.json` |
| `db-diagnostic` | `diagnostic` (file name) | One reviewed SQL file from `scripts/diagnostics/` | `diagnostic-<name>.json` |
| `web-smoke` | - | Signed-out Playwright smoke of the staging site (`scripts/staging_web_smoke.py`); also runs after every delivery | `web-smoke.json` |

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

1. Candidates, read-only: Yuyu-Tei listings whose current proposal is ambiguous, pending and
   unreviewed, with no capture scope of any kind, oldest candidate first. One live resolver run
   (F1 included) drops every listing it now resolves exactly, so no capture is spent on a listing
   an `approve-f1-batch` run can map. The first `2 * count` bounded ambiguous families (2..12
   siblings, authoritative release) form the plan.
2. Then as `enqueue-remaining-50`: every #116 guard and the shared-print guard, the first `count`
   eligible (default 50, at most 100) pinned by SHA-256, the storage fit, the #116 tool's checks.
   The summary adds `candidates` (counts at each step) and `batch` (candidate id, card code,
   official siblings) for the owner's review. `apply=true` needs the dry run's `expected_sha256`;
   a new candidate or a moved digest changes the list and the apply refuses.

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
   schedule), so an apply never starts 02:00-06:00 UTC. It never fetches a source, enqueues work
   or touches a collector service. The owner's rule: a 48 h storage check after each batch.

Every run waits for the owner's approval in `staging-ops` before it gets credentials. Checked at
dispatch and again right before the runbook runs:

- no collector-affecting runbook 02:00-06:00 UTC, no write runbook 19:30-20:30 UTC (a dry run
  is neither);
- no staging delivery running or queued (`staging-automerge`, `staging-credential-presence`,
  `Verify staging merge`). `Serialized staging delivery` is `workflow_call` only and has no runs
  of its own; a workflow that calls it is the one to list.

Collector releases are not runbooks: they stay on the CI delivery path.

## Commands (cloud session, REST only)

```bash
R=repos/Insomniac79ac/optcg-price-tracker
ID=state-$(date -u +%Y%m%dT%H%M%SZ)          # any unique text; it becomes part of the run name

# 1. Dispatch (inputs are strings; omit the ones a runbook does not use)
gh api -X POST $R/actions/workflows/ops-readonly.yml/dispatches -f ref=staging \
  -f 'inputs[runbook]=staging-state' -f "inputs[request_id]=$ID"
#   verify-lossless:  -f 'inputs[ledger_floor]=59328'
#   db-diagnostic:    -f 'inputs[diagnostic]=freshness-not-met'
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
  (or `approve-f1-batch`, `enqueue-capture-batch`), `inputs[apply]=false`; `inputs[count]` is optional (empty is the
  runbook's default). The run waits for the owner. Read `approved_list_sha256` from the dry run;
  for an apply the owner (or an agent the owner asked) dispatches again with `inputs[apply]=true`
  and `inputs[expected_sha256]=<that sha>`, and the owner approves it.
- Agents never approve a waiting run (`pending_deployments` is blocked by `.claude/hooks/guard.py`).
- Is a staging delivery running? The same check the runbooks use:
  `gh api "$R/actions/workflows/ci.yml/runs?status=in_progress" --jq '.workflow_runs[].id'`, then
  for each id `gh api $R/actions/runs/<id>/jobs --jq '.jobs[] | select(.name|test("staging-")) | {name,status}'`,
  plus `staging-verify.yml` runs with `status=in_progress`.

## Adding a runbook or diagnostic

- Diagnostic: add `scripts/diagnostics/<name>.sql` (statements introduced by `-- name`, SELECT/WITH
  only; `{{ELIGIBLE}}` expands to the operational-health population) and its name to the
  `diagnostic` choice in `ops-readonly.yml`. The tests run every file on a real schema in a
  read-only session.
- Runbook: a module in `scripts/ops/` with `run(out_dir, ...) -> summary`, an entry in
  `RUNBOOKS` (kind, collector-affecting), and the workflow choice. Tests keep the workflow choices
  equal to `RUNBOOKS`. Both are DATA-lane PRs.
