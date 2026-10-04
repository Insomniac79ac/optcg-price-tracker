# Staging baseline verification — 2026-10-04

The database snapshot in [CURRENT_STATE.yaml](CURRENT_STATE.yaml) was read at
**2026-10-04 08:42:38 UTC**. Supporting aggregate results and selected deployment
metadata are in [the evidence artifact](evidence/2026-10-04-staging.json).
These are observations, not a healthy-state declaration or a deployment manifest.
No application code, mapping, database row, schedule or hosted service was changed.

## Method and reproducibility

- Read the GitHub `staging` branch directly: `e018d903f57b89ab1f0f9dc20641bbe43feed868`.
- Read Railway staging service commands, cron schedules, deployments and selected
  nonsecret settings. Project PR deployments and bot PR environments were false.
- Read the Vercel staging project, its Git link and currently assigned frontend.
  Its platform target named `production` belongs to the staging project and alias;
  it is not the Card Pirate production environment.
- A fresh database SSH tunnel failed; direct SSH also reported no available key.
  No key was created and no security configuration changed. Resolved the current
  staging Postgres TCP proxy through Railway's API instead. Read credentials into
  memory only; never printed or committed them.
- Connected with server-enforced read-only transactions and a 30-second statement
  timeout. All checks in [staging_db_read_check.py](../../scripts/staging_db_read_check.py)
  passed on that connection, including migration `c4e8a1d7b902`, schema/constraint
  fingerprints and nonempty identity tables. Queries then ran in a read-only,
  repeatable-read transaction. The checker was loaded from collector source
  revision `41966076ea6988f38436a3aab953d8bba896c7d8`, whose migration head matches
  this live database; the remote staging branch has older migration knowledge.
- The [aggregate SQL](evidence/staging-state-read.sql) documents the actual read
  definitions. For a refresh, first independently establish the staging project,
  environment and current endpoint, verify fingerprints against the relevant
  reviewed migration set, and then execute only on that validated connection.
  Do not change an expected revision just to make a failed guard pass. The SQL
  contains no credentials and cannot itself prove environment identity.
- GET `/health` reported `app_env=staging`, database/Redis connected. GET
  `/analytics/market-value?window=all` agreed with persisted publication date
  `2026-10-03`; both intentional gap dates were absent. Responses were saved
  locally before extracting the small aggregate evidence committed here.

Official Railway connection/SSH docs, Vercel Git configuration and GitHub PR
creation docs were checked on 2026-10-04, along with installed help and Railway's
live query schema. Links are in the
[development instruction standard](AUTONOMY_POLICY.md#development-instruction-standard).

## Findings and limits

The catalogue contains **4,316 active verified CardPrint variants** (2,710
CanonicalCards). Eligibility counts only active, approved, nonsuperseded exact-print
mappings to Yuyu or SNKRDUNK; SNKRDUNK also requires manual verification. There are
2,100 eligible Yuyu mappings and 353 SNKRDUNK mappings: 2,254 variants have at least
one source, 199 have both, and 2,062 have neither. Coverage is 52.2243%.

Mapping eligibility includes 22 SNKRDUNK refresh items blocked for confirmed
identity-validation refusals. Do not present these as operationally healthy.
Two groups returned by an initial broad duplicate query have NULL CardPrint IDs
(legacy mappings); **zero** duplicate active groups have a known exact print/source.
Legacy rows are excluded from coverage and are not silently repaired by this PR.
The database's current-listing uniqueness constraint is not a general uniqueness
constraint on `(card_print_id, source_id)`; the invariant still requires guarded
approval and checks, not an assumption that the schema alone enforces it.

Nine Yuyu shards and SNKRDUNK have configured due-work commands and half-hourly
staging crons. Recent database attempts prove execution; they do not independently
prove continuous future health. Yuyu has 59 pending discovery scopes and 66
completed discovery attempts in the preceding 24 hours; continuous discovery
consumer health remains unknown. SNKRDUNK has 22 completed validation attempts,
which must not be described as discovery completions.

Full 24-hour freshness is not met. Yuyu has 63 raw checks older than 24 hours and
209 with no successful check; SNKRDUNK has 193 with no successful check. SNKRDUNK
has 116 no-listing states and one retained price older than 24 hours. These counts
keep price age distinct from check age. They include blocked refresh work and do
not measure a sustained full-cycle deadline distribution.

Raw is the only live freshness category; no `psa10_asking` observation exists.
PSA10 implementation in a reported deployment revision is not proof of activation
or customer-facing rollout. Those live states remain `unknown`.

Bounded `due_run_start` log reads for current Yuyu shard 0 and SNKRDUNK deployments
returned no records. Yuyu admission versions and SNKRDUNK's effective runtime batch
maximum are therefore `unknown`. SNKRDUNK has no service override for
`BATCH_MAX_MAPPINGS_PER_RUN`; the reported source defaults to 70, but that is not
an independent runtime measurement. Source-budget limits are live configuration,
not measured safe capacity. Yuyu promotional exclusions are binding policy and
present in the API revision; this audit did not retest every public price/history
path and records that limit explicitly.

The deployed fleet differs from remote `staging`: the API is at `e018d90`, the
frontend at `0211aa6`, while collector CLI messages report `4196607` with no Git
commit metadata. Runtime collector hashes are unknown. Future deployment missions
must reconcile this divergence before choosing a source revision; this PR cannot
serve as permission to redeploy the older branch over newer collectors.

## Contract reconciliation and PR boundary

Root `AGENTS.md` previously required approval for routine staging changes. Its
new entry point delegates to the contract and retains explicit user scope limits
and the production gate. Historical rollout approval holds in older reports do
not override a subsequent authorized mission, but technical prerequisites and
identity quarantines remain binding. No unresolved product-policy decision is
required to create this contract.

To honor “do not deploy application changes,” the only non-document configuration
edit adds `docs/card-pirate-autonomy: false` to the existing Vercel
`git.deploymentEnabled` exclusions. This prevents this PR branch from deploying;
it does not alter staging's runtime or other branch rules. Railway PR deployment
settings were read, not changed. The PR targets `staging` and remains open for the
one initial review. No merge or application deployment is part of this task.

Validation: parsed YAML/JSON, checked snapshot arithmetic against captured SQL
results, checked required mission sections and policy boundaries, resolved local
Markdown links, reviewed the diff for application changes/secrets, and ran
`git diff --check` and the repository's secret-file check. Application tests are
not needed for these documentation and branch-exclusion changes.
