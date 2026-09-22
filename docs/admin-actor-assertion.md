# Admin actor assertion v1

`APPROVE_EXACT` is authorized twice: `X-Admin-Token` authenticates the Next.js
server, and `X-Admin-Actor-Assertion` identifies the validated Auth.js admin who
made the decision. The browser can supply neither trusted value.

The signing key is the 32-byte digest:

```text
SHA-256(UTF8("opcg-admin-actor-v1\0") || UTF8(ADMIN_TOKEN))
```

The assertion is an HS256 JWT. No other algorithm is accepted. It carries:

- `iss=opcg-web-admin-proxy`
- `aud=opcg-proposal-decision`
- `purpose=approve_exact_proposal`
- `sub` and `email` from the server-validated Auth.js admin identity
- `iat`, `exp` (at most 60 seconds after `iat`), and a unique `jti`
- uppercase HTTP `method`, exact backend `path`, and lowercase hexadecimal
  `body_sha256` over the exact forwarded request bytes

The backend permits five seconds of clock skew and otherwise validates every
claim. It first requires the ordinary admin token and fails closed when
`ADMIN_TOKEN` is absent, including development mode. Actor failures use:

- `admin_actor_assertion_required`
- `admin_actor_assertion_invalid`
- `admin_actor_assertion_expired`
- `admin_actor_assertion_request_mismatch`

The proxy reads the body as bytes, creates the assertion after Auth.js session
validation, and forwards the same bytes with server-generated headers. Incoming
admin-token and actor-assertion headers are ignored. Neither credential is
returned to browser code or included in logs.

The deterministic Node/Python compatibility vector is
[`contracts/admin-actor-assertion-v1.json`](contracts/admin-actor-assertion-v1.json).

## Exact approval mutation

The only decision route in this tranche is:

```text
POST /admin/source-mapping-proposals/review/groups/{proposal_group_id}/approve-exact
```

Its JSON body contains `selected_alternative_id`, `expected_evidence_digest`,
`expected_resolver_version`, `expected_updated_at`, and optional `review_note`.
Unknown fields are forbidden. In particular, reviewer identity and all result
or lifecycle fields are server-owned.

The route owns one transaction and one commit. The decision service locks the
group, its alternatives, and its source candidate; checks exact replay; applies
optimistic concurrency; reruns the canonical resolver from stored evidence;
rechecks the print, release, candidate and listing; invokes the source writer;
and flushes lifecycle state. Source writers never commit. Any refusal rolls the
transaction back.

Decision conflicts use stable codes including `proposal_not_found`,
`proposal_superseded`, `proposal_not_pending`, `proposal_not_exact`,
`proposal_has_no_single_recommended_alternative`,
`selected_alternative_not_in_group`, `evidence_digest_changed`,
`resolver_version_changed`, `proposal_updated`, `proposal_result_changed`,
`candidate_missing`, `candidate_state_changed`, `release_changed`, and
`source_identity_changed`. Existing exact-print mapping refusal codes remain
authoritative for inactive/unverified prints and rejected, duplicate, or
different-print mappings.
