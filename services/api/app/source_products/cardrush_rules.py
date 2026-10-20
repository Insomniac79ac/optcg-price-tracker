"""CardRush (cardrush-op.jp) title grammar, MEASURED on 4,506 names (CardRush plan §1.3, 2026-10-16).

    [〔condition|graded〕][☆SALE☆][(qualifier)]name[(variant marker)...]【rarity】{code}

No condition label means 〔状態A〕 (/page/8). 〔※状態難/…鑑定済〕 is a flawed slab. Membership of group 42
(傷アリ特価) overrides the name label with raw:damaged; that is a group fact, applied by the collector.
`{-}` marks an uncoded item (DON!! and similar).
"""

from __future__ import annotations

import re

from app.source_products import grade_keys
from app.source_products.titles import (
    CODE,
    PARALLEL_MARKERS,
    SEALED_MARKERS,
    SPECIAL_RARITIES,
    ParsedTitle,
    kind_for,
)

SOURCE = "cardrush"
DAMAGED_GROUP_KEY = "42"
_PREFIX = re.compile(r"^〔([^〕]*)〕")
_SALE = "☆SALE☆"
_QUALIFIER = re.compile(r"^\(([^()]*)\)")
_TAIL = re.compile(r"【([^】]*)】\s*\{(" + CODE.pattern + r"|-)\}\s*$")
_MARKER = re.compile(r"\(([^()]*)\)\s*$")
_GRADED = re.compile(r"^(※状態難/)?(PSA|BGS|CGC|ARS)([0-9]{1,2}(?:\.5)?)?鑑定済$")
_RAW = {"状態A": "A", "状態A-": "A-", "状態B": "B", "状態C": "C"}


def grade_key_for_label(label: str | None) -> str | None:
    """grade_key from the 〔…〕 prefix; None when the label is not one the rules know."""
    if label is None:
        return grade_keys.raw("A")
    if label in _RAW:
        return grade_keys.raw(_RAW[label])
    graded = _GRADED.fullmatch(label)
    if graded:
        return grade_keys.graded(graded.group(2), graded.group(3), flawed=bool(graded.group(1)))
    return None


def parse_title(title: str) -> ParsedTitle:
    text = title.strip()
    label = None
    prefix = _PREFIX.match(text)
    if prefix:
        label = prefix.group(1)
        text = text[prefix.end():].lstrip()
    on_sale = text.startswith(_SALE)
    if on_sale:
        text = text[len(_SALE):].lstrip()
    qualifier = None
    q = _QUALIFIER.match(text)
    if q:
        qualifier = q.group(1)
        text = text[q.end():].lstrip()
    grade_key = grade_key_for_label(label)
    graded = grade_key is not None and grade_key.startswith("graded:")
    tail = _TAIL.search(text)
    if tail is None:
        return ParsedTitle(title=title, name=text or None, card_code=None, rarity=None,
                           kind="graded" if graded else "unknown", qualifier=qualifier,
                           grade_key=grade_key, on_sale=on_sale)
    rarity_token, code = tail.group(1).strip(), tail.group(2)
    head = text[: tail.start()].rstrip()
    markers: list[str] = []
    while (m := _MARKER.search(head)) is not None:
        markers.insert(0, m.group(1).strip())
        head = head[: m.start()].rstrip()
    rarity, _, suffix = rarity_token.partition("/")
    special = suffix == "SP" or "SP" in markers or rarity in SPECIAL_RARITIES
    parallel = suffix == "P" or any(m in PARALLEL_MARKERS for m in markers)
    sealed = any(m in SEALED_MARKERS for m in markers)
    kind_markers = tuple(m for m in markers if m not in PARALLEL_MARKERS and m != "SP")
    kind = kind_for(kind_markers, special=special, parallel=parallel, graded=graded, sealed=sealed,
                    title=title)
    if qualifier is not None and kind == "plain":
        kind = "unknown"  # (赤白版) and similar are distinct prints until a rendering says otherwise
    return ParsedTitle(
        title=title, name=head or None, card_code=None if code == "-" else code, rarity=None if rarity in {"", "-"} else rarity,
        markers=tuple(markers), kind=kind, qualifier=qualifier, grade_key=grade_key, on_sale=on_sale,
    )
