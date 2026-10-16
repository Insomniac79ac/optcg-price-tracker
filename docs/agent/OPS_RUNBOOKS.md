# Ops runbooks (GitHub Actions)

Since 2026-10-15 agents work in Claude Code cloud sessions. They can reach GitHub (REST only;
GraphQL is blocked) but not Postgres or the Railway API, and they hold no staging credential.
GitHub Actions holds the staging credentials (`staging-delivery` Environment). So data-lane
reads and writes run as allowlisted runbooks in two workflows, and agents trigger them and read
the results over the GitHub REST API without ever seeing a secret.

| Workflow | Approval | Credentials | Runbooks |
|---|---|---|---|
| `ops-readonly` | none | `staging-delivery` | read-only, below |
| `ops-write` | owner (Environment `staging-ops`, required reviewer) | `staging-delivery`, only after approval | `enqueue-remaining-50` |

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
| `fleet-vs-receipt` | `receipt` (empty = PR #103 rollout) | All 10 collectors: live deployment, status, exact-commit marker, image digest, cron and deployment records after the receipt | `fleet-vs-receipt.json` |
| `official-images-status` | - | Last 5 `official-images-mirror` runs and the `check_official_images` database check (no R2 or Bandai request) | `official-images-status.json` |
| `db-diagnostic` | `diagnostic` (file name) | One reviewed SQL file from `scripts/diagnostics/` | `diagnostic-<name>.json` |
| `web-smoke` | - | Signed-out Playwright smoke of the staging site (`scripts/staging_web_smoke.py`); also runs after every delivery | `web-smoke.json` |

The `ops-summary` annotations carry what a check needs without the artifact: `staging-state`
adds `quarantined_refresh_work` (count, oldest blocked-since), `official-images-status` adds
`recent_runs` (status and start time of each of the last 5 mirror runs), and `db-diagnostic` adds
`rows` (each statement as `columns` plus `rows`, in file order while they fit 18,000 characters;
the rest are named in `rows_omitted` and stay in the artifact).
`identity-capture-work` lists every Yuyu identity-capture work item (state, attempts, denials,
transient failures) and the last 24 h of their attempt outcomes: the post-enqueue progress check.

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
- `ops-write`: dispatch the same way with `ops-write.yml`, `inputs[runbook]=enqueue-remaining-50`,
  `inputs[apply]=false`. The run waits for the owner. Read `approved_list_sha256` from the dry run;
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
