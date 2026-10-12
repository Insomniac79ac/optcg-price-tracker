# Artwork evidence bytes in R2, hash and pointer in Postgres: DESIGN ONLY

Status: **design only.** Nothing was implemented or migrated in session 10, and no existing
evidence moves.

## Where artwork captures are stored today (MEASURED 2026-10-11, read-only)

- The Yuyu identity-evidence capture (`services/yuyutei_collector/yuyutei_collector/identity_evidence.py`,
  `retain_image`) writes each original image into **Postgres** `raw_snapshots.raw_content`. The
  value is a JSON envelope: `{"encoding":"base64","body_sha256":…,"body":<base64>}`, with
  `parser_version='yuyu-identity-evidence-v1'`.
- It does **not** use R2. `app.services.private_object_storage` (EVIDENCE_R2_*) exists, but its only
  caller is `scripts/archive_bandai_release_evidence.py`.
- Stored today (`evidence/identity-capture-sizes.txt`):

| Kind | Rows | Average stored | Total |
|---|---|---|---|
| Yuyu source images (`card.yuyu-tei.jp`) | 516 | 635,067 B | 327.7 MB |
| Official images (`www.onepiece-cardgame.com`) | 1,059 | 291,299 B | 308.5 MB |
| Product/homepage HTML (`yuyu-tei.jp`) | 1,034 | 31,892 B stored (186,852 B raw) | 33.0 MB |

- `pg_column_size == octet_length` for the image rows. Base64 of JPEG/PNG does not compress, so
  every image costs about 4/3 of its original bytes, uncompressed, in TOAST.
- Images are about **636 MB, roughly 23% of the 2.79 GB database**.

## Proposed design

1. **Object.** Store the exact original response bytes in the private evidence bucket under a
   content-addressed key: `identity-evidence/sha256/<body_sha256>`.
   - Write-once: `HEAD` first, then `PUT` only if the object is absent.
   - Never overwrite. A present object must already have the same length and SHA, or the capture
     refuses.
   - The client exposes no delete, and `PrivateR2ObjectStorage` already has only HEAD/PUT/GET.
2. **Pointer row.** `raw_snapshots` keeps one row per captured response, as today: URL, status,
   fetched_at, parser version, `content_hash`. `raw_content` becomes a small immutable envelope:
   `{"encoding":"r2-sha256","object_key":…,"body_sha256":…,"body_length":…,"content_type":…}`,
   with a new parser version `yuyu-identity-evidence-v2`. `content_hash` still fingerprints the
   envelope, so the pointer itself is tamper-evident.
3. **Order.** Persist raw before parse, extended:
   - `PUT` and verify (`HEAD` length + GET-back SHA) **before** the Postgres insert.
   - A failed upload is a transient failure with no row.
   - A row is never written for bytes that are not durable.
4. **Readers.** `physical_artwork_proof.image_body` accepts both encodings. For `r2-sha256` it
   GETs the object and requires `len == body_length` and `sha256 == body_sha256 == expected`
   before decoding. Every existing proof check stays.
5. **Provenance rules preserved:**
   - original bytes: exact response bytes, no re-encode;
   - SHA and length: verifiable on every read;
   - lineage: same `raw_snapshots` id that attempts and proofs reference;
   - never deleted: no delete path. Bucket lifecycle rules must stay empty. R2 bucket lock or
     retention is an option to check (UNVERIFIED).
6. **Existing evidence.** Not migrated. The 1,575 base64 rows stay as they are. A later
   copy-then-verify migration would itself be AMBER at least. It would also need a decision
   whether the Postgres copy may ever be dropped; dropping it is RED (deleting RAW evidence).

## Effect, cost and risks

- **NEW100 one-off** (`evidence/storage-model.json`): about 127 MB of images by measured averages
  (hard bound 887.0 MB). These would go to R2 instead of the database volume, leaving about 6 MB
  of HTML plus pointer rows in Postgres.
- **R2 cost (ESTIMATE, vendor list prices not re-checked this session):**
  - storage about $0.015/GB-month, so 0.13-0.89 GB is about $0.002-0.013/month;
  - 317 PUTs plus HEADs are well under $0.01;
  - egress is free.
- **Owner decisions needed before any build:**
  1. Collectors would need `EVIDENCE_R2_*` credentials. Distributing a secret to ten collector
     services changes the secrets footprint, so treat it as RED (security/secrets policy) until
     the owner decides.
  2. Proof validation in the resolver would make network reads. Either accept that, or validate
     against R2 only at review time and pin the pixel hash in the registry.
- **Risk:** an R2 outage makes new captures transient-fail. Prices are unaffected. Collector
  release class: AMBER (collector code), plus the RED secrets decision above.
