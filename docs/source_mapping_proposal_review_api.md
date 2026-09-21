# Persisted source-mapping proposal review API

Source Mapping Coverage 1B1C1A adds a GET-only review read model beneath
`/admin/source-mapping-proposals/review`. It reads the persisted proposal queue;
it does not rerun the resolver, fetch source sites, or write proposal, candidate,
mapping, observation, attempt, or snapshot rows.

## Existing-route audit

The pre-existing routes remain compatible:

- `GET /summary` and `GET /releases` return resolver-analysis report dictionaries
  and still run the read-only resolver analysis.
- `GET /groups` returns raw `SourceMappingProposalGroup` fields plus the shared
  `PaginationMeta`. Its unfiltered request uses two SQL statements (count and
  page); a source-name filter adds one source lookup.
- `GET /groups/{proposal_group_id}` returns the raw group and alternatives. Its
  `selectinload` path uses two SQL statements (group and alternatives).

Those persisted group responses did not provide source names, source-specific
candidate fields, canonical names, release display context, print metadata, or
resolved display images. They also exposed the full evidence JSON in every old
list row because that is part of the established compatibility contract.

The reusable presentation components are
`get_display_images_for_prints` (one bulk query, stored/owned evidence only),
`printing_label`, and `special_print_label`. SNKRDUNK print-options already use
the same helpers. Candidate read models supply stored Yuyu-Tei and SNKRDUNK
listing evidence; approval services are not imported or copied into this read
path.

## Review routes

- `GET /review/summary`: SQL-aggregated persisted queue totals, source and
  resolution matrices, alternative cardinality, release state, stored candidate
  image state, and recommendation state.
- `GET /review/releases`: every real `ReleaseProduct` plus one explicit null-ID
  unresolved-release bucket. Membership is always
  `card_prints.release_product_id`.
- `GET /review/groups`: lightweight enriched queue rows.
- `GET /review/groups/{proposal_group_id}`: complete candidate, evidence,
  canonical card, release, exact-print alternatives, review state, historical
  state, resulting mapping linkage, and separately labelled legacy
  compatibility metadata.

All routes use the existing admin-token dependency. There are no POST, PATCH,
PUT, or DELETE review routes.

## Filtering, sorting, and pagination

The list accepts `source`, `release_product_id`, `release_code`,
`unresolved_release`, `resolution_status`, `review_status`, `card_code`,
`candidate_id`, `proposal_group_id`, `has_candidate_image`,
`has_recommended_alternative`, `include_superseded`, and deterministic free text
`q`. Free text searches stored card codes/names, candidate titles/names,
canonical listing identity, and candidate IDs; it performs no fuzzy inference.

Sort values are `default`, `id_asc`, `id_desc`, `created_newest`,
`created_oldest`, `release_newest`, `release_oldest`, `exact_first`,
`ambiguous_first`, `source`, and `card_code`. Every order ends in proposal ID
as a stable tie-breaker. The default puts resolved releases first, then uses the
deterministic release-product-ID fallback, resolution priority, source, card
code, and proposal ID. Null-release proposals are last.

`limit` must be one of 25, 50, 100, or 200; the default is 50. `offset` is
non-negative. Responses use `PaginationMeta`.

`release_products` has no authoritative release-date/order column. The contract
therefore returns `chronology_available=false` and
`authoritative_release_order=null` rather than inferring chronology from card
codes, names, source text, creation order, or legacy `Card.set_code`. Coded
products are returned in stable release-product-ID descending order, uncoded
products follow in the same stable order, and the unresolved bucket is last.

## Data and image authority

- `SourceCardMapping.card_print_id` is authoritative mapping lineage.
- Alternatives identify exact `CardPrint` rows.
- `CardPrint.release_product_id` is authoritative product membership, including
  mixed-code OP17 printings.
- `CanonicalCard` describes card-family/rules identity.
- Legacy `Card` and `card_id` appear only under `compatibility` in detail.

Candidate image URLs are stored candidate fields. Print display images use the
existing batch resolver, which reads stored mapping evidence and locally owned
asset metadata without network requests. Missing candidate and print artwork is
represented explicitly with `image_missing`; the API performs no crop,
thumbnail transformation, advisory fetch, download, or persistence.

## Query bound

The list first pages proposal IDs/context and then bulk-loads each related
population. SQL statement-count tests cover one, 25, and 100 returned rows.
Measured on the SQLite test fixture:

- one item: 6 statements;
- 25 mixed-source items: 7 statements;
- 100 mixed-source items: 7 statements.

The corresponding in-process enriched-page timings were approximately 30 ms
for both 25 and 100 rows. The count is independent of page size; there is no
candidate, alternative, print, release, or image query per row. A dedicated
PostgreSQL test exercises the summary, release aggregation, image/recommendation
filters, and enriched list SQL.
