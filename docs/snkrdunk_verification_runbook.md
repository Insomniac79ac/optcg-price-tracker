# SNKRDUNK verification runbook

How to verify a SNKRDUNK collection run. Written after the 2026-08-11
production report reached a wrong conclusion by using the wrong endpoint.

## Rule 1 — verify per print, never per card

**Always use the print-centric read path. Never the legacy card-keyed one.**

| Use | Do not use |
|---|---|
| `GET /prints/{print_id}/market-index` | `GET /cards/{card_id}/market-index` |
| `GET /prints/{print_id}/prices` | card-keyed price helpers |
| `app.services.print_market_index.get_market_index_for_print` | `app.services.market_index.get_market_index_for_cards` |

### Why

Two `card_prints` (a base and a parallel treatment of the same card) bridge
through **one legacy `cards` row**. The legacy card-keyed index does not keep
their observations separate — by design, and documented in
`app.api.cards.get_card_market_index`'s own docstring.

The 2026-08-11 report used `get_market_index_for_cards` and produced:

> "9 of 9 cards resolve from both sources"

with a Sanji row pairing **Yuyu-Tei ¥120** with **SNKRDUNK ¥1,500**. Those two
values belong to *different prints* — print 4 (base) and print 3 (parallel).
The print endpoints never produced that row. **The API was correct; the
verification script was wrong.**

The correct print-level answer for the same data was **12 full two-source
prints, 8 Yuyu-Tei-only, 0 no-data** — a different number, over a different
unit, than the "9 cards" figure.

### Sanity check before trusting any coverage number

- Is the unit a **print_id**, not a card_id? Card-level counts are not
  comparable to print-level ones and must never be reported as such.
- Do sibling prints show **different** values? If a base and parallel report
  identical source values, suspect the legacy path.
- Does the row count match the number of **verified prints** (currently 20),
  not the number of legacy cards (currently fewer)?

Regression cover lives in `services/api/tests/test_prints.py` — including
`test_legacy_card_endpoint_does_merge_siblings_which_is_why_prints_exist`,
which asserts the legacy merge still happens so the trap stays visible.

## Rule 2 — read the batch outcome fields, not just the exit code

`batch_complete` reports:

| Field | Meaning |
|---|---|
| `mappings_selected` | eligible mappings found |
| `mappings_attempted` | actually processed |
| `mappings_identity_verified` | passed every identity gate |
| `mappings_written` | rows actually persisted |
| `mappings_floor_unavailable` | verified, but nothing listed — **a success** |
| `mappings_failed` | genuine failures |
| `failed_mapping_ids` | which ones |
| `stopped_reason` | source-wide denial, if any |
| `exit_code` | see below |

### Exit codes

| Code | Status | Meaning |
|---|---|---|
| `0` | `success` | every attempted mapping either wrote a row or was verified `floor_unavailable` |
| `1` | `source_wide_failure` | 403 / 429 / CAPTCHA / challenge — stop, do not retry |
| `2` | `partial_failure` | at least one genuine failure: identity, artwork, release, operational error, DB write failure |

A verified print whose A–D chips are all 出品待ち is **not** a failure. There is
simply nothing to record. Before 2026-08-11 these counted against the exit
code, so a wholly healthy 16-mapping batch exited 2 — which trains operators to
ignore non-zero exits. `mappings_failed` is the number to alert on.

## Rule 3 — check the zero-write invariant on validate-only runs

A validate-only run must leave `price_observations` and `raw_snapshots`
completely unchanged. `mappings_written` is always `0`; `mappings_would_write`
carries what *would* have been written.

## Rule 4 — read provenance from the run, not from assumption

`collection_written`, `collection_no_write` and `batch_mapping_result` emit:

- `card_code_authority` — `Bandai` or `Yuyu-Tei`
- `card_code_evidence_type` — e.g. `bandai_cardlist_image_url`
- `release_name_matched_via` — `Bandai official name` or `SNKRDUNK source-specific rendering`

Full evidence URLs stay out of logs (they are persisted in the mapping's
`match_explanation_json`). Never log credentials or connection strings.

See [snkrdunk_identity_authority.md](snkrdunk_identity_authority.md) for which
source may establish each field.
