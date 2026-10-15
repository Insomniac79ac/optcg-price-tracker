# Product lane log

One short entry per PRODUCT-lane PR, newest last: date (UTC), PR, what changed
for collectors, tests run, screenshot/artifact links. The CI artifacts are the
delivery receipt. Lane rules: [AUTONOMY_POLICY.md](AUTONOMY_POLICY.md#delivery-lanes-owner-decision-2026-10-15).

- 2026-10-15, #126: `/api/collector-token-check` tells whether the API accepts a pass the website signs (`ok` / `mismatch` / ...), so a diverged `API_JWT_SECRET` no longer hides behind "could not be loaded" on `/account`. Collectors see no change. Tests: vitest `collectorTokenCheck`, `src/app/api` route inventory; pytest `test_auth_user.py`. Receipt: CI staging-delivery artifact for the merge.
