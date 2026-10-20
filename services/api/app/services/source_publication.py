"""Which sources customers may see. New-sources plan §2.5 (docs/agent/plans/new-sources/PLAN.md).

A source in PRE_CUTOVER_SOURCES has rows (shadow collection, plan D3/C3) but no public life yet:
no chart series, latest price, history, mover or alert reads it, and it is in none of the Market
Index inputs. Removing a name here is part of that source's owner-approved cutover (plan D4/C4,
RED), in the same PR as its SOURCE_SEMANTICS entry and splice row.

Every customer-facing read already passes through one of these, which consult this set:
- app.services.customer_prices.customer_price_clause (SQL reads),
- app.services.source_semantics.is_customer_price (in-memory filters),
- app.services.print_series.load_source_catalogue (which platforms a chart can name).
The worker keeps its own copy in worker/customer_prices.py (it does not install the API package);
tests/test_source_publication.py holds the two equal.
"""

from __future__ import annotations

PRE_CUTOVER_SOURCES: frozenset[str] = frozenset({"dorasuta", "cardrush"})


def is_public_source(source: str) -> bool:
    return source not in PRE_CUTOVER_SOURCES
