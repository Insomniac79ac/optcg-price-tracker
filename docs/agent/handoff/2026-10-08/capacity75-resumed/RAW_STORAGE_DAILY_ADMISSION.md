# Bounded renewable staging RAW storage

This delivery keeps every writer OFF and does not establish sustained storage
savings. It adds a separately selectable `RAW_DICTIONARY_STORAGE_MODE=daily-v1`
behind the existing `RAW_DICTIONARY_STORAGE_ENABLED` and exact staging guards.
The default remains the original global, all-time 200-row canary, including the
16 previously consumed rows and the recovered row. No prior intent is replayed.

Daily mode admits at most 8,192 encoded snapshots and 32 MiB of encoded bodies
per UTC transaction day, across both sources under the original nonblocking
transaction advisory lock. The body must fit the remaining byte allowance.
Recovery does not refund charges. A rolled-back insert also rolls back its
ledger charge. Admission exhaustion, lock contention, or insufficient savings
retains newly fetched plaintext under unchanged ownership and source budgets.
These ceilings are storage admission limits, not observed throughput or a
90-day volume forecast. Codec, full source URL equality, hashes, dependencies,
RAW-before-parse commits, CardPrint identity, and price semantics stay guarded.

Migration `f9e5b4a8c012` adds only a UTC ledger-time index and a compact scoped
RAW lookup index. The latter indexes source/parser/URL hash/ID for HTTP 200;
the writer also compares the entire URL. Building it does not inspect TOAST
bodies. Lookup examines at most 32 recent scoped bodies, then the oldest
retained scoped plaintext anchor. Every encoded child has an older plaintext
same-scope dependency. A page that no longer compresses efficiently remains
plaintext and becomes a recent anchor. The indexed daily ledger scan depends
on one day's admitted rows, rather than the lifetime ledger size.

AMBER delivery preflight is in
`evidence/raw-storage-daily-preflight-20261008.json`. The existing serialized
delivery helper accepts only the individually allowlisted parent/revision/path
and reviewed checksum; writer-OFF, destination, schema, lease, lock and statement
timeout guards remain. The original e8 transition remains independently tested.
The new migration does not rewrite raw bodies or dictionary ledger records.
Both new indexes can be removed after writer-OFF and application rollback,
while retaining e8 dependency protection, codec readers, portable backup19,
all captured bodies and immutable price/check/publication history.

Activation is separate from delivery. It requires current natural component
receipts, all old reader/backup protections, staging APP_ENV, a fresh snapshot,
source safety/volume/rollback preflight, and an ordinary SNKR writer sample.
Measure lossless original lengths/digests/lineage, actual physical bytes and
index/ledger overhead, codec/base lookup costs, admission skips, denials,
leases, runtime, and successful RAW recurrence. Sample both sources; do not
treat an empty scheduled turn as a writer sample. The existing SNKR next due
at the resume census is 2026-10-08T10:32:04Z. Do not invoke a source job to
manufacture this evidence. Recompute 30/90-day headroom using measured coverage
of encoded writes and plaintext fallbacks, reserve 3 GiB, and separately reserve
the full 887,045,884-byte NEW100 image bound before any capture expansion.

Immediate rollback disables the selected writer(s) and restores mode to canary.
The tested OFF path bypasses storage admission and lookup. Retain the new schema
revision and installed readers; they understand this unchanged representation.
If application source must be reverted, restore the writer implementation from
PR77 through a new bounded native delivery while retaining the additive migration
and its current revision. An obsolete full PR77 delivery expects e8 and is not
the rollback command. Keep e8 dependency protection and all dependency rows.
Bounded, explicitly selected canary
rows may be expanded only after independent original SHA/length verification
with the existing OFF recovery function. Broad expansion is not assumed to fit
the volume, and is not the application rollback. Any later activation preflight
must record its exact writer-owned recovery selection and room before writing.

Official references checked 2026-10-08:
[Railway volumes](https://docs.railway.com/volumes/reference) (downsizing remains
unsupported), [Railway cron](https://docs.railway.com/cron-jobs) (overlapping
same-service turns are skipped, timing is not exact), and
[SQLAlchemy conditional DDL](https://docs.sqlalchemy.org/en/20/core/constraints.html#sqlalchemy.schema.HasConditionalDDL.ddl_if).
Installed Railway 5.62.1 and GitHub CLI 2.88.0 help verified. Source budgets,
cadence, pacing, Yuyu four-claim bound, SNKR singleton, PSA10 OFF, production
boundary and historical evidence are unchanged by this delivery.
