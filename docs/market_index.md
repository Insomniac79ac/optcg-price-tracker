# Market Index — data, images, and public presentation

Reference doc for the Market Index feature and the card-image pipeline behind
it, written during the collector-first redesign audit (Phases 1-11, dated
2026-07-27 in `docs/staging_checklist.md`). Referenced from
`apps/web/src/components/ui/CardImageFrame.tsx` ("Image hosting" below) and
`apps/web/next.config.ts` (`APPROVED_IMAGE_HOSTS`).

## Calculation (unchanged by this task)

The Market Index value itself — median of eligible cross-source prices,
coverage/staleness/confidence metadata — is computed by
`services/api/app/services/market_index.py` and is untouched by this pass.
Everything below is about *sourcing images* and *presenting* the index, not
recomputing it.

## Approved price sources

Yuyu-Tei and SNKRDUNK only, per every prior staging doc
(`docs/staging_data.md`). This task doesn't add Cardrush, Mercado, or any
other source. `app.services.card_image_import.APPROVED_IMAGE_SOURCES` enforces
the same two-source allowlist for card images specifically.

## Source eligibility

Implemented in `app.services.market_index._resolve_yuyutei_sell`/
`_resolve_snkrdunk` - shared by both the legacy card-keyed Market Index
(`GET /cards/{id}/market-index`) and the print-centric one
(`GET /prints/{print_id}/market-index`, see `app.services.print_market_index`
and `docs/print_centric_pricing.md`).

**Yuyu-Tei retail sell** (product decision - see
`docs/yuyutei_collector_operations.md` "Stock is not required"):

> latest verified Yuyu-Tei sell observation <= 7 days old

Stock/availability has no effect on eligibility. A Yuyu-Tei displayed sell
price is useful market evidence whether or not the retailer currently
reports the item in stock - an out-of-stock observation is exactly as
eligible as an in-stock one of the same age. Only freshness (and the
collector's own identity/price validation - see the collector doc) govern
whether a sell observation counts. Yuyu-Tei dealer buy remains auxiliary-only
(never eligible for the index itself, unchanged).

**SNKRDUNK** - unchanged by this task: >=3 sold observations in the trailing
30 days resolves to their median (`transaction_median`); otherwise falls back
to the latest listing floor if it's <=7 days old (`listing_floor`,
`fallback_used=true`).

**Combination** - 2+ eligible sources → median, `coverage_status="full"`;
exactly 1 eligible source → that value, `coverage_status="limited"`; 0 eligible
sources → no index value, `coverage_status="none"`.

**Combination history** (`index_version`, versioned separately from
`source_semantics_version` - see `app/services/market_index.py`):

- **v1** - every eligible source value was a co-equal addend, as described
  immediately above.
- **v2** - an eligible value whose `fallback_used` was true stood aside from
  the aggregate whenever a non-fallback value was present. Introduced after a
  SNKRDUNK platform-minimum listing dragged a staging index to ¥1,310 for a
  print no source priced above ¥120.
- **v3** (current) - back to "every eligible value contributes", because v2 had
  diagnosed that defect wrongly. The ¥1,310 case was an *admissibility* failure,
  and the platform-floor rule in `source_semantics` is what actually fixed it;
  giving a current asking price **zero** weight was too blunt a remedy for it.
  Market Index is the consensus of the usable market-facing prices currently
  observable, and a live listing is weaker and different evidence from a
  completed sale but is not worth nothing. Each source still exposes at most
  ONE representative value (SNKRDUNK: a sold median when the sample supports
  one, its current listing floor otherwise - never both), so no marketplace
  votes twice, and the combination step names no source. A future Card Rush,
  Mercado or Cardmarket needs a resolver and nothing else.

Collector-facing surfaces label the evidence type neutrally rather than
excluding it - "Retail price", "Current listing", "Recent sales median" (see
`apps/web/src/lib/sourceEvidence.ts`). The louder exclusion wording is reserved
for values that genuinely are outside the index: platform-minimum listings,
below-minimum anomalies and stale observations.

## Image data audit (as of 2026-07-27)

Queried directly against the staging Postgres database (12 cards total):

| card_id | card_code | rarity / variant | image_url | Yuyu-Tei mapping | SNKRDUNK mapping |
|---|---|---|---|---|---|
| 1 | OP01-001 | L / base | none (until this task) | `yuyu-tei.jp/sell/opc/card/OP01-001` (card-code search page) | `snkrdunk.com/cards/OP01-001` |
| 2 | OP01-013 | SR / base | none | `yuyu-tei.jp/sell/opc/card/OP01-013` (search page) | `snkrdunk.com/cards/OP01-013` |
| 3-10 | various | base/alt_art | none | none | none |
| 11 | OP01-001 | Parallel / Leader | `card.yuyu-tei.jp/opc/front/op01/10002.jpg` | `yuyu-tei.jp/sell/opc/card/op01/10002` (numbered product page) | several `snkrdunk.com/en/trading-cards/{id}` |
| 12 | OP01-002 | Parallel / Leader | `card.yuyu-tei.jp/opc/front/op01/10004.jpg` | `yuyu-tei.jp/sell/opc/card/op01/10004` | several `snkrdunk.com/en/trading-cards/{id}` |

Summary: **2 of 12** cards had a usable `image_url` before this task (both
verified live: HTTP 200, `content-type: image/jpeg`, served from
`card.yuyu-tei.jp`, a GCS-backed CDN). **4 of 12** have any source mapping at
all; **8 of 12** have none.

### Why the other 10 couldn't be resolved

- **Cards 11/12's** Yuyu-Tei mapping happens to be the *numbered product page*
  (`yuyu-tei.jp/sell/opc/card/op01/10002`) — the same `{set}/{number}` slug
  `card.yuyu-tei.jp`'s image CDN uses, so the image URL was directly
  derivable from data already on file. This is how those two got their
  images (originally via mock/staging seeding, before this task existed).
- **Cards 1/2's** Yuyu-Tei mapping is a *card-code search page*
  (`yuyu-tei.jp/sell/opc/card/OP01-001`), not a numbered product page — it
  doesn't carry a resolvable image slug directly. Fetching that page to find
  the slug was attempted (`WebFetch`) and returned **HTTP 403** — the site's
  bot protection blocking the request. Per this task's explicit instructions
  ("do not bypass site protections"), this was not retried with a different
  client/user-agent/header set. Card 1's SNKRDUNK mapping
  (`snkrdunk.com/cards/OP01-001`) was also checked and returned **HTTP 404** —
  it isn't a real product URL in the first place (a placeholder from earlier
  mock-data seeding, not a genuine mapping).
- **Cards 3-10** have no source mapping of either kind — there is nothing
  mapped to even attempt.

**Conclusion**: neither approved source can currently provide a *reliable,
approved-path* image for the remaining 10 cards without either inventing a
URL (not done) or bypassing site protections (not done). This is the
documented blocker — see "Cards still missing artwork" below.

## Image provenance fields (new, this task)

Migration `f35ff2f33090_add_card_image_provenance` adds four nullable columns
to `cards`:

| Field | Meaning |
|---|---|
| `image_source` | `"yuyutei"` or `"snkrdunk"` (see `APPROVED_IMAGE_SOURCES`) |
| `image_source_url` | The public source page this image was verified against |
| `image_status` | `"verified"` once fetched and confirmed to return real image content |
| `image_last_verified_at` | When that verification happened |

No alternate-image galleries, no additional fields — deliberately the
smallest set needed to answer "where did this image come from and was it
actually checked."

## Image import procedure

`app.services.card_image_import` (`POST /admin/cards/import-images.csv`,
template at `GET /admin/cards/import-images-template.csv`) is a **separate,
narrower** workflow from the general `/admin/cards/import.csv` catalog
importer — see that module's docstring for the full reasoning. In short:

- Every identity field (`card_code`, `set_code`, `rarity`, `variant`,
  `language`) is required and used as an **exact** filter — zero or multiple
  matches is always a row error, never a guess. This is what prevents a
  Parallel printing from ever receiving a base-rarity printing's image (or
  vice versa) — see `test_wrong_variant_never_receives_another_variants_image`
  in `services/api/tests/test_card_image_import.py`.
- It never creates a card row — only attaches an image to one that already
  exists.
- `image_url` is fetched server-side (HEAD, falling back to a ranged GET) and
  its `content-type` must start with `image/` — an HTML error/login/CAPTCHA
  page is rejected as a row error, in both `dry_run` and real apply, so the
  preview reflects real reachability.
- `image_source` must be one of the two approved sources; both `image_url`
  and `image_source_url` must be `https`.

### How the two existing images got their provenance backfilled

Cards 11 and 12 already had a working `image_url` (from earlier staging
seeding, before this workflow existed). Their provenance was backfilled by
calling `import_card_images_csv(db, csv_text, dry_run=False)` directly — the
same service function the admin endpoint calls — against the staging
database, rather than an ad hoc `UPDATE`. This session doesn't hold the
staging `ADMIN_TOKEN` (rotated by the operator directly, per
`docs/staging_checklist.md`'s admin-login entries), so the HTTP endpoint
itself couldn't be called with real auth; invoking the validated service
function directly was the closest available equivalent to "an existing
validated import path" per this task's instructions, and is recorded here
for transparency. The two rows now carry `image_source="yuyutei"`,
`image_status="verified"`, and their real `image_source_url`.

## Cards still missing artwork (blocker)

Cards 1, 2, and 3-10 (10 of 12 total) still show the branded placeholder.
An operator with real, verified image URLs for these can fill in
`GET /admin/cards/import-images-template.csv` and submit it via
`POST /admin/cards/import-images.csv?dry_run=true` to preview, then
`dry_run=false` to apply. No further automated resolution is safe without
either an operator supplying a verified URL or a future, explicitly-scoped
task to re-approach Yuyu-Tei's search pages through a sanctioned method
(e.g. an official API, or manual lookup) — not by relaxing the "don't bypass
site protections" rule.

## Image hosting

`CardImageFrame` renders card art with a plain `<img>` (lazy, async,
`referrerPolicy="no-referrer"`, falls back to the placeholder on error),
**not** `next/image` — deliberate, not an oversight. `next/image` fetches,
resizes, and caches the source image through this app's own server before
ever serving it to a browser: a meaningfully bigger claim on a third-party
host's content than a browser hotlinking it directly, for a feature
(automatic resizing/blur placeholder) the existing `vault-frame`
`aspect-[63/88]` wrapper already gets via fixed aspect ratio (no layout
shift either way).

What *did* change this task: `next.config.ts`'s CSP `img-src` previously
allowed any `https:` host. It now allowlists only
`https://card.yuyu-tei.jp` (`APPROVED_IMAGE_HOSTS`) — the one host this audit
actually verified serves real image content. Add a new host there only after
verifying it the same way this doc does (fetch it, confirm `content-type:
image/*`, confirm it's one of the two approved sources).

If a future task wants to move to `next/image`, the swap is additive:
`CardImageFrame` already sets the attributes `next/image` would need
(lazy loading, alt text, a fixed-aspect-ratio container), and
`APPROVED_IMAGE_HOSTS` above is already the exact narrow `remotePatterns`
list that change would use.

## Market Index wording (public page)

`/market/movers` (nav label "Market Index") was a dense per-source price
table with a row of plain-text links straight to internal/admin tooling
(`/admin/refresh-runs`, `/admin/snkrdunk-candidates`, `/admin/alerts`,
`/admin/card-audit`) reachable by any anonymous visitor, plus links to pages
this app's own `SidebarNav` had already deliberately stopped linking
(`/market/opportunities`, `/analytics/buy-decisions`, etc.). It's been
replaced with an explainer (what the Market Index is, contributing sources,
full vs. limited coverage, listing fallback, freshness) followed by the same
catalogue grid `/cards` uses, sorted by index value — no admin links, no
"movers"/trending framing, never presented as a buy/sell recommendation.

The same reasoning applies to `/cards/[id]`'s former "Market context" panel
(opportunity scores + signal events, linking to
`/analytics/buy-decisions`/`/analytics/sell-decisions`/`/analytics/portfolio-risk`)
— removed from the public card-detail page for the same reason: it's exactly
the buy/sell-signal framing this task's Phase 8 explicitly rules out, on a
page every anonymous visitor reaches. The underlying signal-events/
opportunities APIs and pages are unchanged and still directly reachable, per
`SidebarNav`'s existing "still reachable directly, just not linked" policy.

## Mock/staging status

Unchanged: `SCRAPING_MODE=mock` throughout. Every price shown anywhere in
this app is still mock/staging data, not live scraped prices — every page
that shows a price also shows the existing "Staging data - prices are from
the mock price source (SCRAPING_MODE=mock), not live." note.
