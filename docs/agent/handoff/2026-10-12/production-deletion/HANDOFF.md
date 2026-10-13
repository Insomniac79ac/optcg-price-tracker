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

- `evidence/pr108-delivery/`: PR #108 CI receipts (Vercel Git-fetch failure);
  `verify-3ec8a7a-after-redeploy.json`: verifier green after the owner-authorized redeploy.

Pending for the next session:
- Land this record with the next docs change (branch
  `docs/production-deletion-pr108-fix-20261012`, no PR opened).
- `scripts/staging_db_read_check.py` comment (port 21415 was the production proxy,
  now removed): folded into collector-v1 S1.
- Staging `ADMIN_TOKEN` rotation: collector-v1 S5 (owner decision 2026-10-12).
