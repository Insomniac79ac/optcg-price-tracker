# Generate the staging observation

Run from a full repository checkout with GitHub, Railway and Vercel CLIs already
authenticated for the existing staging projects:

```sh
python -m pip install -r scripts/agent-state-requirements.txt
python scripts/generate_staging_state.py --live
```

This updates `docs/agent/CURRENT_STATE.yaml` and writes a content-addressed JSON
artifact under `docs/agent/evidence/`. Review and commit both. It does not commit,
push, schedule itself, deploy, scrape a source, or write to a database. An alternate
`--output /tmp/staging-state.yaml` is useful for inspection without changing the
tracked snapshot. Provider CLI help/live schemas and official references were
checked on 2026-10-04; follow the operating contract's documentation-check standard
when those interfaces change.

Offline replay uses a **generator-produced** evidence artifact (the original
manual `2026-10-04-staging.json` predates this envelope):

```sh
python scripts/generate_staging_state.py --fixture path/to/staging-state-HASH.json --output /tmp/replayed-state.yaml
python -m unittest discover -s scripts/tests -p test_generate_staging_state.py -v
```

Replay is explicitly labeled `collection_mode: fixture` and cannot overwrite the
canonical tracked `CURRENT_STATE.yaml`. Its original observation time is retained;
replaying data does not make it current. No live commands run in fixture mode.

## Identity, consistency and failure behavior

The live collector pins the repository, staging Railway project/environment and
Postgres service IDs, and the existing Vercel staging project ID. It verifies
Railway environment/project identity before fetching freshly scoped database
credentials into memory. It resolves the current TCP proxy through the API;
it never trusts an old DSN or saved endpoint. No production override exists.

The existing database fingerprint checker validates schema, named constraints,
lineage columns, nonempty identity tables and the reviewed checkout's migration
heads. Fingerprints and aggregate queries share one PostgreSQL repeatable-read,
read-only transaction with a 30-second statement timeout. The fixed query source
is [staging-state-read.sql](evidence/staging-state-read.sql). No migrations, job
triggers, source HTTP requests or data mutations are available through the tool.

Required Railway/Git/database failures return nonzero and preserve the previous
snapshot. A Vercel read failure permits a partial snapshot with unknown frontend
metadata and an explicit completeness blocker; a wrong Vercel project is refused.
Provider error bodies and connection diagnostics are not printed, since they may
contain credentials. Inspect provider authentication separately when necessary.

Only allowlisted aggregate and deployment fields enter evidence. Credentials,
arbitrary service commands, free-text failure reasons, customer records and
personal platform metadata are excluded. Evidence is written before an atomic
snapshot replacement and referenced by SHA-256. An interrupted publication may
leave an unreferenced evidence file, but cannot truncate the previous snapshot.
Concurrent invocations are not scheduled by this tool; callers should run one
refresh at a time.

## Reading the result

Schema version 2 keeps the requested top-level sections and adds collection mode,
evidence hashes and explicit reasons for unknown values. Per-service deployment
identity lives under `staging.services`; the active frontend artifact is under
`staging.frontend`. The remote staging branch SHA is not the CLI collector's
reported SHA or a verified runtime hash.

Coverage counts active, verified CardPrints and eligible Yuyu/SNKRDUNK mappings,
including quarantined refresh work. It is not proof of operational coverage.
Freshness keeps successful checks, historical price age and no-listing separate.
A bad instantaneous deadline count is `not_met`; a clean instant remains `unknown`
for sustained compliance. Source budgets are observed configuration, not safe
capacity measurements. Policy flags remain constraints, not audit verdicts.

Admission versions, effective runtime batch limits, public PSA10 activation and
continuous discovery health remain `unknown` until direct evidence is collected.
The tool does not infer them from defaults or old reports. Discovery and validation
are counted separately. Historical Market Value gaps and mapping duplicates become
visible blockers; generating state never repairs data or fabricates receipts.

The mission is recorded in [STATE_GENERATOR_MISSION.md](STATE_GENERATOR_MISSION.md).
