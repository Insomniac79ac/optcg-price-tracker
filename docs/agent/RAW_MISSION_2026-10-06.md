# RAW staging mission: evidence constraint

The mission did not achieve stabilization or 60% operational coverage. The first
quantified coverage constraint is insufficient exact CardPrint evidence. A fresh,
SELECT-only recomputation with the established resolver gives an optimistic
mapping ceiling of **2,314 / 4,316 (53.6145%)**, even assuming source recovery,
capacity and guard-passing approval of every exact recommendation. Reaching 60%
requires **276 additional distinct uncovered exact identities** beyond that ceiling.
Ambiguous family matches cannot close this gap under the binding identity policy.

The refreshed mapping baseline is 2,254 variants (52.2243%), 199 with both mappings
(4.6108%), and 2,062 with neither. Operational coverage, defined here as an enabled,
unpaused source with nonblocked RAW work and a successful check within 24 hours,
was 1,751 (40.5700%) at 02:10 UTC; both operational sources: 0; operational
zero-source: 2,565. This includes confident no-listing and does not establish
recurring deadline compliance. No mappings were approved: first-source and
second-source gains are both zero.

Yuyu remains DEGRADED with 2,100 mappings. Latest completed shard executions took
71.73–103.37 seconds, with zero reported 403/429/challenge/identity errors and
settled claims/reservations. Over the last two hours successful refreshes cost
100.35 requests on average, maximum 103; average mapping runtime was 8.93 seconds.
The final budget observation had 4,777 requests remaining in its 9,000-request,
30-minute window. This is a point-in-time admission balance, not validated
expansion or deadline headroom. Eight-work turns leave overdue cohort tails;
no deadline policy, source budget, schedule, routing or concurrency was changed.

SNKRDUNK remains BLOCKED with 353 mappings and its persistent pause preserved.
All 22 identity quarantines remain fail-closed. Attempt 1875 / mapping 2230 was
denied on October 5 at 13:31 UTC after 299 admitted requests. Its homepage snapshot
25528 is HTTP 200; no product snapshot was captured. The retained structured
execution records two 403s, but that runtime did not log denied-request host/path.
The pause therefore cannot be attributed positively to the optional resources
excluded by later fixes, nor declared a proven widespread primary-source denial.
Current source recovery and post-unblock capacity are unverified. No speculative
unpause, source probe, browser evasion or manual source job was performed.

At the final 02:11 UTC state observation, RAW due-work comprised 1,883 checks within
23 hours, 130 between 23–24 hours, 418 older than 24 hours, and 22 never checked.
Due: 570; overdue: 440, including the 22 quarantines; backoff: 0; claims: 0;
reservations: 0; expired claims: 0; reservation mismatches: false. Yuyu had 349
older-than-24-hour checks; SNKRDUNK had 69. Sustained natural deadline compliance
and new live transition verification were not established by this mission.

Recurring Yuyu discovery completed 59 scope runs in the last 24 hours and added
zero candidates. It enumerated existing evidence and refreshed pending proposals;
the inspected latest runs ended naturally without pagination/budget truncation.
The recomputed proposal groups are: Yuyu 185 exact, 1,648 ambiguous, 220 unresolved;
SNKRDUNK 82 exact, 218 ambiguous, 23 release-unresolved. Only 59 Yuyu exact
recommendations and one SNKRDUNK exact recommendation cover currently zero-source
variants. Resolver stale classifications are zero; this does not make SNKRDUNK's
October 2 discovery evidence current live evidence. Exact approval readiness and
post-unblock source capacity are not asserted. The resolver reports 156 canonical
prints with no candidate evidence from either source; per-source counts are 190
for Yuyu and 3,659 for SNKRDUNK.

**PSA10 NOT READY.** Both sources lack demonstrated stable recurring RAW operation.
No PSA10 activation was performed.

Production was never accessed or changed. Exact identity guards, manual mappings
and quarantines were preserved; no ambiguous candidate was approved. No
historical Market Value rows, collector configuration, schedules or source budgets
were changed. Yuyu sale/public/history/index/Market Value policy and the prohibition
on substituting struck former prices remain unchanged. This mission did not
repeat the live promotional-price endpoint audit, so policy preservation is not
presented as fresh end-to-end validation.

Evidence: `CURRENT_STATE.yaml`, its content-addressed JSON, the current resolver
report, read-only inspection, retained denial logs and machine-readable mission
result under `docs/agent/evidence/`. State-generator tests: 17 passed. The mission
stops at the demonstrated exact-evidence ceiling and unresolved denial provenance;
it does not label the supplied or refreshed baseline healthy.
