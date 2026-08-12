# Tranche: Print-centric public catalogue + search

## Page or component
`/cards` (public catalogue + its search/filters), plus a minimal `/prints/[id]`
destination so tiles have a print-scoped place to land.

## Emotional outcome
Browsing feels like flipping through a real collection of individual cards —
each exact print is its own collectible, and the price is quiet context under
the artwork.

## User's five-second impression
"These are real One Piece cards, I can see each one fully, and there's an
honest price under each."

## Must visibly change
- `/cards` is backed by `GET /prints` — 20 real prints, not legacy card rows.
- Every tile shows full, uncropped Bandai artwork (currently 18/20 render as
  grey placeholders).
- Base and parallel siblings appear as separate tiles with separate prices.
- Coverage reads honestly: "2 sources" vs "Yuyu-Tei only".
- Filters reduce to treatment + rarity; search matches code / EN / JP.

## Must not change
- Home `/`, `/market/movers`, `/search`, all `/analytics/*`, `/collection`,
  `/wishlist`, `/grading` — they keep legacy `CollectorCardTile` + `/cards/catalogue`.
- `/cards/[id]` legacy detail route — untouched.
- Admin shell and every `/admin/**` page; authentication.
- Market Index methodology, collectors, cron, Railway, DB schema, mappings,
  observations.
- `CollectorCardTile` behaviour for its existing callers.

## Real data available (GET /prints, verified live on staging)
- `image_url` — 20/20 present, all distinct, real 600×838 PNGs on
  `www.onepiece-cardgame.com`, HTTP 200 with no referrer.
- `card_code`, `name_en`, `name_jp` — 20/20 present.
- `rarity`, `card_type`, `treatment`, `language`, `release_product_code`.
- `market_index` — print-scoped: `index_value_jpy`, `source_count`,
  `coverage_status`, `confidence`, `source_values[]` (yuyutei `retail_sell`,
  snkrdunk `listing_floor`), `freshest_observation_at`.
- `source_coverage[]`, `latest_observation_at`.
- Facets: treatments, rarities, languages, verification_statuses.
- NOT available: any set/release filter or facet; any price history/trend on
  the catalogue endpoint.

## Before evidence
- `shots/before_desktop.png`, `shots/before_mobile.png` (staging `/cards`).
- Current problems, concretely:
  1. Backed by legacy `/cards/catalogue` — card_id keyed.
  2. 18 of 20 visible tiles are grey placeholders; only the two
     `card.yuyu-tei.jp` images load.
  3. Legacy rows show "Index unavailable / no sources" beside real cards.
  4. Siblings collapse: one Sanji `OP01-013` row, not base + parallel.
  5. Filters offer set/language/variant that print data cannot honour.

## Acceptance criteria
1. `/cards` issues `GET /prints` and no legacy `/cards/catalogue` or
   `/cards/{id}/market-index` call.
2. All 20 prints render; every tile keyed by `card_print_id`.
3. Sanji `OP01-013` base and parallel both appear, with ¥120 and ¥1,740.
4. Every image uses `object-fit: contain`, full card visible, no crop at
   375 / 430 / 768 / desktop.
5. `full` → "2 sources"; `limited` → "Yuyu-Tei only". No fake trend,
   sparkline, or percentage anywhere.
6. Search returns individual prints for `OP01-013`, `Sanji`, `サンジ`.
7. No mock/demo dataset reachable from the page.

## Verification
- Focused vitest for catalogue + adapter + tile.
- `npm run lint`, `tsc --noEmit`, `npm run test`, `npm run build`.
- Desktop + mobile screenshots on deployed staging.
- Fresh `cardpirate-visual-reviewer` score (mandatory gate).

## Commit
One focused commit.

## Known blocker carried into Lay-down
CSP `img-src` in `apps/web/next.config.ts` allowlists only
`https://card.yuyu-tei.jp`. All 20 print images are on
`https://www.onepiece-cardgame.com`. Without adding that host every card
renders as a placeholder — this is a frontend code change (not a Vercel env
var), verified serving real PNGs, so it is made inside this tranche.

---

## After evidence (captured on deployed staging, 2026-08-12)

Deployed: `https://optcg-price-tracker-staging.vercel.app/cards`
Commits: `fe46f58` (print-centric catalogue), `660f7bb` (same-origin artwork proxy)

| File | What it shows |
|---|---|
| `before-desktop-1440.png` | Legacy card-keyed catalogue: 18/20 grey placeholders, siblings collapsed |
| `before-mobile-375.png` | Same, mobile |
| `after-desktop-1440.png` | 20 prints, full artwork, honest coverage chips |
| `after-mobile-375.png` | 2-column grid, full artwork, search usable |
| `after-mobile-430.png` | 2-column grid at 430px |
| `after-tablet-768.png` | 3-column grid at 768px |
| `after-search-sanji.png` | `?q=Sanji` → 3 individual prints, not one collapsed row |
| `after-siblings-op01-013.png` | `?q=OP01-013` → base ¥120 "Yuyu-Tei only" + parallel ¥1,740 "2 sources" |
| `after-print-detail-3.png` | Minimal `/prints/3` landing page (next tranche's subject) |

### Measured on the deployed page (not inferred from source)

Instrumented via Playwright against the live staging URL, scrolling every tile
into view to defeat lazy loading:

| Viewport | imgs | loaded | `object-fit` != contain | clipped | h-scroll | search visible |
|---|---|---|---|---|---|---|
| 375px | 20 | 20 | 0 | 0 | no | yes |
| 430px | 20 | 20 | 0 | 0 | no | yes |
| 768px | 20 | 20 | 0 | 0 | no | yes |
| 1440px | 20 | 20 | 0 | 0 | no | yes |

"clipped" compares each image's rendered box against the box `contain` would
produce at its natural size; 0 means no artwork is cut off anywhere.
Natural size 600x838 (ratio 0.716) on every tile.

All 20 rendered tiles were cross-checked field-by-field against
`GET /prints` (card code, Market Index value, coverage wording, and image
filename): **20/20 matched, 0 mismatches**. Coverage totals: 12 full,
8 limited, 0 no-data.

Sibling pairs, each with distinct price AND distinct artwork file:

| Card | base | parallel | distinct images |
|---|---|---|---|
| OP01-013 Sanji | ¥120 | ¥1,740 | 2/2 |
| OP03-001 Ace | ¥810 | ¥5,490 | 2/2 |
| OP03-013 Marco | ¥220 | ¥780 | 2/2 |
| OP04-001 Vivi | ¥540 | ¥8,434 | 2/2 |
| OP04-044 Kaido | ¥540 | ¥1,040 | 2/2 |

### Note on the artwork itself

Bandai's official card list serves these images with a visible **"SAMPLE"
watermark** baked into the artwork. That is genuine source imagery, not a
placeholder and not fabricated - but it is a real product consideration for a
launch-facing catalogue and is called out here rather than buried.
