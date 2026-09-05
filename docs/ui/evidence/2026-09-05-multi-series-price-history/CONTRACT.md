# Tranche: Multi-series price history (Analytics 0C)

## Page or component
`/prints/[id]` — the EXISTING "Price history" section. No new page, no new
route, no standalone analytics surface.

## Emotional outcome
A collector can see Market Index and each independent platform beside each
other for this exact printing, tell which line is whose, and take a platform
off the chart when they only care about one — without ever being shown a line
that joins two things that were measured differently.

## User's five-second impression
"Market Index and the shops it reads, on one small chart, and I can switch
them off."

## Must visibly change
- The section's chart is now driven by `GET /prints/{id}/series`, not
  reconstructed from `/prices`.
- A compact chip row that is BOTH the legend and the filter: "Market Index",
  "Yuyu-Tei · Retail price", "SNKRDUNK · Current listing", and any future
  platform, automatically.
- A 7D / 30D / All window control. Default 30D. No 90D.
- Market Index v1/v2/v3 rendered as visually related but DISCONNECTED pieces,
  with a dashed marker where the measurement changed.
- A tooltip naming the date, each selected series, its value, and — for a
  reading that is not a market price — why.

## Must not change
- Backend, Market Index arithmetic, source semantics, collectors.
- Card artwork, identity, Market Index block, source panels, source range,
  About this print, Other printings.
- The evidence ROWS beneath the chart, which still come from `/prices`.
- Discover, `/cards`, market routes, search.

## Real data available
- `GET /prints/{id}/series?window=7d|30d|all` — per-series `segments`,
  `breaks`, `coverage`, `role`, `available` / `unavailable_reason`.
- The endpoint names no platforms: it returns Market Index plus every source
  that has actually observed THIS print.

## Acceptance criteria
1. Market Index + all available PRIMARY source series selected by default;
   auxiliary series are not.
2. No chip at all for a source with no history for this print — never a
   disabled control.
3. A line is NEVER stroked across a server segment boundary, nor across a
   point that is not a market price.
4. Changing the window RE-REQUESTS the backend with that window; it never
   slices a payload already in hand.
5. A constrained reading (SNKRDUNK's ¥1,000 platform floor) is never plotted
   and never substituted with ¥0; it stays visible in the tooltip and row,
   marked as not a market price.
6. A one-point series is one dot and no line.
7. No 90D control; no confidence, reliability, agreement percentage, or
   fabricated daily change anywhere in the section.
8. Nothing in the client reads or depends on stored `price_type`.
9. No horizontal overflow at 390px; controls stay chips, not a panel.

## Verification

- Focused vitest, full vitest (1031 passing), `tsc --noEmit`, `git diff --check`.
- ESLint on every changed file: one `react-hooks/set-state-in-effect` error,
  confirmed PRE-EXISTING by linting `HEAD`'s own copy of `page.tsx` (same
  single error, line 141 there / 174 here). No new lint failure.
- Live capture against real staging data, desktop 1440 + mobile 390, on a
  production build (`next build` + `next start`) pointed at deployed staging
  through a local CORS-injecting proxy.
- `window-requests.log` in this folder: the proxy's own record of one
  `/series` request per window press, each naming the window pressed.
- Fresh `cardpirate-visual-reviewer` pass, then a second fresh pass after the
  fixes below.

### What the live evidence covers — corrected 0C-2

An earlier round of this tranche claimed staging held "only 20 prints" and
deleted three scenarios as unreproducible. **That claim was wrong** — print ids
are sparse, and a contiguous scan of 1..120 said nothing about a 4,316-print
catalogue. See `STAGING-EVIDENCE.md` for the identity proof and the root
cause. All three scenarios exist and are now captured on real prints:

| scenario | print | what makes it that case |
|---|---|---|
| Market Index + Yuyu-Tei + SNKRDUNK | 1 (OP01-001) | 17 such prints; also the only missing-day gap on staging |
| Yuyu-Tei only, index exactly overlapping it | 4 (OP01-013) | 247 Yuyu-only prints; 224 have exact index/source overlap |
| SNKRDUNK only | 5687 (OP01-078) | 26 SNKRDUNK-only prints |
| SNKRDUNK only, wholly constrained | 6806 (OP01-013) | every reading is the ¥1,000 platform floor |
| constrained ¥1,000 beside plotted sources | 5 (OP02-013) | 14 such prints |
| no history at all | 3580 (OP17-040) | 4,026 such prints; section renders nothing |
| index version break | 1, and 223 others | `index_version_change` + `source_semantics_version_change` |

**Fixture coverage only**, because staging genuinely contains no instance:

- **source instrument / reference-type break** — 0 prints across all 290 priced
  prints carry one. Covered by `printSeries.test.ts` §G ("never joins
  listing_floor to transaction_median as one instrument", "keeps two unlabelled
  instruments apart rather than welding them").
- **one-point series** — the sparsest real series has 10 points. Covered by
  `printSeries.test.ts` §E ("keeps a one-point series as one point and draws no
  line through it").

## Defects found by the fresh reviewer, and fixed

The first visual-reviewer pass returned FAIL. Three findings were real and are
fixed in this tranche; a fourth was found while re-capturing.

1. **The Market Index was invisible wherever it agreed with a source.** The
   index is Atlas's combination of the platforms beneath it, so on a print with
   one eligible source it holds exactly that source's value; painted in server
   order at equal width it went down first and the source painted over it - a
   lit gold chip with no gold on the plot, on four of seven charted prints.
   Fixed by `seriesPaintOrder` (index drawn last) plus a narrower index stroke,
   so agreement reads as a gold core inside a coloured halo. No point moved.
2. **Break marks were not attributable, and the caption was falsifiable.** The
   marks were drawn in the grid's neutral grey at full plot height, so on a
   print where only the index broke, a platform line crossed them unbroken -
   directly under "Lines are not joined across them." Marks are now tinted to
   the series they belong to, and the caption names that series.
3. **Both new control groups sat on `text-faint`** (3.12:1) and declared no
   `focus-visible`, unlike every sibling control in the component library.
   Moved to `text-muted` and given the codebase's teal focus ring.
4. **The tooltip overflowed the page at 390px** (39px of horizontal scroll),
   found only once the mobile tooltip was actually captured - the previous
   round's "mobile tooltip" images contained no tooltip. The tooltip is now
   width-capped and wraps. Touch was verified too: the tooltip IS reachable by
   tap, which the earlier evidence had left an open question.

### Round 2 — a second fresh pass, three more fixed

The re-audit confirmed all four fixes above landed and found three more:

5. **A lit chip for a platform with no line.** On the constrained print,
   "SNKRDUNK · Current listing" was selected with a solid swatch while nothing
   SNKRDUNK was drawn (correctly — every reading is the ¥1,000 floor). That is
   the SAME untruth as the round-1 index defect, reproduced for a source. The
   chip's swatch is now broken rather than solid, its accessible name says
   "nothing to plot in this window", and the chart carries a line naming the
   platform and pointing at the readings below. `plottedCount` already existed
   on the model; nothing new had to be computed.
6. **The empty-chart message sat at `text-faint`** — the tier `docs/brand.md`
   reserves for non-essential labels — while being the only content in the
   box. Moved to `text-secondary`, matching `CollectorEmptyState`'s own split
   of primary line vs secondary line.
7. **A white UA focus ring painted over the chart on tap.** Recharts puts a
   `tabIndex` on its root, so touching the plot drew the browser's default
   outline — loud, and off-brand beside the teal ring this tranche had just
   adopted. The chart now uses that same teal ring.

### Round 3 (0C-2) — the two vocabularies, RESOLVED

The chip said "SNKRDUNK · Current listing" while the row beneath said
"SNKRDUNK listing floor": two names for one reading, in one section. Escalated
out of 0C, and now settled on ONE collector vocabulary.

`printPriceHistory.ts` no longer keeps its own words. It maps the STORED
`price_type` onto the API-facing `reference_type` that names the same quantity
(`floor`->`listing_floor`, `sell`->`retail_sell`) and asks
`@/lib/sourceEvidence` — the single module that turns a quantity into
collector copy, and the same one the chips and tooltip already asked. Two
label tables became one, which is why the drift cannot recur.

Visible result, everywhere in the section:

- `SNKRDUNK · Current listing` — chip, chart note, tooltip, evidence row
- `Yuyu-Tei · Retail price` — chip, chart note, tooltip, evidence row
- `Market Index` — no platform, no instrument suffix
- unknown stored type -> humanised token, never dropped, never guessed

`reference_type = listing_floor` is untouched in the API and the database, and
`priceType` is still carried on the row view as its identity — it is simply
never rendered. The "not a completed sale" explanation still comes from
`sourceEvidence`'s own sentence ("Lowest current listing observed on this
source. Asking prices are not completed sales...").

## Commit
Left UNCOMMITTED for review, per task instruction.
