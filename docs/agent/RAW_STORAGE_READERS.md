# RAW capacity: readers before writers

This staging release installs lossless readers only. It does not encode any
live payload, change a schema, enable an intent, change a mapping, or alter
source admission, schedules, budgets, pacing or concurrency. Existing plaintext
continues through the same parsing and identity guards.

The October 7 natural-operation census found a storage constraint alongside
Yuyu's sixteen-item execution admission ceiling. PostgreSQL occupies 2.405 GB;
the pinned 10 GB volume reports 3.158 GB used. Recurring RAW, recurring discovery
and operational metadata add approximately 174 MB/day before further coverage.
These are measured payload-growth estimates, not a provider quota for R2.
The dedicated private staging archive contains 494 MB; its quota is unknown.
The shared public display-image bucket was not accessed.

An offline retained-byte sample tested 100 same-URL pairs. Dictionary compression
reduced 4,021,110 stored payload bytes to 212,864 encoded bytes before small
envelopes. Every reconstructed body matched its original SHA-256 and bytes;
maximum compression plus reconstruction took 3.3 ms. This is a storage prototype,
not installed capacity or a natural source throughput claim. The durable full
census and original samples remain in the October 7 capacity handoff.

The reader uses exactly one older plaintext snapshot from the same source URL
and parser version. It verifies the base and reconstructed hashes, original
UTF-8 bytes and an 8 MiB expanded bound. Corruption, missing bases, future bases,
chains and detached encoded reads fail closed. Nothing fetches source data to
recover a missing dictionary. ORM callers and portable backup exports receive
the original text, hash, UTC timestamp and lineage. Direct SQL clients see the
stored representation and must explicitly reconstruct an encoded value.

Before a later writer activation, require all reader consumers to be installed,
foreign-key protection for dictionary dependencies, a pinned staging-only writer,
raw-before-parse persistence, bounded recovery, portable backup compatibility,
and natural measured storage/runtime savings. Preserve all completed evidence
scopes, approvals, original proofs, snapshots and recovery2765. No existing RAW
body is rewritten by this release. No usable price or check freshness changes
through encoding or decoding.

Recovery for this reader-only release is an isolated forward PR restoring its
previous model mapping and dependency inputs. No encoded rows or schema changes
exist, so no database reversal is necessary. Roll back for plaintext regression,
incorrect identity, ownership/admission failure, uncontrolled requests or source
denial; preserve all raw evidence and source pauses. Existing collector recovery
deployments and complete prior commits remain retained.

Delivery requires native auto-merge, serialized strict staging audits, the exact
API build, and actual naturally adopted SNKRDUNK and all-nine Yuyu receipts.
Production remains RED and PSA10 remains OFF. The coverage mission is incomplete.
