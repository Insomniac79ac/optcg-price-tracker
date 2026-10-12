# Railway production deletion: evidence (2026-10-12)

STAGING untouched. Owner performed every Railway/GitHub click; the agent only read.
Full record and before/after table: `docs/agent/plans/production-deprecation/INVENTORY.md` §8.

- `tools/baseline.py`: read-only staging baseline (Railway reads, read-only Postgres
  session, Redis PING, `/health`, TCP state of the old production ports).
- `evidence/baseline-before.json` (08:27Z), `baseline-after-proxies.json` (09:35Z),
  `baseline-after-env.json` (09:50Z).
- `evidence/verify-before.json` (08:43Z), `verify-after-env.json` (10:03Z): staging verifier, green.
- `evidence/ports-after-proxies.txt`: protocol-level port probe.
- `evidence/production-env-tombstone.json`: soft-deleted environment record.

- `evidence/pr107-delivery/`: PR #107 CI delivery receipts; `baseline-after-pr107.json`,
  `collector-records-after-pr107.json`: post-merge checks.

Pending for the next session:
- The outcome PR's own delivery receipt.
- `scripts/staging_db_read_check.py` comment (port 21415 was the production proxy,
  now removed): separate small PR outside quiet windows, or with the next release.
- Staging `ADMIN_TOKEN` rotation: owner decision.
