# Card Pirate autonomous-development operating contract

Adopted: 2026-10-04. Target: staging. Repository: `Insomniac79ac/optcg-price-tracker`.

## Mission authority

A human authorizes the mission, its boundaries and success metrics. The agent
owns decomposition, implementation, tests, staging delivery, observation of
natural operation and bounded fix-forward work until the mission is complete.
Use [MISSION_TEMPLATE.md](MISSION_TEMPLATE.md); do not request approval between
implementation steps. Reporting milestones are updates, not approval gates.
Branches, commits, pushes, PRs and merges into staging needed by an active
implementation mission are authorized, subject to checks and explicit mission
restrictions. Never merge a PR the user asked to leave open.

This contract supersedes the former per-action staging approval list in root
[AGENTS.md](../../AGENTS.md). Older runbooks and reports saying “separate approval
required” are historical scope restrictions, not new approval gates for an
otherwise authorized mission. Their technical prerequisites still apply.
Explicit current user restrictions and higher-priority instructions prevail.
[INVARIANTS.md](INVARIANTS.md) binds every authority level. State files and prior
successful operations are evidence, not authorization to expand a mission.

This initial contract PR is documentation/state tooling only: no application
deployment, staging mutation, production access or automatic merge is authorized.
Leave it open for initial human review. The operating permissions below govern
subsequent authorized staging missions after adoption.

## Authority levels

Classify each action by its actual impact. Where categories overlap, RED overrides
AMBER, and AMBER overrides GREEN. “Reversible” requires an executable recovery
path; a hopeful redeploy is not a rollback plan. Unknown impact must be investigated
before mutation, rather than guessed safe.

### GREEN — AUTONOMOUS

Proceed without human approval within the active mission:

- Normal code changes, tests, regression tests, refactors and documentation.
- Branches and PRs, including the Git work described above.
- Staging deployments, service restarts and redeployments.
- Reversible staging configuration changes within the established safety envelope.
- Fix-forward debugging and resolving bounded implementation defects.
- Exact source-mapping approvals that pass the established identity guards.
- Bulk staging operations explicitly serving the mission, except AMBER cases below.
- Due-work and discovery operation under existing admission, locking and budgets.
- Source scheduling/budget tuning within documented, measured safety envelopes.
- Necessary, reversible staging database writes covered by the mission.
- Updating machine-readable project state with verified evidence.

An isolated failure does not stop the whole mission. Skip or quarantine bad
records, preserve evidence and continue independent work where integrity permits.
Quarantine is reversible isolation from use, never permission to delete evidence,
weaken identity validation or invent a replacement match.

### AMBER — AUTONOMOUS WITH PREFLIGHT + ROLLBACK

Proceed without waiting for human approval **after** all safeguards pass:

1. Calculate impact: exact environment/resources, record counts, dependencies,
   source requests, concurrency, runtime, cost and blast radius.
2. Verify backups and rollback where applicable: recovery artifact, compatibility,
   restore/reversal procedure and a validated recovery path. Record why a backup
   is not applicable when no persistent state changes.
3. Document the expected mutation: before/after state, bounded manifest or SQL
   selection, idempotency, failure thresholds and rollback triggers.
4. Establish post-change verification: invariants, expected counts, deployment
   identity, health checks and a natural-operation observation window tied to the
   relevant cron/queue cycle. Identify the evidence that will prove completion.

AMBER includes:

- Additive/reversible database migrations.
- Large bulk mapping approvals (identity guards apply to every row).
- Significant staging cron changes and source-budget changes that alter the
  established envelope.
- Substantial source-volume increases.
- Service replacement/cutover.
- Reversible historical-data repairs outside immutable published history.
- Enabling an already-built major subsystem, including due-work/discovery.
- Infrastructure changes within the existing staging architecture.

Source-budget tuning inside an already measured envelope is GREEN; expanding or
establishing the envelope is AMBER. “Large” and “significant” are impact-based:
use AMBER when a change affects a meaningful share of coverage, capacity,
concurrency, recovery effort or cost. Do not split bulk changes to evade preflight.
Record the measured bounds; current config values alone are not proven capacity.

If safeguards fail, stop the affected action. Repair a bounded preflight failure
and rerun it autonomously; continue independent safe work. If all safeguards pass,
proceed without asking the user. A failed safeguard is not permission to bypass it.
Escalate when safe recovery needs a human decision, mission assumptions no longer
hold, or RED applies. Unknown rollback or impact is a failed preflight.

### RED — HUMAN DECISION REQUIRED

Stop and ask before:

- ANY production deployment or change; production access also requires explicit
  authorization under the repository boundary.
- Destructive or irreversible database migrations.
- Deleting significant user/business data.
- Rewriting immutable historical published data, even if a backup exists.
- Changing Card Pirate pricing methodology.
- Changing Market Index / Market Value economic meaning.
- Weakening exact-card identity validation.
- Auto-approving ambiguous identity matches.
- Changing Yuyu promotional-price product policy.
- Exposing previously private customer data.
- Changing authentication, security or secrets policy.
- Adding a materially new paid external service or significant recurring cost.
- Changing core product positioning or brand strategy.
- Actions with meaningful legal/compliance implications.

Prepare the concrete decision, impact, evidence and safe alternatives first.
Do not execute the dependent action while waiting. A general mission does not
waive RED boundaries. Explicit human authorization must identify the decision
and scope; an invariant change must be recorded in [DECISIONS.md](DECISIONS.md)
and reconciled with the contract before implementation.

## Fix-forward rule

**An isolated operational defect is NOT a mission stop condition.** For a bounded
issue, autonomously:

1. Diagnose using retained raw evidence and current state.
2. Write regression coverage reproducing the defect with mocks/fixtures first.
3. Implement the bounded fix.
4. Deploy to staging within mission authority.
5. Observe natural operation and verify recovery and invariants.
6. Update state and continue the mission.

Hard-stop the affected execution path for:

- Wrong physical-card identity.
- Duplicate or uncontrolled source requests.
- Database integrity risk.
- Widespread source blocking/rate limiting.
- Security issue.
- Production impact.
- An invalidated mission assumption.
- A RED-policy decision.

Contain the risk immediately with an authorized reversible pause/quarantine; never
continue unsafe requests or writes. Stop the whole mission when impact cannot be
isolated or its assumptions no longer hold. Safe diagnosis, regression work and
independent tasks may continue. A guarded refusal of an ambiguous candidate is
expected quarantine, not proof that a wrong identity was written. Resume an
isolated path only after its guard is verified; obtain human decision for RED or
changed mission scope.

## Evidence and completion

Verify the target environment before each external mutation. Preserve raw payloads
before parsing, exact identity guards, source-wide admission/locking and bounded
retries. Never mix unmetered legacy jobs with admitted due-work for one source.
Measure source capacity from natural operation, including request cost, latency,
denials, deadlines, leases and restart behavior. Mapping counts, deployment
success and one manual run do not prove healthy operational coverage.

Report meaningful milestones and defects without waiting for replies. Record the
commit/deployment identifiers, relevant tests, before/after state, natural-cycle
receipts and unresolved limits. Update [CURRENT_STATE.yaml](CURRENT_STATE.yaml)
with UTC observation times and reproducible evidence; use `unknown` for unverified
values. Re-read live state before acting on this snapshot. Completion requires
observed success metrics, not fabricated receipts or optimistic status labels.

## Development instruction standard

Before using technical or deployment instructions whose behavior may have changed,
check current official documentation, the installed tool version and local
`--help` or the live API schema. Verify environment-selection flags, request
methods, side effects, branch triggers and rollback behavior. Historical CLI/API
syntax in reports is not authoritative. Record the official reference and check
date in the execution evidence. If docs and installed behavior differ, investigate
with read-only inspection before mutation.

Official starting points (checked 2026-10-04):

- [Railway CLI](https://docs.railway.com/cli),
  [database connections](https://docs.railway.com/cli/connect) and
  [SSH](https://docs.railway.com/cli/ssh).
- [Vercel Git deployment configuration](https://vercel.com/docs/project-configuration/git-configuration).
- [GitHub PR creation](https://cli.github.com/manual/gh_pr_create).

Platform labels alone do not establish business environment: the Vercel project
`optcg-price-tracker-staging` uses its platform `production` target for the staging
alias. Verify project ID, Git branch, alias and backend destination together.
This does not authorize access to Card Pirate production.
