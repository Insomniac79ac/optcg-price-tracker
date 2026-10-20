"""What a shop's product title says, parsed without guessing (new-sources plan §2.3).

A parsed title carries only what the text states: the card code, the rarity token, every other
marker verbatim, and the listing kind those markers imply. Identity is decided later by the
resolver (app.source_products.resolver); nothing here looks at the catalogue.

Kinds are the Yuyu-Tei F1 kinds (owner 2026-10-17): plain, parallel, special, foil. A title naming
ラメフォイル or 海賊旗フォイル is foil and never plain. Graded slabs and sealed product are kinds of
their own and never become raw prices. A marker the rules do not know leaves the kind "unknown",
which the resolver quarantines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

CODE = re.compile(r"(?:OP|EB|ST|PRB)[0-9]{2}-[0-9]{3}|P-[0-9]{3}")
ORDINARY_RARITIES = frozenset({"C", "UC", "R", "SR", "SEC", "L", "P", "TR"})
# Rarity tokens that are a special print on their own (TR is an official special rarity).
SPECIAL_RARITIES = frozenset({"TR"})
# A bare promo P names no kind (plan §2.3): promo parallels are not reliably marked.
KINDLESS_RARITIES = frozenset({"P"})
FOIL_MARKERS = ("ラメフォイル", "海賊旗フォイル")
PARALLEL_MARKERS = frozenset(
    {"パラレル", "スーパーパラレル", "レッドスーパーパラレル", "ゴールドスーパーパラレル"}
)
GRADED_WORDS = re.compile(r"PSA|BGS|CGC|ARS|鑑定")
SEALED_MARKERS = frozenset({"未開封"})


@dataclass(frozen=True)
class ParsedTitle:
    title: str
    name: str | None
    card_code: str | None
    rarity: str | None
    markers: tuple[str, ...] = field(default_factory=tuple)
    kind: str = "unknown"
    qualifier: str | None = None
    grade_key: str | None = None
    on_sale: bool = False

    @property
    def variant_markers(self) -> tuple[str, ...]:
        """Markers that may tell prints apart and so need a reviewed rendering."""
        return tuple(m for m in self.markers if m not in PARALLEL_MARKERS and m != "SP")


def is_foil(text: str) -> bool:
    return any(marker in text for marker in FOIL_MARKERS)


def kind_for(markers: tuple[str, ...], *, special: bool, parallel: bool, graded: bool, sealed: bool, title: str) -> str:
    """The listing kind, most specific first. Unknown markers do not make a title plain."""
    if graded:
        return "graded"
    if sealed:
        return "sealed"
    if is_foil(title):
        return "foil"
    if special:
        return "special"
    if parallel:
        return "parallel"
    return "plain" if not markers else "unknown"
