# CLAUDE.md

Guidance for Claude Code when working in this repository (Card Pirate, `Insomniac79ac/optcg-price-tracker`).
The operating contract is [docs/agent/AUTONOMY_POLICY.md](docs/agent/AUTONOMY_POLICY.md) and the hard
rules are [docs/agent/INVARIANTS.md](docs/agent/INVARIANTS.md). Read them; this file does not repeat them.

## Hard lines

- **Staging only.** Base branch `staging`. Production is RED: never touched without the owner's explicit decision.
- **PSA10 is OFF.** Do not activate or build toward it unless the owner asks.
- **Never print secrets**, their lengths or parts: no `env`, `printenv`, `.env` contents, tokens in logs,
  commit messages, PR text or chat. Never commit credentials.
- Prices are JPY, timestamps UTC. Exact-card identity guards are never weakened.
- No merges 19:30-20:30 UTC (market-index snapshot). No collector change 02:00-06:00 UTC.

## Lanes

CI decides the lane from the diff (`scripts/product_lane.py`, run by `policy-gate`); any doubt is DATA.

- **PRODUCT**: `apps/web` (not `vercel.json`), `services/api/tests`, docs outside `docs/agent/`
  (plus `docs/agent/PRODUCT_LOG.md`), allowlisted collector-facing API modules, additive product
  migrations. No mission manifest; append a line to `docs/agent/PRODUCT_LOG.md`. Auth/security paths
  need an `Independent security review: ...` line in the PR description.
- **DATA**: everything else, including collectors and their import graph, identity, prices, Market
  Value/Index, `scripts/`, `docs/agent/`, `.github/`, `.claude/` and this file. Adds exactly one
  mission file `docs/agent/missions/<branch, / as ->.json` for the PR's own diff
  (`python scripts/staging_mission.py digest --base origin/staging` prints `diff_sha256`). Never edit
  another mission file. Merging `staging` in keeps the hash valid unless the merge changes the PR's
  own files. Carried state (API and Alembic expectations, pinned collector components, checks,
  operational notes) is `docs/agent/STAGING_FLEET.json`; edit it only when the PR moves the fleet,
  and list it in the mission's impacts. `docs/agent/STAGING_MISSION.json` is retired: nothing reads it.
- Collector PRs: the mission may set `yuyu_reader_component`/`snkr_component` to `merge` for its own
  delivery. After a collector delivery or a migration, the next staging merge must be a small PR that
  pins those keys to the merge SHA and `revision` to the new Alembic head in `STAGING_FLEET.json`,
  or Verify staging merge fails on the old pin.
- Split a change that spans both lanes into two PRs.
- The committed hook `.claude/hooks/guard.py` blocks Edit/Write on DATA paths unless the session has
  `CARDPIRATE_LANE=data` (the message says "Data lane. Split it into its own PR or open an issue for the owner.").
- Confirm the collector import graph is untouched for every PR: `python scripts/product_lane.py
  --base origin/staging` lists the lane and its reasons; no reason may read `collector runtime input
  (import graph)`.

## Delivery

- Open PRs as **draft**. A non-draft PR to `staging` arms native auto-merge once CI passes
  (`staging-automerge`), unless it carries the `hold-for-owner` label (the owner merges it by hand).
  Agents may add that label, never remove it.
- One staging delivery at a time: before marking a PR ready, check no `staging-automerge`,
  `staging-credential-presence` or `Verify staging merge` job is running or queued
  (commands in [docs/agent/OPS_RUNBOOKS.md](docs/agent/OPS_RUNBOOKS.md#commands-cloud-session-rest-only)).
- Staging must be up to date: rebase on `staging` before marking ready.
- The CI artifacts are the delivery receipt. After every delivery CI also runs the signed-out web
  smoke (`scripts/staging_web_smoke.py`).

## GitHub from a cloud session

- GraphQL is blocked. Use `gh api` (REST). Draft/ready and auto-merge:
  - `gh api -X POST repos/{o}/{r}/pulls/{n}/ccr/ready_for_review`
  - `gh api -X POST repos/{o}/{r}/pulls/{n}/ccr/convert_to_draft`
  - `gh api -X PUT repos/{o}/{r}/pulls/{n}/ccr/auto_merge` / `-X DELETE ...` (only when the task allows it)
- Artifact zips and job logs redirect to blob storage, which the proxy blocks. Read runbook summaries
  from check-run annotations, or use the GitHub MCP `get_job_logs` tool.
- Blocked by the hook: deployments, pending deployments (environment approvals), rulesets, branch
  protection, secrets, environments and variables APIs; direct pushes to `staging`; force pushes;
  PR approvals; admin merges.

## Staging data: ops runbooks

Cloud sessions cannot reach Postgres or Railway and must not try (`railway` and remote `psql`/`pg_dump`
are blocked). Trigger an allowlisted GitHub Actions runbook instead and read its summary:

```bash
R=repos/Insomniac79ac/optcg-price-tracker
gh api -X POST $R/actions/workflows/ops-readonly.yml/dispatches -f ref=staging \
  -f 'inputs[runbook]=staging-state' -f 'inputs[request_id]=my-id'
```

- `ops-readonly` (no approval): `staging-state`, `verify-lossless`, `storage-rates`, `fleet-vs-receipt`,
  `official-images-status`, `db-diagnostic`, `web-smoke`. Every DB read is `default_transaction_read_only=on`.
- `ops-write` (owner approves each run in the `staging-ops` Environment): `enqueue-remaining-50`,
  `approve-f1-batch`, `enqueue-capture-batch`, `plan-refresh-backfill`, `apply-migration`,
  `collector-redeploy`, `collector-sibling-on`, `collector-sibling-off`, `catalogue-import`, `yuyu-source-probe`, `snkr-parser-requeue`; dry run by default. Agents never approve a waiting run.
- Finding the run and reading its result: [docs/agent/OPS_RUNBOOKS.md](docs/agent/OPS_RUNBOOKS.md).

## Tests locally (cloud session)

Postgres 16 and Redis are preinstalled. Start Postgres and create a test database once:

```bash
pg_ctlcluster 16 main start
su postgres -c "psql -c \"create user opcg password 'opcg' superuser\"" && su postgres -c "createdb -O opcg opcg_test"
python3 -m venv /tmp/venv && . /tmp/venv/bin/activate
pip install -r services/api/requirements.txt -r services/worker/requirements.txt -r scripts/agent-state-requirements.txt pytest
pip install --no-deps ./packages/opcg_source_identity     # the API/worker conftest refuses a stale copy
```

- API: `cd services/api && TEST_POSTGRES_URL=postgresql+psycopg://opcg:opcg@localhost:5432/opcg_test REQUIRE_POSTGRES=1 python -m pytest -q`
- Worker: same variables, `cd services/worker && python -m pytest -q`.
- Agent/CI tooling: `python -m unittest discover -s scripts/tests -p 'test_*.py'`
  (ops runbooks also take `OPS_TEST_POSTGRES_URL`; guardrails: `-p test_claude_guardrails.py`).
- Web: `cd apps/web && npm ci && npm test -- --maxWorkers=2 && npx tsc --noEmit`.
- Redis (if a test needs it): `redis-server --daemonize yes`.

### Collector frontend workflow

- Use the CardPirate collector UI skill for public and collector-facing frontend work.
- Work in one visual tranche at a time.
- Write or update the tranche contract before implementation.
- Capture desktop and mobile screenshots before and after.
- Use the fresh visual-reviewer agent; the builder must not be the final grader.
- Functional tests alone do not prove visual completion.
- Do not claim live completion until the staging deployment and stable alias are verified.
- Run `/clear` between unrelated tranches.

See `docs/ui/ATLAS_LOOP.md` for the full process.
