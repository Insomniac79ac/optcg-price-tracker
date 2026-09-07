# Tranche: Card artwork frame consistency

## Page or component
`CardImageFrame` — the shared card-artwork frame.

In scope: `/cards` (`PrintCardTile`) and Analytics "Cards in this view"
(`MarketLandscapeCards`) — the two public surfaces where the inconsistency was
reported. The Discover hero fan (`CatalogueIntro`) passes the same props and is
carried along by the same fix.

Out of scope: `CardVaultTile` (authenticated `/collection/vault` and the
dashboard highlights). It passes neither `padded` nor `geometry`, so it has
always framed its thumbnails differently and this tranche does not change it.
That is a consumer-level choice on a different, denser surface — not the
shared-layer defect — and folding it in would be scope creep. Worth its own
tranche.

## Emotional outcome
A wall of cards should read as a wall of *cards* — one shelf, one mount, one
framing language. A collector should never wonder why one card in a row sits
tighter in its frame than the card beside it.

## User's five-second impression
"These are all presented the same way."

## Must visibly change
- Prints carrying verified display-image geometry stop rendering edge-to-edge and
  pick up the same inset every other tile has.
- `/cards` and Analytics show one framing language for equivalent inputs.

## Must not change
- Analytics layout, the card-strip sizing, or the sparse-row difference from the
  prior tranche.
- Pricing semantics, source logic, Market Index logic, any backend.
- Card identity or image-source selection — no client-side image rewriting.
- Responsive card geometry, aspect ratio, accessibility behaviour.
- The bounded placement path itself, which is still what a genuinely composited
  asset needs.

## Root cause

`CardImageFrame` has two mutually exclusive render paths, and the `padded` prop —
a 6px `p-1.5` inset — reached only one of them.

- **Contain path** (no geometry): `object-contain` + `p-1.5`. Inset.
- **Bounded path** (valid geometry whose canvas matches the loaded image):
  absolute placement from `placeCardBox`, with no padding at all. Edge-to-edge.

Bounded placement was built for assets that composite a card onto a **larger**
canvas — the SNKRDUNK case, where plain contain fits the *canvas* and the card
lands at ~43% of the frame. Correcting that is worth losing the inset.

But the geometry actually being served is not that shape. All 20 geometry
records on staging (of 2,000 prints scanned) are R2-mirrored **tight crops**:
`canvas_px` 600×838, `card_bbox_px` `{0, 0, 600, 838}` — the card box *is* the
whole canvas, and the asset has no alpha channel at all. For such an asset
`placeCardBox` returns `widthPct: 100, leftPct: 0, topPct: ~0.006` — exactly
filling the frame. Bounded placement had nothing to correct; it only dropped the
padding.

So ~1% of prints rendered flush while the other ~99% rendered inset, in the same
grid. Every consumer passes `padded` and `geometry` identically, so the
divergence was entirely internal to the shared component.

## Fix

`hasCanvasPadding()` in `src/lib/cardGeometry.ts`, consulted alongside
`isValidGeometry()`. Bounded placement now engages only when the canvas actually
carries margin outside the card box. A tight crop takes the contain path, so it
is framed by the same code, with the same inset, as every other tile.

This is consistency by construction rather than by matching two sets of
arithmetic. Both paths fit a tight crop the same way; bounded placement was
simply bypassing the inset and rendering the card flush and slightly larger.

An earlier attempt insetting the bounded clip box instead was rejected: it
shrinks the box `placeCardBox` centres against, so the card sat ~5.6px high
(gutter 7px top, 12.6px bottom). That is visible in a measurement and was not a
real fix.

## Measured result

Full-page CDP measurement of the three `/cards?q=OP01-013` tiles, desktop 1440×900.
Two of the three carry geometry; the third does not.

| tile | before | after |
|---|---|---|
| 1 (geometry) | bounded — gutter 1.0/1.0/1.0/1.8, art 216.8×302.8 | contain — gutter 7.0/7.0/9.8/9.8, art 204.8×286.0 |
| 2 (no geometry) | contain — gutter 7.0/7.0/9.8/9.8, art 204.8×286.0 | unchanged |
| 3 (geometry) | bounded — gutter 1.0/1.0/1.0/1.8, art 216.8×302.8 | contain — gutter 7.0/7.0/9.8/9.8, art 204.8×286.0 |

Gutters are left/right/top/bottom in CSS px on a 218.8×305.6 frame. Before, the
two geometry tiles sat flush (1px) with artwork 12px wider than their neighbour;
after, all three report the identical path, artwork size and gutter. Nothing
overflows its frame in either state.

Console: 0 error/warning events on `/cards?q=OP01-013` (including a second load,
which exercises the cached-image `measureOnMount` path) and on
`/analytics?set=OP-01`.

## Evidence

Captured from a **production build** (`next build && next start`) against real
staging data, via the reusable CDP harness described in
`2026-09-06-market-landscape/capture_evidence.py`. No view is stubbed. The two
`before-*` files were captured the same way from a build of the unmodified HEAD
sources, so they are a like-for-like comparison.

| file | view | why |
|---|---|---|
| `before-desktop-01-cards-mixed-framing.png` | `/cards?q=OP01-013`, 1440×900 | The defect: tiles 1 and 3 flush against tile 2's inset. |
| `before-mobile-01-cards-mixed-framing.png` | same, 390×844 | The defect at mobile width. |
| `desktop-01-cards-mixed-framing.png` | `/cards?q=OP01-013`, 1440×900 | Three prints of one card: two carry geometry (previously edge-to-edge), one does not (previously inset). Both former behaviours side by side in one grid. |
| `mobile-01-cards-mixed-framing.png` | same, 390×844 | Same comparison at mobile width. |
| `desktop-02-analytics-strip.png` | `/analytics?set=OP-01`, 1440×900 | "Cards in this view" — OP01-001 and OP01-002 carry geometry, the other four do not, alternating across the strip. |
| `mobile-02-analytics-strip.png` | same, 390×844 | Same strip at mobile width. |
