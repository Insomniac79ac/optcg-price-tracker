"""Global listing integrity debt, independent of quality pagination/filters."""
from collections import defaultdict

from app.services.source_mapping_identity import load_source_mapping_identities, EXACT, LEGACY_COMPATIBILITY, BROKEN


def mapping_listing_report(db):
    groups = defaultdict(list)
    report = dict(superseded_historical_rows=0, unparseable_canonical_identities=0,
                  current_exact_mappings=0, current_compatibility_only_mappings=0, broken_mappings=0)
    for identity in load_source_mapping_identities(db):
        mapping = identity.mapping
        current = mapping.superseded_at is None
        if not current:
            report["superseded_historical_rows"] += 1
        if mapping.canonical_source_listing_identity is None:
            report["unparseable_canonical_identities"] += 1
        elif current:
            groups[(mapping.source_id, mapping.canonical_source_listing_identity)].append(mapping.id)
        if current and identity.classification == EXACT:
            report["current_exact_mappings"] += 1
        if current and identity.classification == LEGACY_COMPATIBILITY:
            report["current_compatibility_only_mappings"] += 1
        if identity.classification == BROKEN:
            report["broken_mappings"] += 1
    report["duplicate_current_identities"] = [
        dict(source_id=source, canonical_source_listing_identity=listing, mapping_ids=ids)
        for (source, listing), ids in sorted(groups.items()) if len(ids) > 1
    ]
    report["duplicate_current_canonical_identities"] = len(report["duplicate_current_identities"])
    return report
