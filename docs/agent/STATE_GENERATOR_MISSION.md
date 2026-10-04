# MISSION

Generate the machine-readable staging baseline repeatably from current, verified,
read-only evidence. This implements the staging-state tooling requested after
PR #34 adoption. The existing snapshot contract supplies the field scope.

# SUCCESS METRICS

One command generates `CURRENT_STATE.yaml` and a linked, hashed, sanitized evidence
artifact. Identical fixture input gives identical output. Production targets,
unverified database identity and inconsistent counts cannot replace the current
snapshot. Missing optional evidence stays explicitly unknown. Offline regressions
and a live read-only staging run pass. No application runtime changes.

# IN SCOPE

Local CLI/state tooling, fixture tests, CI for those tests, usage documentation,
and read-only staging/GitHub/Vercel inspection. Separate repository state from
reported deployment provenance and actual runtime verification. Report operational
and integrity blockers without performing repairs or approving mappings.

# OUT OF SCOPE

Production access, application changes, database writes/migrations, collection or
discovery triggers, source requests, infrastructure configuration, scheduled
execution and freshness/capacity remediation. No automatic assertion that a queue,
mapping or deployment represents healthy operational coverage.

# HARD STOPS

Apply AUTONOMY_POLICY.md and INVARIANTS.md. Refuse a mismatched staging project,
wrong database fingerprint, read/write transaction, malformed required evidence,
or secret-bearing output. Preserve the prior snapshot on failure. Never bypass a
migration fingerprint mismatch or infer missing receipt/runtime evidence.

# CURRENT BASELINE

PR #34 adopted at staging commit `95f234b62c630a4daca0e27805edd7a0d833e17c`.
The 2026-10-04 baseline contains 4,316 verified variants and 52.2243% mapping
coverage, with incomplete freshness and 22 identity-quarantined SNKRDUNK items.
The frontend is a separately deployed revision; reverify all values at execution.

# REPORTING MILESTONES

Report fixture validation, live read-only generation, output/evidence verification,
and delivery status. These are evidence updates, not approval gates.
