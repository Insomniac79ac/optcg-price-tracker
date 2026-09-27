"""Pure, shared serialization of the frozen A2/A3 evidence (no replay/writer)."""

import hashlib
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ActivePrintIdentity:
    card_print_id: int
    release_product_id: int


def membership_revision(active_prints: Iterable[ActivePrintIdentity]) -> str:
    payload = "\n".join(
        f"{row.card_print_id}:{row.release_product_id}"
        for row in sorted(active_prints, key=lambda row: row.card_print_id)
    )
    return (
        "current-corrected-card-print-release-v1:"
        + hashlib.sha256(payload.encode("utf-8")).hexdigest()
    )


def version_pairs_text(pairs: Iterable[tuple[int, int]]) -> str:
    """Canonical compact representation of exact (index, semantics) pairs."""
    return ",".join(f"{index}:{semantics}" for index, semantics in sorted(set(pairs)))


def publication_reasons_text(reasons: Iterable[object]) -> str:
    """Preserve A2 reason order without inventing another vocabulary."""
    values = [getattr(reason, "value", str(reason)) for reason in reasons]
    if not values:
        raise ValueError("a movement step must carry at least one publication reason")
    return "|".join(values)
