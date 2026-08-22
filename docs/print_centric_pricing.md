# Print-centric public pricing read model

Reference doc for the `/prints` API surface added to make public pricing
reads collectible-print-centric, so two prints of the same canonical card
(e.g. OP01-013 Sanji's two official artwork variants) can never contaminate
each other's prices, Market Index, or history.

Those two prints are distinct because they are **different printings**, not
because of the `treatment` label they carry. `treatment` is an Atlas editorial
classification, never the thing that establishes exact-print identity — see
[snkrdunk_identity_authority.md](snkrdunk_identity_authority.md).

See `docs/market_index.md` for the Market Index calculation itself (unchanged
by this task) and `docs/staging_data.md` for the five-print verified test
dataset.

## Root cause this fixes

Every public price/read helper prior to this task partitioned or filtered
strictly by the legacy `cards.id` (`card_id`), never by `card_prints.id`
(`card_print_id`):

- `app.services.latest_prices.get_latest_prices_for_cards` — its window
  function partitions `PARTITION BY (card_id, source_id, price_type)`, so
  when two card_prints bridge through the same legacy card_id, only the
  single latest-by-`(observed_at, id)` observation across *both* prints
  survives per source/price_type. This is what fed `GET /cards/{id}/
  market-index`, `GET /cards/catalogue`, and `/market/movers` — the one
  print's observation silently masked the other's.
- `GET /cards/{id}/prices` didn't hit that window function, but selected
  every observation for the legacy `card_id` with no `card_print_id` filter
  at all — merging two prints' histories into one undifferentiated series
  (a different form of the same contamination, at the history/trend layer).
- `card_print_id` / `canonical_card_id` / `source_card_mapping_id` were not
  read anywhere on the public path before this task, despite the schema and
  worker-side lineage population already existing (`b1c8f3e2_...`,
  `b858237e3706_...` migrations; `app.services.card_catalog_import`/
  `worker.jobs.refresh_prices` for population).

## New endpoints (`app/api/prints.py`)

| Endpoint | Purpose |
|---|---|
| `GET /prints` | Paginated print catalogue — one item per `card_print`, never merged with siblings |
| `GET /prints/{print_id}` | Print identity + Market Index + sibling prints |
| `GET /prints/{print_id}/market-index` | Market Index computed strictly from this print's own observations |
| `GET /prints/{print_id}/prices` | Full price history + per-series trend, strictly this print's own observations |

Every one of these resolves market data via `app.services.print_pricing`/
`app.services.print_market_index`, which filter every query by
`price_observations.card_print_id`. Because `card_print_id` is only ever set
together with `source_card_mapping_id` (`ck_price_observations_lineage_paired`),
a legacy, lineage-less observation (`card_print_id IS NULL`) can never match
any requested print id — no mock/legacy observation can become print-market
evidence.

Identity fields (`card_code`, `name_en`/`name_jp`, `rarity`, `card_type`,
`colors`) always come from the print's `CanonicalCard`, never from the
legacy `cards.rarity`/`cards.variant` columns.

## Legacy endpoints

`GET /cards/{id}`, `/cards/{id}/prices`, `/cards/{id}/market-index`, `/cards/
catalogue`, and `/market/movers` are unchanged and remain card_id-keyed for
backward compatibility with existing frontend routes. Their market/price
semantics are now documented in-code as legacy (see docstrings on
`get_card_market_index`/`get_card_prices` in `app/api/cards.py`). No new
frontend work should be built against them — new print-aware UI should call
the `/prints` endpoints instead.

## Image contract

`card_print.image_url` (exposed as `image_url` on both `CardPrintOut` and
`PrintCatalogueItemOut`) is the print's own original, full card image — not
a legacy `cards.image_url` fallback, since that could show one print's
artwork under a sibling print's identity. It may be `null` for a print whose
image hasn't been imported yet; consumers must not fall back to a sibling
print's or the legacy card's image.

Frontend consumers must render it the same way `CardImageFrame` (see
`apps/web/src/components/ui/CardImageFrame.tsx` and `docs/market_index.md`
"Image hosting") already renders `cards.image_url` today:

- preserve the full original card aspect ratio (fixed `aspect-[63/88]`
  container)
- `object-fit: contain` (Tailwind `object-contain`) — never `cover`
- no crop, no zoom that removes card edges
- no masking of any part of the card

This tranche does not add a new frontend component — `CardImageFrame` can be
pointed at a print's `image_url` unchanged once print-aware UI work begins.
