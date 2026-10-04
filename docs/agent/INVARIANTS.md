# Card Pirate invariants

Adopted/reaffirmed: 2026-10-04. These constraints apply to every mission and every
authority level in [AUTONOMY_POLICY.md](AUTONOMY_POLICY.md).

## Identity

`CanonicalCard → CardPrint → SourceCardMapping → PriceObservation`

- The exact physical CardPrint is the priced identity; preserve observation lineage.
- `CardPrint.release_product_id` is authoritative. Never infer release membership
  from a card-code prefix.
- No duplicate active mapping for the same exact CardPrint/source.
- Ambiguous identities are never auto-approved. Existing exact identity guards
  and manual mappings take precedence over fuzzy/automatic matches.
- Preserve source-specific approval gates, including SNKRDUNK manual verification.
  Approval is not evidence that a mapping has collected healthy current prices.

## Yuyu

Promotional/sale prices may remain stored internally as provenance. They are:

- NOT customer-facing.
- NOT public price-history points.
- NOT Market Index eligible.
- NOT Market Value inputs.

Struck former prices are NEVER substituted. Do not manufacture a regular price
from a sale page or expose an internal provenance record as a public price.

## Regular price freshness

The standard successful-check target is **24 hours**; dispatch is due at
**23 hours**, leaving one hour of execution headroom. These are requirements,
not a claim that current staging meets them. Apply shared policy consistently
across sources; do not lengthen freshness to disguise a capacity deficit.

A successful explicit no-listing check may advance successful-check freshness
and availability. The historical old price must NOT become fresh: retain its
original observation timestamp. Absence, parsing failure and a source denial
are not successful no-listing checks.

Failure does not advance successful-check freshness and follows bounded
retry/backoff. Keep attempt time, successful-check time, valid-price observation
time, transaction time and publication time distinct. Reparse/replay/calculation
does not create a new source check. Existing separately defined high-interest
policy is not silently changed by the standard target.

## Market Value and history

Forward publication remains completion-receipt-gated. Do not fabricate completion
receipts. A scheduled invocation or partial run is not completion evidence.

**September 27–28, 2026 remain intentional historical gaps.** No interpolation,
invented history or substituted completion receipts may fill them. Published
historical data is immutable without an explicit human decision. A reversible
repair to nonpublished operational state does not authorize rewriting publication.

Preserve the established Market Index / Market Value methodology and economic
meaning. PSA10 asks remain a distinct category, not raw floor prices or raw
Market Index/Market Value inputs.

## Data and source integrity

Persist raw snapshots before extracting or transforming source data. Build and
validate new behavior against mocks before live scraping. Preserve manual mappings,
foreign-key lineage, deduplication, singleton/lease guards, admission and source
budgets. Never create duplicate or uncontrolled source requests. Widespread
blocking/rate limiting requires containment, not evasive retries.

Prices are stored in JPY; timestamps in UTC. Never commit credentials or secrets.
Preserve private customer data and existing authentication/security policy.

## Production

Production is never modified without explicit human authorization. A staging
mission does not authorize production access, deployment, configuration changes,
database writes or effects through shared resources. Verify actual destinations.
