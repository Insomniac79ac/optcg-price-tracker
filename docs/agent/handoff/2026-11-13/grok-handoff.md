# Grok CP engineer handoff, 2026-11-13 (night)

Written by the CP engineer at the end of its 13 Nov 21:15 MYT run. Staging head when written: 1c584a18. The newest coordinator handoff (docs/agent/handoff/2026-11-05/coordinator-handoff.md) and its owner and standing rules still apply.

## In flight overnight
- Mission 5 (#274) OP-18 catalogue import apply: ops-write run 43434421865 (catalogue-import, apply=true, scope op-18, expected_sha256 682bdead080301678191d631fbb848028fb1f9c9d63dc954e91c72d9acbe2ddb), waiting for owner approval. Dispatched 2026-11-13 13:31 UTC.
  - it re-captures the Bandai cardlist and refuses if the plan differs from dry run 43384095863 (for example a new image cache buster or OP-18 parallels appearing); then a new dry run is needed
  - it refuses without a Railway backup of the staging Postgres volume under 24 h, and in 02:00-06:00 UTC and 19:30-20:30 UTC
  - after it applies: OP-18 should exist on /releases with no date; the release-date data migration (branch grok/op18-release-date, local only) follows through a DATA PR, apply-migration dry run and apply, then the fleet revision pin PR
- #287 (draft, hold-for-owner): read-only diagnostic yuyu-mapped-urls. Needs the owner to add `- yuyu-mapped-urls` after `- yuyu-f3-aliases` in the diagnostic choice list of .github/workflows/ops-readonly.yml on that branch; the registry test fails until then. No collector release.

## Verified this run
- dry run 43384095863: success, 119 create rows (OP18-001 to OP18-119, base), one new release product, 0 conflicts, 0 needs-review; db revision 001d92ba8eb9
- Bandai OP-18 product page: release 2026-11-21; rarity list totals 127 plus 1 DON; the 8 not in the cardlist yet are 6 SP, 1 TR, 1 SEC
- fleet pins in docs/agent/STAGING_FLEET.json: both collectors 16e41d4c, revision 001d92ba8eb9

## Not checked
- staging Postgres backup age (no tool; the apply's guard reports it)
