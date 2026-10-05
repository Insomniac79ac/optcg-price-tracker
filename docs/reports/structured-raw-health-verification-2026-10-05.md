# Structured RAW staging operational health

Observed 2026-10-05, staging only. Production untouched. No credential replacement,
configuration/schedule/budget/concurrency changes, mapping changes or manual source
requests were performed for this verification.

## Credential and native merge

PR #40 passed policy-gate and engineering-gate and merged through native auto-merge
at `65ff5fd1a35803c8161c4f38d3af4f64e30a085e`. Follow-up native merges #41 and #42
completed bounded collector rollout recovery. The current probe uses only
`query { projectToken { projectId environmentId } }` with Project-Access-Token,
and the Railway 5.62.1 destination-pinned `status --json` CLI operation with
RAILWAY_TOKEN populated from the existing STAGING_RAILWAY_TOKEN.

[CI credential receipt](../agent/evidence/raw-health-credential-verified-2026-10-05.json)
verifies the exact project `c613898d-bf03-43a6-8813-761f72e1c00a` and staging environment
`05d1eac2-510d-4bd3-999e-fea9ead766b7`. No account/workspace token was introduced
or substituted into the capability gate. Token values were never retained.

Official syntax checked 2026-10-05 against installed help and
[Railway CLI documentation](https://docs.railway.com/cli),
[status](https://docs.railway.com/cli/status), and
[Project Token deployment support](https://docs.railway.com/cli/deploying).
The ten existing probe regressions cover correct identity, wrong project and
wrong environment, HTTP denial, CLI success, sanitized CLI usage failure,
unrelated-query exclusion, transport and secret redaction. The current command
syntax succeeds with the scoped token; no unrelated administrative command is
used to judge its validity.

## Rollout and natural operation

[Rollout receipt](../agent/evidence/raw-health-rollout-verified-2026-10-05.json)
records all nine Yuyu shards (including shard-4-v2) and the SNKRDUNK collector
successfully deployed at exact source
`4df389f6f4c5db71eb0ef185584564a1563f7e09`, completed 16:33:35 UTC.
Live provider status and persisted run revision/deployment IDs agree.
Schedules and start-command hashes remain unchanged.

[Read-only state evidence](../agent/evidence/staging-state-8dcfbf959cb15f6a.json)
contains paired start and finish envelopes for every intended collector from the
subsequent 21:06–21:33 UTC scheduled cycle, hours after deployment. All ten have
zero remaining claims/reservations, overruns, duplicate requests and wrong-shard
work. SNKRDUNK holds its singleton, claims/attempts zero work, and its persistent
source-denial pause remains true. Identity quarantine remains 22 mappings.
Provider trigger/image/scheduled-at provenance remains unknown; scheduled origin
is inferred from unchanged cron operation and subsequent cycle timing, not
invented in the envelope or CURRENT_STATE. No Run Now/source job was triggered.

Latest outcomes correctly expose five Yuyu transient failures and five zero-work
runs (four Yuyu plus paused SNKRDUNK). These executions have zero listed,
no-listing, raw snapshots and accepted observations. Existing authoritative
24-hour aggregates separately record Yuyu captured/failure and SNKRDUNK
captured/no-listing/source-denial outcomes. Earlier successful checks are not
presented as new successful structured runs. No source requests were forced to
obtain success-shaped evidence.

At the 21:37:02 UTC snapshot, Yuyu is DEGRADED with deadline misses, due deficit,
backoff and transient failures. SNKRDUNK is BLOCKED with its persistent pause,
never-checked quarantine and overdue work. Both deadline compliance values are
not_met. RAW due-work is BLOCKED: eligible 2453; within 23h 1999; 23–24h 72;
over 24h 360; never checked 22; due 454; overdue 382; backoff 17; claims 0.
No source is relabeled HEALTHY to complete the instrumentation mission.

## Delivery verification repair

Collector-only recovery commits did not redeploy the API because of its existing
watch paths. The API is SUCCESS at `65ff5fd1a35803c8161c4f38d3af4f64e30a085e`,
which contains structured health. Earlier delivery incorrectly expected the
collector recovery merge SHA for this independently deployed service. The mission
now pins the exact observed API commit; destination checks remain strict.
The verification-only follow-up selects no collector uploads. It retains the
completed rollout receipt rather than causing another deployment or source run.

CURRENT_STATE is regenerated from live, fingerprinted read-only PostgreSQL and
pinned staging provider evidence. Source pause remediation and genuine freshness
recovery remain separate operational missions. The conservative deployment
provenance blocker reflects distinct independently deployed commits, and runtime
image/trigger unknowns remain explicit.
