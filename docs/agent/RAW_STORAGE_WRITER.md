# Guarded staging RAW storage, initially OFF

The measured October 7 recurring payload growth is about 173 MB/day before
relation overhead. Current PostgreSQL storage is approximately 3.16 GB of the
provider's observed 10 GB volume. Preserving all evidence requires a reduction
in future growth before additional capture volume. Provider log retention and
R2 quota remain unknown; neither is claimed as usable database headroom.

This release adds one empty dependency table and a writer that defaults OFF.
It authorizes no feature flag activation, source intent, mapping approval,
source request, cadence/budget adjustment, or provider-volume resize.

## Encoding and ownership

Only pending INSERTs with HTTP200 and parser `yuyutei-collector-v3` or
`snkrdunk-collector-v2` qualify. Existing snapshots, images, identity evidence
and published-sitemap bodies remain untouched. The writer requires the exact
staging project/environment and explicit `APP_ENV=staging` when enabled.

A dictionary is a retained older plaintext body with the identical source ID,
URL and parser. Its hash must match. There are no chains, remote dictionaries,
new secrets, or fallback source fetches. Independent decompression must match
every UTF-8 byte and the original SHA256. Capture time, status, URL, parser,
snapshot ID and observation lineage retain their existing meaning.

Require at least 25% savings against PostgreSQL's measured stored base size,
including its existing TOAST compression. Missing or unprofitable dictionaries
leave the new body plaintext. Corrupt evidence fails closed. A transaction
try-lock makes storage admission nonblocking; the global maximum is 200
encodings, including recovered rows. The source's existing claim/lease/result
fences and request accounting still govern the caller. Snapshot and protected
dependency commit before classification or parsing.

`raw_snapshot_dictionaries.id` is the captured snapshot ID. Both this ID and
the base ID have RESTRICT foreign keys, preventing retention from deleting
either body. Normal retention remains disabled on staging beat. No historical
evidence is deleted to reclaim space.

## Portable backup and recovery

Backup v19 includes dictionary lineage when RAW snapshots are included. Export
reconstructs every complete original plaintext body. Restore inserts those
bodies before their original dependency metadata. It preserves source capture
timestamps and does not fabricate an expansion event for portable plaintext.
The FK-safe registry reverses that insertion order for explicitly requested
replace restores. Old versions remain readable; old runtimes refuse v19.

Application rollback first sets the feature OFF. Leave dependency protection
installed. `expand_snapshot(session, RawSnapshot, explicit_id)` independently
reconstructs and verifies a writer-owned body, changes only its representation
to plaintext, and records the actual UTC expansion time. It keeps both raw
rows, all IDs/hashes/capture times and the dependency ledger. Portable bodies
that are already plaintext are idempotent. Do not restore a reader-incapable
runtime until every encoded body is independently verified expanded.

The migration downgrade refuses a used dependency table. The empty-table
reversal is tested locally; staging application rollback leaves the additive
schema installed. No destructive staging downgrade is needed or authorized.

## Delivery and activation requirements

`apply_staging_raw_dependency.py` accepts only the checksum-pinned
`c4e8a1d7b902 -> e8c2d4f6a901` additive revision inside the existing serialized
delivery lease. It regenerates truthful state accepting only those two reviewed
revisions for the BEFORE observation, verifies all staging writers are OFF,
repeats the database fingerprints on the selected connection, uses a 2-second
lock timeout and 30-second statement timeout, and records the actual after
revision. Other missions omit this manifest entry and perform no DDL.

No existing raw row is changed by the schema step, so a historical-data restore
backup is not applicable. Retain the reader-compatible Git source, before/after
fingerprints, exact migration checksum, existing immutable evidence and local
tested empty-schema reversal/reconstruction procedure.

Before activating even the 200-row canary, refresh state and verify actual
installed readers on API, SNKRDUNK, every Yuyu shard, worker and beat. Preserve
worker mock mode, beat retention OFF, PSA10 OFF and every source guard. Then
observe ordinary scheduled captures, verify original body hashes independently,
measure physical storage and runtime changes, and test bounded expansion of a
canary row with writes OFF. A compression benchmark alone proves neither safe
operational capacity nor 90-day headroom.

Direct SQL returns the storage representation; it must not interpret a codec
envelope as source HTML. Existing ORM readers reconstruct automatically. The
one-shot exact artwork evidence parsers remain plaintext. Future source volume
still needs its own exact identity, deadline, request, storage and rollback
safeguards; this storage release grants none of those approvals.
