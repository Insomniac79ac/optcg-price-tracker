# Private non-production evidence archive

The operator-managed destination is `cardpirate-atlas-evidence-staging`.
It stores immutable official source evidence independently of Codespaces.
It is separate from public display-image storage. No public URL is expected.

Infrastructure provisioning and archive upload are separate operations. Adding
the client or running `prepare` does not create a bucket or configure credentials.
A successful local preparation is **not** a durability receipt.

## Operator configuration

The upload workflow assumes the operator has already provisioned the private
bucket and dedicated credentials. Keep r2.dev access disabled and attach no
custom domains, Workers, or public delivery routes. Credentials should apply
only to this archive bucket. Provisioning, credential policy changes, and
Cloudflare management checks are separate infrastructure work; this command
does not perform them or claim to have verified their configuration.

The client exposes only bucket HEAD and object HEAD, conditional PUT, and GET.
It cannot list contents, delete objects, configure infrastructure, or construct
public or signed URLs. The destination must match the dedicated staging archive
before any request. It never accesses `cardpirate-atlas-assets` or changes the
existing display-image settings. A successful bucket HEAD proves authenticated
reachability; bucket privacy remains an operator-provided configuration premise.

Supply only these settings through an approved staging/operator secret store:

```text
EVIDENCE_R2_ACCOUNT_ID
EVIDENCE_R2_ACCESS_KEY_ID
EVIDENCE_R2_SECRET_ACCESS_KEY
EVIDENCE_R2_BUCKET_NAME=cardpirate-atlas-evidence-staging
```

The account ID must be the 32-character hexadecimal Cloudflare account ID.
Presence checks print only present/absent. Client validation may identify a
malformed setting by name; never print values, provider responses, endpoints,
headers, or exception tracebacks. Correct invalid configuration through the
secret store, without copying credentials into chat or local scripts.

No `EVIDENCE_R2_PUBLIC_BASE_URL` exists. Do not put credentials in files, logs,
source control, production, browser variables, or frontend builds. The standalone
`EvidenceR2Settings` reads only operator process variables; the API, worker,
collectors, and frontend receive no new configuration dependency. The private
client reuses existing key validation, HEAD error handling and result types;
the public `R2ObjectStorage` contract is unchanged.

## Prepare and verify

The operator environment needs the API's existing boto3 dependency plus
beautifulsoup4 (already in worker/collector development requirements).

```sh
python scripts/archive_bandai_release_evidence.py prepare \
  --archive /tmp/public-ux-1a-release-dates-2026-09-24.tar.gz \
  --manifest /tmp/public-ux-1a-release-dates-2026-09-24.prepared.json
```

Preparation re-extracts all accepted evidence and verifies all 75 acquisition
records, 67 raw responses, and 117 product/source associations. The deterministic
tar.gz preserves source-file bytes with sorted file ordering, zero archive
timestamps, normalized owners/modes, and an embedded checksum inventory.
It excludes earlier chronology previews, reports, duplicate CSVs, and unrelated
files. No source website is contacted.

After loading the operator's private archive configuration:

```sh
python scripts/archive_bandai_release_evidence.py upload \
  --archive /tmp/public-ux-1a-release-dates-2026-09-24.tar.gz \
  --manifest /tmp/public-ux-1a-release-dates-2026-09-24.prepared.json \
  --receipt docs/evidence/public-ux-1a-release-dates-2026-09-24.json
```

The object key includes the full archive SHA-256 under
`official-evidence/bandai_jp/release-dates/2026-09-24/sha256/`.
Bucket HEAD confirms reachability, then HEAD of the exact object precedes PUT.
Existing objects are read and SHA-256 verified, never overwritten; a second GET
then independently verifies the bytes returned for reuse.
PUT uses `If-None-Match: *` to reject a concurrent creation. The private GET must
return identical bytes; ETag is never a checksum. Recovery then extracts only
the downloaded bytes to a disposable directory and re-runs the evidence
extractor. It must reconstruct the same 59 product/date pairs with zero conflicts
and verify every embedded file hash. The recovered directory is removed on exit;
the source evidence is retained.

The receipt records the archive format, size, file count, digest, immutable key,
counts, accepted 59-product mapping, audited mapping member and digest, GET-back
size/digest, and UTC recovery timestamp/result. It records the checks performed
and distinguishes operator-provided privacy from live authenticated reachability.
It contains no credentials, raw payload bodies, signed URLs, or tokens.

Only the verified receipt and implementation/tests/docs belong in Git. Commit
the receipt before a later database backfill; push only when authorized. A local
prepared manifest must never be presented as a GET-back receipt. No migration,
backfill, API chronology change, database access, collector, source fetch, or
production access belongs in this workflow.

## Independent recovery

On another checkout, use `PrivateR2ObjectStorage.get_object_bytes` with the exact
key in the committed receipt and persist those bytes to a disposable archive
file. No original source evidence directory is needed. Run:

```sh
python scripts/archive_bandai_release_evidence.py recover \
  --archive /tmp/downloaded-bandai-release-dates.tar.gz \
  --manifest docs/evidence/public-ux-1a-release-dates-2026-09-24.json
```

Recovery first checks the outer byte length and SHA-256, then safely extracts
regular files into a fresh temporary directory. It verifies all embedded file
hashes, recomputes all raw payload hashes, and reruns the offline audit against
only that extracted directory. It compares the accepted mapping and audited
JSON digests with the receipt and requires 59 coded products, 59 dates, zero
conflicts, 75 acquisition records, 67 raw payloads, and 117 associations. Only
the temporary extraction directory is automatically deleted. Preserve the
original evidence and downloaded archive.

Upload runs this same independent recovery on its freshly downloaded bytes
before writing a successful receipt. If configuration, upload, verification,
or recovery fails, do not create a durability receipt or proceed to a migration.
