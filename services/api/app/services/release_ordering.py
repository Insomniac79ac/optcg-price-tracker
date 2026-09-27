"""Shared authoritative chronology for public release lists."""

from app.models.release_product import ReleaseProduct

ORDERING_BASIS = "released_on_desc_then_deterministic_fallback"


def public_release_ordering():
    return (
        ReleaseProduct.released_on.desc().nulls_last(),
        ReleaseProduct.source_catalogue.asc(),
        ReleaseProduct.official_code.asc().nulls_last(),
        ReleaseProduct.display_name.asc(),
        ReleaseProduct.id.asc(),
    )
