"""The one rule for whether a source mapping may contribute a price.

A price row is a claim that a specific printing sold for a specific amount at
a specific source. A mapping is what authorises that claim, and it authorises
it only in one state:

  * `is_active` - the mapping has not been withdrawn; and
  * `review_status == 'approved'` - a human confirmed, through the api's
    exact-print gate (app.services.exact_print_approval), which printing this
    listing actually sells.

`needs_review` is the explicit "nobody has confirmed this yet" state and
`rejected` is the explicit "this is wrong" state. Neither can back a price,
and an active-but-unapproved row is precisely the case that reads as safe and
is not: it is live, it is fetchable, and nothing about it has been verified.

WHY THIS MODULE EXISTS. The rule was already enforced in three separate write
paths - both production collectors' `validate_mapping_for_write` and the
SNKRDUNK candidate-price ingest - and NOT in `refresh_prices`, which filtered
on `is_active` alone and would happily price a `needs_review` mapping. The
collectors and the api are separate deployables that share no code, so their
copies necessarily stay copies; within the worker, though, there is no reason
for two jobs to spell the same rule two ways and drift again.

WHAT THIS DELIBERATELY DOES NOT DO. It says nothing about lineage. A mapping
that names an exact `card_print_id` and a legacy one that names only a
`card_id` are both priceable; which columns the resulting observation carries
is the writer's business (copied from the mapping, both-or-neither), not this
gate's. And it is a gate on WRITING new prices only - observations already
written stay exactly as they are when a mapping is later unapproved, because
they record what was true when they were taken.
"""

from worker.models import SourceCardMapping

APPROVED_REVIEW_STATUS = "approved"

# SQL-level form, for callers that select mappings in bulk. Spread into a
# query with `.filter(*PRICEABLE_MAPPING_CONDITIONS)`.
PRICEABLE_MAPPING_CONDITIONS = (
    SourceCardMapping.is_active.is_(True),
    SourceCardMapping.review_status == APPROVED_REVIEW_STATUS,
)


def is_priceable_mapping(mapping: SourceCardMapping) -> bool:
    """In-Python form of the same rule, for callers holding a loaded row."""
    return bool(mapping.is_active) and mapping.review_status == APPROVED_REVIEW_STATUS
