# Product lane log

One short entry per PRODUCT-lane PR, newest last: date (UTC), PR, what changed
for collectors, tests run, screenshot/artifact links. The CI artifacts are the
delivery receipt. Lane rules: [AUTONOMY_POLICY.md](AUTONOMY_POLICY.md#delivery-lanes-owner-decision-2026-10-15).

- 2026-10-15, #126: `/api/collector-token-check` tells whether the API accepts a pass the website signs (`ok` / `mismatch` / ...), so a diverged `API_JWT_SECRET` no longer hides behind "could not be loaded" on `/account`. Collectors see no change. Tests: vitest `collectorTokenCheck`, `src/app/api` route inventory; pytest `test_auth_user.py`. Receipt: CI staging-delivery artifact for the merge.
- 2026-10-15, #129: test-only. The card page admin-panel test waits for the fetched mapping row instead of the heading, removing a race with the fetch effect. Collectors see no change. Tests: vitest `src/app/cards` (119 passed).
- 2026-10-15, #132: Collector v1 S6. `/prints/{id}` gets Add to collection and Watch; ownership badges on Other versions and `/cards/code/{code}`; `/cards/{id}` is an exact-unique 308 lookup (needs #131); sign-in and account in the homepage style; expired admin cookie no longer hides Google sign-in; Google account chooser always; `/account` upstream logging. Tests: full vitest (1838). Screenshots: `docs/ui/evidence/2026-10-15-collector-v1-s6-card-actions/`. Receipt: CI staging-delivery artifact for the merge.
