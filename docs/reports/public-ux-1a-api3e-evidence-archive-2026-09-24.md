# Public UX 1A-API3E — private evidence durability

PUBLIC_UX_1A_EVIDENCE_DURABLE

The configuration issue is resolved. `PrivateR2ObjectStorage.from_settings()`
accepted the operator configuration and the dedicated staging bucket before any
network request. Authenticated bucket HEAD, content-addressed object HEAD,
conditional PUT, GET-back verification, and recovery from the downloaded archive
all passed on 2026-09-24. The durable manifest/receipt is
[`docs/evidence/public-ux-1a-release-dates-2026-09-24.json`](../evidence/public-ux-1a-release-dates-2026-09-24.json).

## Destination and remote operations

The sole destination was `cardpirate-atlas-evidence-staging`. No public URL or
public base URL was required or constructed. The client consumed only the
separate `EVIDENCE_R2_*` operator settings. No credential values, provider
endpoints, response headers, or exception tracebacks were printed.

| Operation | Result | Completed at (UTC) |
|---|---|---|
| Bucket HEAD | Reachable | 2026-09-24T16:00:54.824756Z |
| Exact object HEAD | Absent | 2026-09-24T16:00:55.004059Z |
| Conditional PUT | Created with `If-None-Match: *` | 2026-09-24T16:00:55.339183Z |
| GET | Size and SHA-256 exactly match the local archive | 2026-09-24T16:00:55.547650Z |
| Downloaded-only recovery | Passed; temporary extraction removed | 2026-09-24T16:00:59.871260Z |

The existing public `cardpirate-atlas-assets` bucket received no requests and
was not changed. No Cloudflare management API or infrastructure configuration
was accessed or changed. Authenticated bucket HEAD establishes reachability;
privacy and credential scope remain operator-provided configuration premises,
not a new Cloudflare management attestation. The receipt makes this distinction.

## Reverified evidence and deterministic archive

| Field | Result |
|---|---|
| Archive format | Deterministic tar.gz (USTAR, normalized gzip header) |
| Archive bytes | 657098 |
| Archive files | 149 |
| Accepted coded ReleaseProducts / dates | 59 / 59 |
| Conflicts | 0 |
| Acquisition records | 75 |
| Unique raw payloads | 67 |
| Product/source associations | 117 |
| Embedded file and raw payload SHA-256 digests | All verified |
| Accepted audited rows and product/date mapping | Exact match |
| Two independent local archive builds | Byte-identical; match prior preparation |
| Downloaded archive recovery | Passed |

Archive and downloaded SHA-256:
`247eaa5fd75590c49f8323dc0662c54cff91820df5200236ffe21f7616d69e54`

Verified remote object key:
`official-evidence/bandai_jp/release-dates/2026-09-24/sha256/247eaa5fd75590c49f8323dc0662c54cff91820df5200236ffe21f7616d69e54.tar.gz`

Audited mapping member: `release_date_evidence_audited.json`.
Its SHA-256 is `abad5b6ed5f94a55805c5dc85318121f8585955ea208ee011712552a553f914d`.
Canonical accepted product/date mapping SHA-256:
`313f1d4bd09865d6198bc5949000f38065fce2daea2d723d97aa34e4f1412090`.

## Recovery and source preservation

The GET response was persisted locally before recovery. Only those downloaded
bytes were extracted into a fresh `bandai-evidence-recovery-*` directory.
Recovery verified the archive size and digest, all embedded file sizes and
SHA-256 hashes, all raw payload digests, the 59 accepted audited rows, and the
exact product/date mapping against the receipt. The extractor reproduced all
required counts from that extraction. An operator wrapper blocked reads or
directory enumeration of the original evidence directory during upload and
remote recovery, and confirmed the temporary extraction no longer existed.

A before/after checksum inventory confirms all 151 original files remain
unchanged in `data/official_snapshots/bandai_jp/release_dates/2026-09-24_api3`.
The archive intentionally includes its 148 selected evidence files plus the
generated checksum manifest. Only temporary recovery extraction directories
were deleted. Local archives and the original evidence were retained.

Retained local artifacts in `/tmp/api3e-durability-om8f_ygh/`:

- `release-dates.tar.gz` and `prepared.json`: deterministic local preparation.
- `downloaded.tar.gz`: authenticated GET response, verified byte-for-byte.
- `remote-operations.json`: redacted operation results and UTC timestamps.
- `original-files-before.json` and `source-preservation.json`: preservation checks.
- `local-recovery.json`: offline pre-upload recovery result.

These temporary local paths are supplementary. Future recovery needs only the
committed receipt, the private object, and operator credentials; it does not
depend on this Codespace or the original source directory. Follow
[the independent recovery instructions](../evidence-archive.md#independent-recovery).

## Validation and scope

The focused private archive and offline evidence suites passed: **28 tests**.
The receipt was checked against the downloaded bytes and all required counts,
and checked for the actual evidence credential values without printing them.
Git whitespace validation and the repository secret scanner passed.

This resume commits only the durable manifest/receipt and archive documentation.
No application code, storage client, tests, infrastructure configuration, or
chronology migration changed. PR #13 remains open and unmerged on
`feature/public-ux-1a-api-contract`; the resume commit is local and was not pushed.

No database access or mutation, new Bandai fetch, collector, external job,
backfill, mapping/candidate change, production access, Railway/Vercel
configuration change, or credential disclosure occurred. Durability is verified;
chronology work remains deferred.
