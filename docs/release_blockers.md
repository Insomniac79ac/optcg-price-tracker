# Release blockers - v1.0.0-rc.1

Tracked list of issues found during the Phase 11 release-candidate audit (see
`scripts/release_candidate_audit.sh` and `docs/release_candidate_report.md`) that could affect the
`v1.0.0` tag decision. Add a row whenever the audit (or manual QA) turns up something worth
tracking - not every `WARN` from the audit script needs a row here, only the ones a human decides
are actually worth tracking to resolution.

| ID | Severity | Area | Issue | Status | Owner | Notes |
|----|----------|------|-------|--------|-------|-------|
| - | - | - | No known blockers yet | - | - | - |

## Severity definitions

- **blocker** - must be fixed before tagging `v1.0.0`. Data loss, a broken migration, a secret
  committed to git, or a route that's completely down.
- **high** - should be fixed before tagging, but a same-day follow-up patch release is an
  acceptable fallback if there's a real reason to ship now anyway.
- **medium** - worth fixing soon, but doesn't block the tag. Cosmetic-but-confusing UI issues,
  a non-critical admin page returning a warning status, missing-but-not-required documentation.
- **low** - nice to have. Polish, minor copy issues, optional tooling gaps.

## How to use this table

1. When `scripts/release_candidate_audit.sh` reports a `WARN`, decide whether it's just noise (a
   route the script guessed at that never existed, e.g.) or a real gap worth tracking. Only the
   latter gets a row.
2. Give it an ID (`RC-1`, `RC-2`, ...), a severity from the table above, and the area it affects.
3. Update `Status` as it moves (`open` -> `in progress` -> `fixed` -> `verified`).
4. Before tagging `v1.0.0-rc.1`, every `blocker` row must be `verified`. `high` rows should be
   `verified` or have an explicit, written reason for shipping anyway in `Notes`.
