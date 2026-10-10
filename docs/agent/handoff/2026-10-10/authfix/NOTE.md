# Admin-auth fix (PR #93): follow-ups, not fixed

2026-10-10, staging. PR #93 added admin auth to the signal-event writes and
the private market and digest reads. While doing that we noticed the items
below. They are out of scope for #93. They belong to the legacy-deletion and
collector-accounts work; don't fix them piecemeal.

## Collector-facing dashboard

- **The dashboard layout preference is shared.** `/dashboard/preferences`
  stores one layout for everyone instead of one per user. One user's
  customization changes every other user's dashboard.
- **Two widgets aren't filtered by user.** The portfolio chart and recent
  activity on `/dashboard/overview` appear to read global data rather than the
  signed-in user's collection. They need a per-user check under collector
  accounts.
- **Some saved views point at pages that are now admin-only.** Views pinned to
  `/market/signals`, `/market/signal-events`, `/market/opportunities` or
  `/market/report` now lead a collector to a not-found. Prune or migrate them.

## Stale branch-scoped Vercel preview variables

Project `prj_DCbF7bhFkkAdfMQLZWvOQbxEDDhr`. These are names only, read
2026-10-10. Since #93, Git deployments build only `staging`, so these
variables are unused. Delete them with the legacy-deletion work.

| Branch | Variables |
|---|---|
| `feature/collector-public-context` | `API_INTERNAL_URL`, `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_APP_ENV`, `R2_PUBLIC_BASE_URL`, `AUTH_SECRET` (sensitive), `API_JWT_SECRET` (sensitive) |
| `feature/market-value-b1-ui` | `API_INTERNAL_URL`, `NEXT_PUBLIC_API_URL`, `R2_PUBLIC_BASE_URL`, `AUTH_SECRET` (sensitive) |
| `feature/public-ux-cards-home-1a` | `API_INTERNAL_URL`, `NEXT_PUBLIC_API_URL`, `R2_PUBLIC_BASE_URL`, `AUTH_SECRET` (sensitive) |
| `feature/public-ux-market-1b-ui` | `API_INTERNAL_URL`, `NEXT_PUBLIC_API_URL`, `R2_PUBLIC_BASE_URL`, `AUTH_SECRET` (sensitive) |
| `optimize/vercel-function-bundles-a1` | `API_INTERNAL_URL`, `NEXT_PUBLIC_API_URL`, `R2_PUBLIC_BASE_URL`, `AUTH_SECRET` (sensitive) |

If any old branch still holds a session-signing secret, treat that secret as
due for rotation when these are removed.

Previews are behind Vercel Authentication
(`ssoProtection: all_except_custom_domains`). `ADMIN_TOKEN` is
Production-target only.

## Also seen

- `GET /market/report/latest` returned 500 on staging before #93. This is an
  existing bug that #93 doesn't change.
- The old branch `fix/admin-auth-mutating-routes` (remote head 1bae1c2) was
  replaced by `fix/admin-auth-mutating-routes-v2`. It can be deleted now that
  #93 has merged.
