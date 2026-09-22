from opcg_source_identity import canonical_source_listing_identity
from opcg_source_identity.vectors import verify_contract

from worker.matching.listing_identity import canonical_source_listing_identity as worker_identity


def test_shared_and_worker_contract():
    verify_contract(canonical_source_listing_identity)
    verify_contract(worker_identity)
