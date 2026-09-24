# Public UX 1A-API3E — private archive durability resume

PUBLIC_UX_1A_EVIDENCE_ARCHIVE_INFRA_BLOCKED

## Current blocker

The restarted operator process has all four required `EVIDENCE_R2_*` settings
present. The existing client rejects `EVIDENCE_R2_ACCOUNT_ID` as malformed:
it requires a 32-character hexadecimal Cloudflare account ID. The validation
failed before constructing an S3 client or issuing any network request.
Only setting presence and the validator's static error category were reported;
no configuration values, provider endpoints, headers, or credentials were printed.

The operator reports that private archive configuration is now provisioned.
This supersedes the earlier missing-configuration diagnosis, but reachability,
remote object existence, upload, GET-back, and remote recovery remain unverified.
No Cloudflare management configuration was accessed or changed. Correct the
account ID through the secure operator configuration and make it available to
the process; do not paste any value into chat. Resume the documented upload only
after the existing client accepts the configuration.

## Recomputed local evidence

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
| All raw payload SHA-256 digests | Verified |
| Accepted audited rows and product/date mapping | Exact match |
| Local archive recovery | Passed; not a remote durability proof |

Archive SHA-256:
`247eaa5fd75590c49f8323dc0662c54cff91820df5200236ffe21f7616d69e54`

Intended content-addressed object key (remote presence not checked):
`official-evidence/bandai_jp/release-dates/2026-09-24/sha256/247eaa5fd75590c49f8323dc0662c54cff91820df5200236ffe21f7616d69e54.tar.gz`

Audited mapping member: `release_date_evidence_audited.json`.
Its SHA-256 is `abad5b6ed5f94a55805c5dc85318121f8585955ea208ee011712552a553f914d`.
Canonical accepted product/date mapping SHA-256:
`313f1d4bd09865d6198bc5949000f38065fce2daea2d723d97aa34e4f1412090`.

Local artifacts:

- `/tmp/api3e-release-dates-2026-09-24.tar.gz`
- `/tmp/api3e-release-dates-2026-09-24.prepared.json`

Both were regenerated from the retained API3 evidence. The archive digest, size,
and file count match the previous preparation. They are local preparation
artifacts, not a durable receipt. No successful receipt was created at
`docs/evidence/public-ux-1a-release-dates-2026-09-24.json`.

## Implementation and verification

The private client uses only the separate evidence configuration, needs no public
base URL, and constructs no public URL. Added bucket HEAD verifies reachability
without listing contents. The upload command refuses any destination outside
the dedicated staging archive before making a request. Existing objects require
a matching GET SHA-256 followed by a second verified GET. Conditional PUT still
uses `If-None-Match: *`; mismatched existing objects are never overwritten.

The resume workflow consumes the operator-provided private configuration and
records this premise separately from live checks. It does not fabricate a
Cloudflare privacy or credential-policy verification attestation. See
[private archive operations](../evidence-archive.md).

Recovery extracts only the supplied archive bytes into a fresh temporary
directory, verifies embedded file and raw payload digests, and reruns the offline
audit. The separate `recover` command works from `/tmp` using the local archive
and prepared manifest, without reading the original evidence directory. It
reproduces 59 coded products, 59 dates, zero conflicts, and the identical mapping.
The recovery directory is removed. Remote-download recovery remains outstanding.

Final focused archive/evidence tests: **28 passed**. An earlier combined run with
public-storage regressions passed all **171 tests**, before adding the account-ID
validation regression. A later combined repeat stalled in the existing
`test_unrelated_api_code_serves_with_every_r2_setting_unset` at its local
TestClient `/health` request; a bounded repeat timed out after 45 seconds in
AnyIO's thread portal. No public/API implementation was changed to address this
unrelated test-run limitation. The final 28 focused tests passed independently.

Required API compilation, dependency checks, Git whitespace checks, and the
repository secret scanner passed. No Docker or frontend build ran. A checksum
inventory confirms all 151 original source-bundle files remain unchanged (the
archive intentionally includes only its 148 evidence files plus its generated
manifest).

Implementation/tests/documentation are the only authorized commit scope.
PR #13 remains open and unmerged on `feature/public-ux-1a-api-contract`.
No migration, ReleaseProduct backfill, or chronology API ordering change was made.

## Safety

No staging/production database access or mutation, source fetch, collector,
proposal/mapping/candidate mutation, production access, Cloudflare mutation,
public asset bucket access/change, or secret disclosure occurred. Public storage
implementation and application configuration files are unchanged. Tests use
mock storage and disposable in-memory application data only.

Durability cannot be declared until authenticated bucket HEAD, content-addressed
upload/reuse, GET-back SHA-256, independent recovery from the downloaded bytes,
and a committed successful receipt are complete.
