# Bounded published SNKRDUNK discovery

This staging adapter accepts only explicit one-shot `snkr-published:` intents.
It retains robots, sitemap index, every advertised shard and inspected product
response before parsing. Published positions around current approved manually
verified anchors select at most20 products; no IDs are constructed. Existing
candidate URLs, all mapped/retained URL aliases and previously inspected identities are excluded. New rows are
unmatched metadata with null price and no mapping decision. Manual verification,
exact physical identity and RAW freshness gates remain separate requirements.

Bounds:12 anchors,12 advertised shards,100000 distinct URLs/shard,400000 total,
radius1..48,20 products,300 admitted requests including the existing homepage,
serial1.5s document pacing, existing180s mapping deadline and240s claim lease.
8MiB compressed/decompressed XML parser limit;2MiB product parser limit.
The SDK buffers before these checks. They are not hard download limits; oversized
responses remain RAW and fail closed. Benchmark measurement covers synthetic
parsing/planning only, not live HTTP capacity. Source singleton, ordinal admission,
no redirect/retry, browser callback settlement and PostgreSQL result fencing are
reused. No Worker runtime module is imported by the collector image.

Publication deploys only the existing staging SNKR service. No intents, source
requests, schedule/budget/config changes or database writes occur at publication.
New capture/discovery volume requires its own fresh AMBER preflight after strict
serialized delivery and actual natural runtime adoption. For one discovery intent,
require no currently actionable SNKR RAW backlog, no paused/disabled source,
>=300 unreserved requests, and2GiB storage reserve plus512MiB HTML/WAL/index
allowance. The latter is an operational allowance, not a hard transport cap.
Require next40min planned RAW demand multiplied by the observed24h maximum
RAW request cost plus300 to fit the unchanged3100 window. A peak run using2953
requests does not supply300 spare requests. This is an observed-cost capacity
guard, not a hard transport bound; admission still enforces actual requests.
Abort planning if any guard fails. Do not replay any completed scope or recovery.

Executable recovery preparation:

```sh
python scripts/prepare_snkr_discovery_rollback.py --output /tmp/snkr-discovery-rollback.patch
```

This generates and checks a local patch retaining the PR70 RAW dispatcher while
settling pending discovery with a zero-request `identity_refusal` result under
the existing claim/result fence. It blocks the intent without creating a source
check, clears its reservation and advances the normal claim fairness cursor.
Apply it in a separate isolated recovery branch, regenerate that PR's mission
manifest, and use PR/engineering-gate/native auto-merge/serialized strict delivery
with the same pinned SNKR service. Simply restoring a refresh-only dispatcher
can strand its cursor at an unsupported pending discovery lane. The checked
rollback avoids that starvation and lets later ordinary RAW work continue. Preserve all RAW, candidate evidence,
manual decisions and history. No data restore, deletion or job trigger is needed.
The retained prior source is1ddb234b8a0a51a2ad313359e22168182bf07dbd and prior
SNKR deployment446e3604-a969-42ac-8537-fb2cf94fbf0d. The generated patch was
validated with git apply --check and an executed generated dispatcher against
disposable PostgreSQL. The regression first reproduces the old cursor stall,
then verifies zero-request scope settlement, continued RAW dispatch, zero open
reservations and unchanged retained RAW/manual/candidate decisions. PostgreSQL
tests also verify retention, stale lease
refusal, singleton loss, replay refusal and late-denial rollback. A required source
denial commits the existing pause before any candidate writes. Do not clear it.

Recovery triggers: unexpected source requests outside this explicit lane,
candidate writes escaping a fence, identity/price/mapping writes, broad denial,
resource pressure, or a failing valid-input parser. Stop the affected lane and
publish recovery; do not weaken a guard to complete a scope.

Natural verification: first ordinary scheduled SNKR execution after delivery must
report the actual new installed component revision. Then, only if fresh safeguards
pass, plan one scope for the ordinary schedule, bounded at300 requests and20
products. Observe the next scheduled turn plus one cycle for settled claims and
reservations. Verify retained raw lineage, unmatched candidate IDs and inspected
identities, actual request costs and runtime, zero price/mapping/freshness writes,
unchanged source schedule/budget and preserved existing evidence. Mapping and
operational gains are zero until separately reviewed exact proofs and natural
RAW checks exist. Production RED; PSA10 OFF.
