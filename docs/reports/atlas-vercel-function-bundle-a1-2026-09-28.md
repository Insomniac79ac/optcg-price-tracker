# Atlas Vercel Function Bundle Optimization A1

Local classification: **ready for review**; actual GitHub CI is required before
the final review handoff and will be linked from the PR.

Implementation and local package reduction are complete. Unique local ZIP
packages fell from **76,229,408 to 6,007,702 bytes**, a reduction of
**70,221,706 bytes (92.1189%)**. Sharp, libvips, and the actual OG renderer are
absent from every measured AFTER package. The version trace is bounded.

The full frontend suite has **1,583 passing tests and four failures**. All four
fail identically on untouched staging at the exact baseline SHA. They are
unrelated to A1 and remain unchanged. Independent finalization reruns reproduce
the same four assertions on both trees (31 passing tests each). These known
baseline failures are recorded below, rather than changed or excluded. The two
source optimizations, focused tests, local build/analyzer, type checking, lint,
and browser smoke passed.

## Recovery, checkout, and scope

Accepted recovery state: `VERCEL_ACCIDENTAL_PROJECT_DELETED_A1_RESUMED`. Recovery
found `repo` already absent by name and its previously verified actual ID; this
implementation run performed no deletion or project creation.

- Checkout: `/tmp/atlas-vercel-a1-resumed/repo`.
- Branch: `optimize/vercel-function-bundles-a1`, attached to the existing branch
  without altering the absent older worktrees or rewriting their records.
- Implementation base and verified remote staging:
  `0e00810a3f319eda1c099b5a6fc52856851bddb3`.
- Tracked tree was clean before implementation; no unexpected source changes.
- Both local Vercel links identify `optcg-price-tracker-staging`, project
  `prj_DCbF7bhFkkAdfMQLZWvOQbxEDDhr`, team `team_fDDZv0BhAU76b7swojQuhRz9`.
- Independent `vercel project inspect` resolved that exact name/ID before the
  AFTER build. Existing local settings were reused; **no `vercel pull` ran**.
- Original checkout remains on PR #25's branch at
  `71cd3ceb2858c48dbb02f661e222cd004a7efaa2`, with no tracked changes.
- A1 changed-file intersection with PR #25's file list is empty.

The accepted BEFORE build and analyzer were reused. Only missing package ZIP
sizes/digests, complete trace categories, and metadata-response hashes were
measured from the existing outputs. No BEFORE build/analyzer was repeated.

## Changed files

| Files | Change |
| --- | --- |
| `apps/web/src/app/opengraph-image.tsx`, `opengraph-image.png` | Remove generator; add exact captured 1200 × 630 PNG |
| `apps/web/src/app/apple-icon.tsx`, `apple-icon.png` | Remove generator; add exact captured 180 × 180 PNG |
| `apps/web/scripts/generate-build-version.js` | Deterministic root VERSION generation, explicit missing/empty-file errors |
| `apps/web/src/generated/buildVersion.ts` | Generated root version constant only |
| `apps/web/next.config.ts` | Generate automatically for Next build/dev phases |
| `apps/web/src/app/api/version/route.ts` | Replace runtime filesystem scanning with constant; preserve response/fetch contract |
| `apps/web/scripts/generate-build-version.test.js` | Generator and actual Next config phase tests |
| `apps/web/src/app/api/version/route.test.ts` | Version schema, overrides, fallback, backend errors/timeout, no runtime filesystem probing |
| `apps/web/src/app/metadata-images.test.ts` | Original PNG hashes, formats and dimensions |
| `apps/web/src/lib/nextConfigImgSrc.test.ts` | Adapt existing CSP tests to phase-aware config export |
| `apps/web/Dockerfile`, `apps/web/Dockerfile.dockerignore`, `docker-compose.prod.yml` | Give local web builds root VERSION through a narrowly allowed root context |
| `docs/deployment.md` | Document automatic generation, version precedence, Docker context |
| This report and `atlas-vercel-function-bundle-a1-packages-2026-09-28.csv` | Results and exact local package digests |

There are no dependency/lockfile changes, auth changes, API consolidations,
version-number bumps, trace excludes, backend source edits, or infrastructure
mutations. The finalization scope authorizes commits, a push, and a PR targeting
staging; it stops before merge or manual deployment. Backend, Railway, auth-policy,
Market methodology, and PR #25 files are absent from the diff. The Docker/Compose
changes only preserve the root VERSION contract in local web image builds.

## Static metadata

The PNGs were copied directly from the existing BEFORE build's prerendered
response bodies, before deleting the TSX generators. They are byte-identical to
the current renderer output, retaining the existing CardPirate Atlas artwork,
dark/gold/teal colors, product name, endorsement and tagline.

| Asset | Dimensions | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Open Graph | 1200 × 630 | 37,776 | `0d5f9806b0a7a99df9ec80717dbbbe185b1beb1cf06ec9c65d5ae3278d9fa498` |
| Apple icon | 180 × 180 | 2,815 | `919a6718810dbb65a8e729e72a6a02632599cdc1eddd549da332675bac9f27d3` |

Next automatically discovers the PNG conventions. Built HTML and local browser
responses contain `og:image` referencing `/opengraph-image.png?...` and
`rel="apple-touch-icon"` referencing `/apple-icon.png?...`, including the
correct icon dimensions/type. Both URLs return HTTP 200, `image/png`, and the
original bytes. The source contains no production `next/og` or `ImageResponse`
usage. The old extensionless generator routes no longer exist.

**Builder limitation:** Next/Vercel still emit shared `.func` fallback aliases
for the PNG routes, just as for other static metadata. Their prerender configs
have `expiration: false`, PNG fallback bodies, and no runtime image renderer.
Ordinary image requests serve the prerendered bytes. The local `.func` aliases
have not disappeared; a literal requirement for zero such fallback aliases is
not met by this native static-file implementation. No generated output was
manually patched to conceal them, and no deployed resource inventory is claimed.

The analyzer reports three framework `next/server` deprecated ImageResponse
shims; inspection confirms they only throw a migration error. They are not the
OG renderer and import no Sharp/libvips. Actual renderer/native dependencies
are absent from the AFTER file maps and metadata traces.

## Version implementation

`next.config.ts` generates `src/generated/buildVersion.ts` in the production
build and development phases. The generator resolves exactly one root VERSION
path relative to its own script location. It trims the value, rejects missing,
empty, or multiline content, encodes it as data, and does not rewrite unchanged
output. It reads no secrets or package version and embeds no time-dependent data.

This runs for direct `next build`/`next dev`, `npm run build`, Vercel's local
build, and the analyzer. Actual Next config-loader tests prove generation of a
missing module in build/dev, a clear build error without VERSION, and no VERSION
requirement when loading runtime config. The generated constant is checked in
for tests/type checks and refreshed automatically to prevent build-time drift.

The route now imports only that constant. `APP_VERSION` remains the override;
`GIT_COMMIT` remains first priority with `VERCEL_GIT_COMMIT_SHA` as its fallback;
missing commit/build-time values remain `unknown`. The backend URL, no-store
fetch, five-second abort timeout, JSON projection, error handling and response
shape `{ web: { version, git_commit, build_time }, api }` are unchanged.

Docker's previous web-only context lacked root VERSION. The web Dockerfile now
uses repository-root context with a Dockerfile-specific allowlist for web source
and VERSION, excluding dependencies, build outputs and environment files. The
Compose file points to that Dockerfile; an absent APP_VERSION no longer masks
the root value with a package-era default. These are local source changes only;
no container image build or production service operation was run.

## BEFORE and AFTER measurements

Both builds use Next.js 16.2.10, Node 24, Vercel CLI 60.1.3, the same dependencies,
and inert local environment values. Package members are resolved through each
real `.func` directory's `filePathMap`, including its launcher. ZIP bytes and
digests come from the installed Vercel build-utils `NodejsLambda.createZip()`.
Count each digest once for unique ZIP bytes; multiply by canonical route aliases
for route-weighted logical bytes. These are local measurements, not billed cloud
storage. The earlier cloud audit had three deployed package identities; that
platform grouping is not substituted for either side of this local comparison.

| Metric | BEFORE | AFTER | Reduction |
| --- | ---: | ---: | ---: |
| Distinct ZIP packages / content digests | 5 | 5 | 0 |
| Unique ZIP bytes | 76,229,408 | 6,007,702 | **70,221,706 (92.1189%)** |
| Unique resolved uncompressed package bytes | 177,205,802 | 19,399,997 | 157,805,805 (89.0523%) |
| Content-deduplicated ordinary file bytes | 54,853,687 | 10,687,736 | 44,165,951 |
| Canonical-route-weighted ZIP bytes | 3,638,217,358 | 271,330,087 | 3,366,887,271 (92.5422%) |
| Canonical-route-weighted resolved bytes | 8,242,227,753 | 820,278,677 | 7,421,949,076 (90.0479%) |
| Real `.func` directories | 5 | 5 | 0 |
| `.func` symlinks | 503 | 503 | 0 |
| All local `.func` paths | 508 | 508 | 0 |
| Canonical local function aliases, excluding RSC/segments | 177 | 177 | 0 |
| Next build/analyzer routes | 175 | 175 | 0 |
| Source pages + route handlers | 53 + 115 | 53 + 115 | 0 |

The two static PNG names replace the two extensionless image names. The major
gain is package contents, not route removal. All ten exact package SHA-256
digests, route weights, and sizes are recorded in the
[package inventory](atlas-vercel-function-bundle-a1-packages-2026-09-28.csv).

| Local package group | BEFORE ZIP bytes | AFTER ZIP bytes |
| --- | ---: | ---: |
| Static pages/errors | 18,019,165 | 1,470,546 |
| Proxy | 501,001 | 501,001 |
| Dynamic pages | 18,218,964 | 1,619,866 |
| APIs | 22,050,705 | 1,567,178 |
| Static metadata | 17,439,573 | 849,111 |

| Dependency family, summed over distinct resolved packages | BEFORE bytes / bundles | AFTER bytes / bundles |
| --- | ---: | ---: |
| Sharp package | 1,058,312 / 4 | 0 / 0 |
| Native libvips distributions | 134,566,652 / 4 | 0 / 0 |
| Actual OG renderer | 12,862,880 / 4 | 0 / 0 |

No remaining route/import requires those libraries in the measured packages.
Installed transitive dependencies remain in node_modules; nothing was removed
from dependencies or forcibly excluded from traces.

## Trace changes

| Trace metric | BEFORE | AFTER |
| --- | ---: | ---: |
| `/api/version` total traced files | 621 | 95 |
| `/api/version` total bytes | 8,278,400 | 1,635,347 |
| Source files / bytes | 509 / 3,570,707 | 0 / 0 |
| Source test files / bytes (subset of source) | 121 / 1,030,524 | 0 / 0 |
| Public assets / bytes | 4 / 2,745,763 | 0 / 0 |
| Apple metadata files / bytes | 163 / 39,506,569 | 94 / 1,638,408 |
| OG metadata files / bytes | 163 / 39,508,380 | 95 / 1,685,149 |

The version constant is compiled into the route chunk, so its original TypeScript
source file is not a separate trace member. AFTER metadata traces contain static
image bytes and framework response handling, with no Sharp, native libvips,
resvg, or actual OG renderer. Full trace member lists are preserved locally.

## Validation and remaining failures

| Check | Result |
| --- | --- |
| Initial focused metadata/version/brand tests | 36 passed |
| Final metadata/version/CSP tests | 18 passed |
| Finalization metadata/version/CSP/brand rerun | 48 passed |
| Generator/config phase + environment tests | 19 passed (10 + 9) |
| Backend version and release-audit regressions | 11 passed |
| Full frontend suite | **1,583 passed, 4 failed**, 120 passing / 3 failing files |
| Independent finalization reproduction on A1 | 31 passed, same 4 failed |
| Independent finalization reproduction on untouched staging | 31 passed, same 4 failed |
| TypeScript `tsc --noEmit` | Passed |
| Touched TypeScript ESLint and JS syntax checks | Passed |
| `git diff --check` | Passed |
| Local Vercel AFTER build | Passed |
| Next experimental analyzer | Passed, 14.5 seconds |
| Local browser + HTTP smoke | Passed |

All paths below are relative to `apps/web`. The exact failing test names and
assertions from both fresh JSON reports are:

| Test file and full test name | A1 result | Staging result | Attributable to A1? |
| --- | --- | --- | --- |
| `src/components/admin/AdminNavigation.test.tsx:51` — `Atlas admin shell uses the same groups in a modal mobile drawer with an explicit close action` | `TestingLibraryElementError: Unable to find an accessible element with the role "button" and name "Open admin navigation"` | Same error and assertion | No |
| `src/components/admin/AdminNavigation.test.tsx:64` — `Atlas admin shell replaces admin access with reauthentication when the role expires` | `AssertionError: expected null not to be null`; `container.querySelector("[data-app-rail]")` | Same error and assertion | No |
| `src/components/ui/CardPrintingChooser.test.tsx:141` — `CardPrintingChooser E. survives a printing whose Market Index is unavailable` | `TestingLibraryElementError: Unable to find an element with the text: /Index unavailable/i` | Same error and assertion | No |
| `src/app/cards/code/[cardCode]/page.test.tsx:135` — `A. multi-print family N. keeps an unpriced printing honest` | `TestingLibraryElementError: Unable to find an element with the text: /Index unavailable/i` | Same error and assertion | No |

The admin tests render AppShell without staging's server-authorized AdminSurface
context and expect former client-role-driven rail behavior. Both pricing tests
expect `Index unavailable`; staging renders `No market price yet`.

Those test files and their product implementation are unmodified. No tests were
skipped or weakened to obtain a green result. The baseline reproduction uses a
separate archive of the exact staging commit, sharing only installed dependencies.
All 529 archived source files were independently byte-checked against `git archive`
of that commit before rerunning the tests. Test names and error messages match
between fresh A1 and staging reports. No failing test or corresponding product
implementation file appears in the A1 diff. No test was edited to hide a failure.

The finalization reran the local Vercel build, 48 focused frontend tests, all 19
Node generator/environment tests, all 11 backend version/release-audit regression
tests, TypeScript, touched-file ESLint, `git diff --check`, and the browser smoke.
All passed. The accepted analyzer and package measurements are reused without
changing their counting method. GitHub's existing frontend CI runs the build and
Node script tests; it does not run the full Vitest suite. The four local Vitest
failures remain documented independently of that CI scope.

Playwright exercised `/`, `/cards`, `/analytics`, `/admin/login` with mock data;
all returned HTTP 200 with no browser runtime/console errors. `/api/version`
returned HTTP 200 with root version, Vercel commit fallback and the local mock
backend version. Both metadata URLs returned byte-identical PNGs. All external
browser requests were blocked/intercepted, and server backend calls used a local
mock. Canceled speculative RSC prefetches on navigation were excluded from network
failure classification. No live collector/backend data was used. No backend fetch
attempt was recorded during either build/analyzer run.

## Preservation, evidence, and cleanup

Final read-only verification: staging exists, stable site HTTP 200, deployment
`dpl_G9bY6oWCDbh3cHGUm1KcL4Hs1ybr` READY at unchanged SHA
`0e00810a3f319eda1c099b5a6fc52856851bddb3`. All 30 project aliases and the domain
inventory match recovery. `repo` and its former domain remain absent.
PR #25 remains OPEN at `71cd3ceb2858c48dbb02f661e222cd004a7efaa2`, with identical
captured metadata and update time (`2026-09-28T10:07:13Z`). No Vercel/Railway
settings were changed. A normal Vercel Preview integration may run when the PR
opens; no manual deployment is authorized or performed.

Evidence: `/tmp/atlas-vercel-a1-implementation/evidence/`, with BEFORE/AFTER
package manifests/digests, trace members, original PNG captures, metadata and
analyzer summaries, browser results, test reports, build logs, and PR verification.
Recovery API evidence remains under `/tmp/atlas-vercel-a1-recovery/evidence/`.
Fresh finalization evidence includes `finalize-baseline-comparison.json`, the two
full failing-test reports, `finalize-focused.json`, build and smoke results, and
the explicit changed-file/PR #25 comparison. Source changes and this report live
in the isolated A1 worktree.

After capturing measurements, removed only this worktree's `apps/web/.next`
and `.vercel/output`. Kept source, PNGs, generated source, scripts, tests,
project links, concise evidence and node_modules. Final `df -h /workspaces`:
**13 GB available, 60% used**. `/tmp`: **106 GB available**.

Method references: [Next static metadata conventions](https://nextjs.org/docs/app/api-reference/file-conventions/metadata),
[Vercel Build Output API](https://vercel.com/docs/build-output-api/primitives).
All numeric conclusions above come from the local build outputs, not estimates
from those references.
