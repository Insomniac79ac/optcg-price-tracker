# Plan: make every collector rollout receipt readable without a manual download

Status: PLAN ONLY (owner ask 2026-10-18 23:43Z). Nothing here is built.

## PLAIN SUMMARY

After a collector rollout, the receipt (`latest-collector-rollout.json`) only exists inside the
`staging-delivery-<sha>` CI artifact. Cloud sessions cannot download artifacts (the zip redirects
to blob storage, which the session proxy blocks), so checking the fleet against the newest
rollout needed the owner to download and upload the file by hand (PR #173, 2026-10-18). The fix
below lets the `fleet-vs-receipt` runbook fetch receipts itself inside GitHub Actions, and puts a
copy of each receipt where sessions can read it over REST. No collector, data or setting changes.

## Why not commit the receipt to `staging` from the job

`staging` takes no direct pushes (branch rules), and the delivery job would need a bypass, which
is a repository-settings change (owner's, RED-adjacent). A bot commit after every rollout also
starts a new CI run on `staging` and moves the head the next PR must rebase on. An automatic
follow-up PR per rollout adds a PR to merge by hand each time. Both cost more than they buy.

## Proposed change (one DATA-lane PR, `hold-for-owner`, merged by hand: it touches `.github/`)

1. **Receipt as annotations (sessions can read it).** In `ci.yml` `staging-automerge` and in
   `staging-delivery.yml`, after "Deploy mission-scoped staging collectors" (only when the
   decision is `full`), emit the receipt as `rollout-receipt i/n` notice annotations, chunked the
   same way as `ops-summary` (reuse `scripts/ops/run.py annotations`). The receipt holds service
   ids, deployment ids, digests, schedules and three non-secret flag values; it already goes
   through the same secret scan rules (`common.assert_clean`) before it is printed.
2. **Fleet check fetches receipts itself.** In `fleet-vs-receipt`, an empty `receipt` input means:
   list the last successful CI runs on `staging` whose `staging-automerge` job ran the deploy step
   (REST, `actions: read`), download their `staging-delivery-<sha>` artifacts inside the Actions
   job (the runner can reach blob storage), and compare each collector with the newest receipt
   that deployed it (the chain logic added in PR #176). A committed receipt path still works.
   `ops-readonly.yml` gains `actions: read` for the runbook job; no secret is added.
3. **Tests.** Annotation round trip of a real receipt (split and rejoin equals the file); receipt
   chain picks the newest per service; the fetch refuses a run that is not on `staging`, not
   from `ci.yml`, or whose artifact name does not match its head SHA.

## Effort and risk (ESTIMATE)

- About 150 lines across `ci.yml`, `staging-delivery.yml`, `ops-readonly.yml`,
  `scripts/ops/fleet.py` and tests. No collector service, Railway setting or database change;
  0 collector rollouts.
- Risk: the delivery job gains one print step after the rollout. A failure there must not fail a
  completed rollout, so the step is `continue-on-error: true` and only prints.

## Owner decisions needed before building

- Approve building it (and when).
- Confirm committed receipts under `docs/agent/handoff/` remain the record for past rollouts
  (PR #103 and PR #173 receipts stay where they are).
