# Collector accounts (S3-S8): pre-launch security audit, 2026-10-16

Base audited: `staging` at `4dbc70b` (after #135). Scope: Google sign-in, `/account`
(profile, export, delete), `/collection`, `/watchlist`, the `/me` API, the collector
token pass, and the surfaces around them. Staging only; nothing in production,
Railway, the database, settings or collectors was touched or read.

## Plain summary

- No IDOR: every `/me` read and write takes the user only from the verified token and
  filters on `user_id`. No browser bundle holds a secret name or value, and 880 commits
  of history contain no committed secret.
- The most serious issue was the web framework: Next.js 16.2.10 sits in the range of
  critical advisories (remote code execution in `next/og`, which the share cards use, and
  in image optimisation). next-auth beta.31 had a fail-open advisory. next-auth and sharp
  are fixed; Next.js is on 16.2.12, which fixes the 16.2.11 set. The 16.3.x-only
  advisories stay open because Next.js 16.3.8 fails staging verification (see
  "Dependency upgrade: what happened").
- Three HIGH issues are fixed: `/me` had no write rate limit, a new collector's first
  page load raced account creation (500, and the email and name went to Sentry), and
  next-auth/sharp.
- The open items are MEDIUM or lower. The ones worth doing before a public launch are
  JWT claim hardening (F2), a secret-strength check (F3), HSTS and a tighter CSP (F14),
  and an export that covers everything delete removes (F5).

## Method

1. A fresh subagent that had not seen the Part A changes reviewed the untouched
   staging checkout. Each of its findings was then checked against the code; findings
   marked *verified* were reproduced with a test or probe.
2. `npm audit` (apps/web) and `pip-audit` (every `requirements*.txt` the API, worker,
   collectors and scripts install).
3. A production `next build --webpack` (the CI build) with sentinel values in
   `API_JWT_SECRET`, `ADMIN_TOKEN`, `AUTH_SECRET`, `AUTH_GOOGLE_SECRET`,
   `R2_SECRET_ACCESS_KEY` and `SENTRY_AUTH_TOKEN`, then a search of `.next/` for those
   values, the secret names, `SignJWT`/`mintApiToken`/`X-Admin-Token` and JWT-shaped
   strings.
4. A history scan of every blob reachable from any branch (6,667 blobs, 880 commits) for
   private keys, cloud/GitHub/Slack/Telegram/Sentry/Vercel/Railway tokens, Google OAuth
   secrets, credentialed Postgres/Redis URLs and named secret assignments. Matches were
   classified without printing values.
5. A second independent reviewer checked every fix diff before its PR was marked ready.

## Findings

| ID | Severity | Area | Evidence | Status |
|---|---|---|---|---|
| D1 | CRITICAL | Dependencies | `next` 16.2.10: GHSA-vcvr-r3jv-pc5j (RCE in `next/og` ImageResponse; used by `src/lib/shareCard.tsx`, `src/app/share/[kind]/[id]/route.tsx`), GHSA-2xp9-vwfh-vxw4 (RCE, image optimisation with AVIF), GHSA-cjq9-62q9-8jv4 and GHSA-p9j2-gv94-2wf4 (SSRF), GHSA-6gpp-xcg3-4w24 (proxy bypass), plus DoS and cache-confusion items | partly fixed: #148 (16.2.12) clears the 16.2.11 set (GHSA-6gpp, -p9j2, -m99w, -89xv and five moderate). #151 (16.3.8) failed staging verification and was reverted (#152), so the 16.3.x-only ones stay open; see the table under "Dependency upgrade" |
| D2 | HIGH | Dependencies | `next-auth` 5.0.0-beta.31 / `@auth/core` 0.41.2: GHSA-8fpg-xm3f-6cx3 (configuration errors fail open), GHSA-7rqj-j65f-68wh, GHSA-xmf8-cvqr-rfgj, GHSA-x445-f3h2-j279 | fixed in #146 (beta.32 / 0.41.3) |
| D3 | HIGH | Dependencies | `sharp` 0.34.5 (used by `src/lib/socialArtwork.ts`): libvips, libheif and librsvg advisories; build-time `browserslist`, `source-map-js`, `baseline-browser-mapping` | our sharp fixed in #147 (0.35.5). Next 16.2.x keeps its own nested sharp 0.34.5 and postcss for `next/image`, which go away with Next 16.3 |
| A1 | HIGH | Rate limiting | `core/rate_limit.py` `COLLECTION_WRITE_PREFIXES` named the removed S8 paths, so no `/me` write was limited; `/me` reads, export and delete fell into per-IP `public_read`, and the website reaches `/me` from shared egress IPs (`lib/meProxy.ts` forwards no client IP) | fixed in #136 (writes 60/5 min, reads 300/5 min, export and delete 20/10 min, keyed per collector; IP keys prefixed so a spoofed header cannot name a collector bucket) |
| F1 | HIGH | Accounts, PII | `auth.py` `_get_or_create_user` select-then-insert; `lib/collectionServer.ts:70-78` sends 4 concurrent `/me` calls, `lib/accountServer.ts:75-78` 2. Losers raised `IntegrityError` → 500 on a new collector's first visit, and its text carries the bound email, name and Google subject into logs and Sentry (`error_tracking.scrub_event` did not touch exception values). *Verified*: probe reproduced the error and the email in its text | fixed in #137 (losers reuse the winner's row; Sentry redacts SQL parameters, Postgres DETAIL and emails) |
| A2 | MEDIUM | Abuse | `/api/collector-token-check` called the API on every request; the API counts all website traffic in one IP bucket | fixed in #141 (60 s cache, in-flight dedupe, 10 requests/min per client, 429 with Retry-After, which `verify_staging_delivery.py` honours) |
| F2 | MEDIUM | Token | `auth.py:62` `jwt.decode(..., algorithms=["HS256"])` pins the algorithm but requires no `exp`, `iat`, `aud`, `iss` or type, and caps no lifetime. A token signed with `API_JWT_SECRET` without `exp` never expires; any other JWT ever signed with this secret that has `sub`+`email` is a collector login. Compare `admin_actor.py:65-87` | open. Fix: web adds `iss`, `aud="cardpirate-api:me"`; API requires `exp`, `iat`, `sub`, `email`, `aud`, `iss` and `exp-iat <= 300`; probe gets its own `aud`. Ship API accepting both first, then web, then API strict. Effort S, two deliveries |
| F3 | MEDIUM | Secrets | `core/env_validation.py:169-213` checks length/defaults only for `ADMIN_TOKEN`; `config_check.py:40` checks `API_JWT_SECRET` only for presence in production; `docker-compose.yml` defaults `local-dev-api-jwt-secret`; the web app validates neither `AUTH_SECRET` nor `API_JWT_SECRET`. A weak or default value would allow forging any collector (or an admin Auth.js session) | open. Fix: reuse the `ADMIN_TOKEN` checks (32+ chars, not a known default, fatal in staging and production) for `API_JWT_SECRET`, and the same in `instrumentation.ts`. Effort S |
| F4 | MEDIUM | Rate limiting | `rate_limit._client_ip` and `api/admin_login.py:45-52` trust the first `X-Forwarded-For` hop, which a direct caller sets. For `/me` the key is now the verified collector, but public reads and the admin-login IP throttle can be dodged by rotating the header (the per-account admin lockout still holds) | partly fixed in #136. Fix the rest: trust only the platform-appended hop (rightmost) or a signed client-IP header from the website. Effort M |
| F14 | MEDIUM | Headers | No HSTS anywhere (`next.config.ts:107-122`, `core/security_headers.py`, Caddy/nginx examples). CSP lacks `base-uri`, `form-action`, `object-src`; scripts allow `'unsafe-inline'`. Vercel adds HSTS on its own domains; Railway unverified | open. Proposed CSP below. Effort S (headers), M (nonces) |
| L1 | MEDIUM | Logs | `app/db.py:6` `create_engine` without `hide_parameters=True`, so any other database error still prints bound parameters into plain server logs. `db.py` is a collector runtime input, so it cannot change in a product or GREEN data PR without touching both collector images | open, owner decision: do it with the next collector release |
| F5 | LOW/MEDIUM | Export | `accounts/service.py:310-337` exports profile, preferences, collection, history, watchlist and value points; `delete_account` (`:376-386`) also removes `saved_views`, `search_history`, `file_jobs`, which are not exported, while `/account` says "Everything we store about you" | open. Fix: add those three to the export (or change the copy). Effort S |
| F6 | LOW | Deletion | `collector_notes` / `collector_activity_events` have no `user_id` and their link to the legacy item tables is `ON DELETE SET NULL`, so legacy note text can outlive the account (presence on staging unconfirmed). The admin backup includes `users` but not the v1 account tables | open. Fix in S9 with the legacy table removal; document backup retention. Effort S/M |
| F7 | LOW | Sessions | Deleting the account signs out only the current browser (`account/AccountActions.tsx:34`); 30-day JWT sessions elsewhere stay valid and the next `/me` call JIT-creates an empty account | open. Fix: tombstone deleted `google_sub` with `deleted_at`; reject passes from sign-ins before it. Effort M |
| F8 | LOW | Paths | `[id]` route segments are put into upstream paths unchecked (`api/saved-views/[id]`, `api/file-jobs/[id]/*`, `api/admin/**/[id]`). If Next decodes `%2F` in params (unconfirmed), a path could reach another API path with the caller's own credentials. `/api/me` itself is safe (`meProxy.ts:8,18-23`) | open. Fix: require `^\d+$`. Effort S |
| F9 | LOW | CSRF | Admin write proxies (`lib/adminProxy.ts:118-160,228-245`) rely only on SameSite=Lax; collector writes also check Origin/Sec-Fetch-Site | open. Fix: call `crossSiteRejection` in the admin proxies. Effort S |
| F10 | LOW | Token | `auth.py:27` compares `ADMIN_TOKEN` with `!=` | open. Fix: `hmac.compare_digest`. Effort S |
| F11 | LOW | Validation | `accounts/schemas.py:41,52,216,223`: notes accept NUL/control characters (Postgres rejects NUL → 500); `acquired_on` has no range. Quantities, prices, targets, enums and lengths are bounded (schemas plus DB CHECKs) | open. Fix: reject C0 controls except tab/newline; bound the date. Effort S |
| F12 | LOW | Images | `/api/card-image` (`route.ts:71-90`) re-serves any `image/*`, including SVG, from our origin; host allowlist and https-only stop SSRF | open. Fix: raster types only, `Content-Security-Policy: sandbox` on the response. Effort S |
| F13 | LOW | Errors | Saved-views and file-jobs proxies return a 500-character `body_preview` of non-JSON upstream bodies; API config errors name the missing variable (`auth.py:24,55`). No stack traces: FastAPI is not in debug mode and has no catch-all handler | open. Fix: generic 5xx bodies, details server-side. Effort S |
| F15 | LOW | CORS | Q2 holds: credentials never allowed, no wildcard outside development, staging defaults to the stable alias (`web_cors.py`). But `.env.*.example:50,133` suggest `CORS_ALLOW_ORIGIN_REGEX=https://.*\.vercel\.app`, which would admit every Vercel tenant (public data only) | open. Owner: confirm the Railway staging value is unset or project-specific |
| S1 | LOW | Secrets tooling | `scripts/check_secrets.sh` checks tracked env and backup files and placeholders for six key names; it does not scan content for secret-shaped values and misses `R2_SECRET_ACCESS_KEY`, `SENTRY_AUTH_TOKEN`, `ADMIN_LOGIN_PASSWORD_HASH` | open. Fix: add a content scan (the patterns used for this audit) and the missing names. Effort S |
| D4 | LOW | Dependencies | Dev-only: `eslint-config-next` chain (`braces`, `micromatch`, `fast-glob`), `vitest`/`@vitest/mocker`, `jsdom`→`undici`, `js-yaml`, `brace-expansion`. Not shipped to the browser or the server runtime; `npm audit fix` errors on this tree | open. Fix: refresh the lockfile when vitest 4.1.11+ and the eslint config allow. Effort S |
| A3 | LOW | Tooling | `scripts/web_route_smoke.sh`, `staging_smoke_test.sh` requested removed pages | fixed in #138 |
| I1 | INFO | API | `/docs`, `/redoc`, `/openapi.json` are public (`main.py:113`) and list the admin API | open. Disable outside development. Effort S |
| I2 | INFO | Accounts | `users.email` is unique and never refreshed; a changed Google email that collides with another user now gets 409 instead of 500 (#137) | open |
| I3 | INFO | Token check | The public route reveals config state (`mismatch`, `unconfigured`) | accepted: needed by the CI verifier |

`pip-audit`: no known vulnerabilities in any API, worker, collector or scripts requirement file.

### Checked and found OK

- **IDOR**: user only from `Depends(require_current_user)` on every route
  (`accounts/router.py`); every query filters on `user_id` (`accounts/service.py:94-108,
  133, 189-208, 249-263, 314-337, 386`); patch/delete of another user's entry is 404;
  `extra="forbid"` on every input schema, so `user_id` cannot be injected. Two-user tests:
  `test_accounts.py::test_user_a_never_sees_or_changes_user_b` and the rest of that file;
  #136 adds two-user rate-limit tests.
- **Token**: HS256 pinned (`auth.py:62`); 5-minute website pass (`collectorApi.ts:22,58`);
  the probe pass has no email and is rejected at `auth.py:68-69` before user creation.
  Admin and collector are separate: a pass is minted only for `sessionKind ===
  "collector"`; `/me` reads only `Authorization`, admin routes only `X-Admin-Token`.
- **Browser**: no secret name or sentinel value anywhere in `.next/` after a build with
  sentinel secrets; token modules are `server-only`; only five `NEXT_PUBLIC_*` variables;
  the `/me` proxy returns only `content-type` and `content-disposition`.
- **NextAuth**: default cookies (HttpOnly, SameSite=Lax, Secure with `__Secure-` over
  https); Auth.js CSRF token on its own POSTs; collector writes check Origin and
  Sec-Fetch-Site (`collectorApi.ts:107-115`); `sanitizeCallbackUrl` (`callbackUrl.ts:98-118`)
  rejects absolute, `//`, `/\`, control-character and `javascript:` targets; the expired
  admin cookie fix (#132) is UI-only and the server checks still fail closed
  (`adminSession.ts:30-31`, `proxyGuard.ts:369-375`).
- **Deletion**: account tables plus `saved_views`, `search_history`, `file_jobs` and
  their files are deleted explicitly; legacy tables cascade by foreign key. Sessions are
  JWT, so there are no Auth.js session tables to clear.
- **Sentry and logs**: `send_default_pii=False`, no locals, bodies or tracing; headers,
  cookies, queries and user scrubbed (API and web); account log lines carry only step,
  status and error class. #137 closes the exception-text gap.

## Proposed CSP (web)

Built in `next.config.ts` from the existing helpers; keeps Sentry (same-origin SDK chunk,
ingest origin in `connect-src`), Vercel Analytics (same-origin `/_vercel/insights`), R2
and source images (`buildImageSrcHosts`), Google sign-in (a redirect; the form POST goes
to Auth.js), `next/font/local` and Next's inline bootstrap:

```
default-src 'self';
script-src 'self' 'unsafe-inline';            # dev also 'unsafe-eval'
style-src 'self' 'unsafe-inline';
img-src 'self' data: https://card.yuyu-tei.jp https://cdn.snkrdunk.com <origin of R2_PUBLIC_BASE_URL>;
font-src 'self';
connect-src 'self' <origin of NEXT_PUBLIC_API_URL> <Sentry ingest origin>;
frame-src 'none';
frame-ancestors 'none';
object-src 'none';
base-uri 'self';
form-action 'self' https://accounts.google.com;
manifest-src 'self';
worker-src 'self';
upgrade-insecure-requests;                     # production builds only
```

Plus `Strict-Transport-Security: max-age=63072000; includeSubDomains` on web and API
(add `preload` only once the domain plan is settled), and
`Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()`.
Ship it first as `Content-Security-Policy-Report-Only` for one staging cycle. Replacing
`'unsafe-inline'` scripts needs a per-request nonce from `proxy.ts` and makes pages
dynamic (effort M).

## Dependency upgrade: what happened

#140 moved Next.js, next-auth and sharp in one step and failed staging verification
twice with only `TimeoutError`. It was reverted (#144), the verifier was taught to name
the failing stage and the requests still in flight (#145, #149), and the upgrade was
retried one package at a time:

- next-auth beta.32 (#146), sharp 0.35.5 (#147) and Next.js 16.2.12 (#148) each verified
  green.
- Next.js 16.3.8 alone (#151) failed the same way. The receipt now reads
  `TimeoutError during browser warm-up /; still loading: fetch /sign-in`. The home page
  never reaches network idle because a request for `/sign-in` (the header's Sign in link,
  `components/ui/TopBar.tsx`) never completes on staging.

#140 and #151 failed identically: the same step ("Verify native Git deployment and
regenerate state"), a `TimeoutError` (not wrong content) about 95-105 s into the
verifier, which is where its first browser pass runs. #140's receipt predates the stage
labels, so only #151 names the page (`/`) and the stuck request (`/sign-in`).

So the trigger is Next.js 16.3.x together with the `/sign-in` request on Vercel. What
16.3 changes that our site trips on is still unknown. The CI logs carry no Vercel build
or function logs, and the receipt artifacts are out of reach from a cloud session.
Locally (`next start`, stub API), clicking Sign in on 16.3.8 renders in 0.2 s, and a
fresh first load of `/` reaches network idle on both versions. The one difference seen:
16.3 answers the Sign in link's plain `/sign-in?callbackUrl=...` RSC request with a 307
to an `_rsc`-hashed URL, and 16.2.12 does not. That is a lead, not a confirmed cause. The
Vercel request log for `/sign-in` between 14:00 and 14:02Z on 2026-10-16 would settle
it.

Original high/critical Next.js advisories already fixed by 16.2.12 (live since #148):
GHSA-6gpp-xcg3-4w24 (proxy bypass), GHSA-89xv-2m56-2m9x (Server Actions SSRF),
GHSA-m99w-x7hq-7vfj (Server Actions DoS), GHSA-p9j2-gv94-2wf4 (rewrites SSRF), all high.
Those that genuinely need 16.3.x, and the rest still open (`npm audit --omit=dev`):

| Advisory | Severity | Fixed in | Reachable here? | Interim mitigation |
|---|---|---|---|---|
| GHSA-vcvr-r3jv-pc5j, RCE in `next/og` ImageResponse (CWE-1395: a vulnerable bundled component) | critical | 16.3.6 | The path is reachable: `/share/[kind]/[id]` renders with `ImageResponse`. Attacker input is limited: the route accepts only `print`/`release` with a numeric id or `market/overall`, text comes from our API, fonts are local, and artwork is accepted only as PNG/JPEG/WebP and re-encoded to PNG by our patched sharp 0.35.5 (`lib/socialArtwork.ts`) | Fixed off by #153's static `/share` fallback (run 38922562795); still open for Next 16.3 |
| GHSA-2xp9-vwfh-vxw4, RCE in image optimisation with AVIF | critical | 16.3.3 | No on Vercel: `/_next/image` is served by Vercel's optimiser, and `next.config.ts` sets no `images` formats or remote patterns | Keep `images` unset; do not self-host the web app on 16.2.x |
| GHSA-p293-qw3h-jr36, RCE on Windows-hosted servers | critical | 16.3.3 | No: Vercel runs Linux | None needed |
| GHSA-cjq9-62q9-8jv4, SSRF in image optimisation | high | 16.3.8 | No on Vercel (as above); no `remotePatterns` | Keep `images.remotePatterns` unset |
| GHSA-mcj8-r9mp-w47p, GHSA-4jqv-mc3x-m676, cache poisoning of SSG/ISR | moderate | 16.3.8 | Low: no `generateStaticParams` or `revalidate` in `src/app`; 4jqv is self-hosted only | None needed beyond staying on Vercel |
| GHSA-f87g-xv8r-7p7x, metadata image routes | moderate | 16.3.8 | No: `icon.svg` and `apple-icon.png` are static files | None |
| GHSA-39w2-rjm5-chcv, dev-server MCP endpoint | low | 16.3.8 | No: dev server only | None |
| Next's nested sharp 0.34.5 (GHSA-f88m, -rgj7, -wq5f) and postcss | high/moderate | Next 16.3 | No on Vercel: used by Next's own image optimiser and build | Same as GHSA-2xp9 |
| browserslist, source-map-js, baseline-browser-mapping, nanoid | high/moderate | lockfile refresh | No: build-time tooling, not served | Refresh the lockfile in a later dependency PR |

16.3.x is parked as a follow-up. Next step: find why `/sign-in` hangs on Vercel under
16.3 (the request log above), fix that route or its link (for example `prefetch={false}`
if the prefetch is the request), then retry 16.3.8 alone. The reachability for
GHSA-2xp9, GHSA-cjq9 and Next's nested sharp assumes Vercel serves `/_next/image` with
its own optimiser, which is how Vercel documents it; that was not checked against the
staging project's settings.

## Fix PRs

| PR | Fixes | Lane / receipt scope |
|---|---|---|
| #140 | D1, D2, D3 in one step | product; failed verification twice, reverted by #144 |
| #145, #149 | Verifier names the failing stage and the requests still loading | data |
| #146 | D2 (next-auth beta.32) | product; verified (run 38879184848) |
| #147 | D3 (sharp 0.35.5) | product; verified (run 38888685548) |
| #148 | D1, part (Next 16.2.12) | product; verified with the following run 38906152623 (#150 merged during its own check) |
| #151 | D1, rest (Next 16.3.8) | product; failed verification (run 38909877498), reverted by #152 |
| #152 | Revert of #151 (back to Next 16.2.12) | product; verified (run 38913847744) |
| #137 | F1 | data; verified (run 38882503658) |
| #136 | A1 | data; verified (run 38885503713) |
| #141 | A2 | product; verified (run 38891946439) |
| #138 | A3 | data; verified (run 38894740983) |

CI run ids and receipts are recorded on each PR. Every PR's diff was checked against
`scripts/collector_runtime_inputs.py` at base (snkrdunk 62 inputs, yuyutei 73):
intersection empty.

## For the owner

- Confirm the Railway staging `CORS_ALLOW_ORIGIN_REGEX` is unset or specific to this
  project (F15); this session cannot read Railway variables.
- Decide when `app/db.py` gets `hide_parameters=True` (L1): it changes both collector
  images' inputs.
- No exposed secret was found, so no rotation is needed beyond 2026-10-15's.
- To unblock Next.js 16.3: check the Vercel request log for `/sign-in` on the #151
  deployment between 14:00 and 14:02Z on 2026-10-16 (status, duration, any redirect
  loop), or open the `staging-delivery-1068d3c…` artifact of run 38909877498. This
  session cannot reach Vercel or the artifact store.
- Decide whether `/share` images stay on while `next/og` is on 16.2.12 (GHSA-vcvr).
