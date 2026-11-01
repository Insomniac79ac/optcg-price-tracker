"""Owner-confirmed SNKRDUNK products that start published discovery in sets it cannot reach.

Published discovery only inspects sitemap neighbours of approved, manually verified SNKRDUNK
mappings. Every such mapping sat in OP-01 to OP-04 and EB-01, so the neighbourhoods ran out on
2026-10-23 and 21 sets (1,139 of the missing high-rarity prints) had no starting point (owner
2026-11-01, perfectionist). A seed is a starting point only: one public product URL per entry,
read from the committed seeds file. It is never a mapping, never priced and never an identity
decision; the products found around it become candidates like any others.
"""

from __future__ import annotations

import json
from pathlib import Path

from opcg_source_identity import canonical_source_listing_identity

SEEDS_FILE = Path(__file__).with_name("discovery_seeds.json")
MAX_SEEDS = 200


def seed_identities(path: Path = SEEDS_FILE) -> list[str]:
    """Distinct canonical listing identities of the committed seeds, in file order (fail closed)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("seeds"), list):
        raise ValueError("unrecognized discovery seeds file")
    seeds = data["seeds"]
    if len(seeds) > MAX_SEEDS:
        raise ValueError("discovery seeds exceed bound")
    identities = []
    for seed in seeds:
        if not isinstance(seed, dict) or not all(
            isinstance(seed.get(k), str) and seed[k] for k in ("release", "url", "title", "confirmed_by")
        ):
            raise ValueError("every seed needs release, url, title and confirmed_by")
        identity = canonical_source_listing_identity("snkrdunk", seed["url"])
        if not identity or identity in identities:
            raise ValueError("distinct public SNKRDUNK product seeds required")
        identities.append(identity)
    return identities
