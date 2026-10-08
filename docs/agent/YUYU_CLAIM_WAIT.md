# Bounded Yuyu claim contention recovery

The shared four-claim limit remains authoritative for every Yuyu consumer and
work kind. An ordinary sharded collector may retry an empty claim only when the
budget-locked refusal explicitly reports that limit and affordable, eligible work
exists for that shard. Six five-second waits bound each collision to thirty
seconds. Each wait releases the transaction; each retry checks ownership and
uses the original queue locks, source pause, budget, lane fairness, shard,
reservation and lease rules. A retry cannot outlive the existing execution
deadline plus the mapping runtime allowance. Other empty/refused claims stop
immediately. Waiting makes no source request and acquires no work lease.

This release changes no cron, request budget, pacing, maximum work, price or
physical-card identity policy. The original nine modulo-nine shards retain their
thirty-minute schedules, sixteen-work bound and shared9000/1800 request envelope.
SNKRDUNK retains its singleton,3100/1800 envelope and original schedule. All RAW
dictionary writers remain OFF. Completed sitemap intents3676/3677 and previous
RAW recovery35175 must never replay.

The original reader verifier remains unchanged. It requires all nine shards to
share one declared profile, the existing original or explicitly declared
ten-minute schedules, and refuses changed phases, mixed schedules and larger
work bounds. No profile is activated by this code release.

Fixture validation covers slot release, continued contention, insufficient
deadline, disabled source before/during retry, lost ownership, unsharded callers,
empty queues, unaffordable work and wrong shards. It asserts no invented RAW or
price success, no source HTTP and no excess active claim/reservation.105 queue,
both-source adapter, retry and health tests passed before the declaration-only
initial implementation;10 contention cases passed after the named retry
constants were added. Native full engineering checks remain
required for delivery.

The offline72-hour forecast uses exact observed due times, the original lane
cycle, per-RAW reservation300, measured56-request proxy, startup proxy302seconds,
uniform stress latency603.164/16seconds, and unchanged budgets/pacing/max16.
The corrected model keeps each service busy throughout scheduled startup AND
execution, as required by Railway same-service overlap behavior. The earlier
execution-only model undercounted overlap and is retained as superseded evidence.
With thirty-second claim wait and integer-minute phases, ten-minute scheduling
forecasts zero misses for the current population,100 phased additions, and a
separate100-capture scenario spaced600seconds, but61 misses for607 additions.
Five-minute scheduling forecasts166 misses with607 additions; it is not a
justified capacity solution. Modeled concurrent claims remain<=4 and request
usage below9000. These forecasts do not prove future capacity: populations are
phased, uniform stress is not every product timing out, startup is an approximate
proxy, and capture load is separate from the added recurring population.
Retained inputs and both models are in the capacity75-resumed handoff. No cadence
expansion may rely on the superseded forecast.

A cadence activation is a separate AMBER action. It must first refresh exact
staging identity, all ten installed natural components, queue/deadline state,
budgets, source denials, reservations, physical growth and recovery artifacts.
Its manifest must bound the extra empty startup/log overhead (five-minute is at
most2592 launches/day versus432 under the original schedule, and same-service
overlaps may be skipped), retain all original source envelopes and provide an
executable reversal to each original cron. Activation requires natural busy
window evidence, bounded retries, all-source RAW recurrence within24hours and
no leaks/denials before any NEW100 expansion. Compression/storage continuity
must independently pass; scheduler modeling does not waive storage safeguards.

PR79's full engineering checks passed and it merged as
`a6c080902895922ba60c4161d417255006b2bd1f`, but the fleet delivery guard refused its
GREEN manifest before any collector upload. The current release uses the
required AMBER fleet preflight; it installs PR79's bounded RAW body query together
with this retry. No classification guard or engineering check is bypassed.

Recovery is a native code revert, with all writer flags retained OFF and schema
`f9e5b4a8c012` preserved. The current verified collector recovery images are the
PR78 ten-service fleet, and the API source recovery is PR79. RAW, dependency
ledger, portable backup compatibility and historical published data remain
unchanged. Source denials, duplicate requests, identity/integrity failures,
ownership or reservation leaks, unexpected writer activation, increased deadline
misses or runtime regression stop the affected path and require bounded diagnosis
before expansion.
