"""Dorasuta (dorasuta.jp) title grammar, MEASURED in the source survey (SV §2.1, 2026-10-16).

    name(rarity[/marker...])(CODE)[【tag】]

Examples: 「モンキー・D・ルフィ(SEC★/パラレル)(OP05-119)」, 「シャンクス(SP/SR/金箔)(OP09-004)【3周年SP】」,
「ゴール・D・ロジャー(★SEC/ゴールドスーパーパラレル)(OP09-118)」. The card code is the last (CODE) group;
condition is not in the title but in the per-condition price rows of one product.
"""

from __future__ import annotations

import re

from app.source_products import grade_keys
from app.source_products.titles import (
    CODE,
    GRADED_WORDS,
    ORDINARY_RARITIES,
    PARALLEL_MARKERS,
    SEALED_MARKERS,
    SPECIAL_RARITIES,
    ParsedTitle,
    kind_for,
)

SOURCE = "dorasuta"
_TAIL = re.compile(r"\((" + CODE.pattern + r")\)\s*(?:【([^】]+)】)?\s*$")
_ATTRS = re.compile(r"\(([^()]*)\)\s*$")

# Per-condition price rows on one product (SV §2.1). Only 状態A is ever counted as raw.
CONDITIONS = {
    "状態A": grade_keys.raw("A"),
    "状態A特価": grade_keys.raw("damaged"),
    "状態C(プレイ用)": grade_keys.raw("play"),
    "状態C": grade_keys.raw("play"),
}


def grade_key_for_condition(label: str) -> str | None:
    """grade_key for a condition row label, or None for a label the rules do not know."""
    return CONDITIONS.get(label.strip())


def parse_title(title: str) -> ParsedTitle:
    text = title.strip()
    tail = _TAIL.search(text)
    if tail is None:
        return ParsedTitle(title=title, name=text or None, card_code=None, rarity=None,
                           kind="graded" if GRADED_WORDS.search(text) else "unknown")
    code, tag = tail.group(1), tail.group(2)
    head = text[: tail.start()].rstrip()
    attrs = _ATTRS.search(head)
    tokens: list[str] = []
    name = head
    if attrs is not None:
        tokens = [t.strip() for t in attrs.group(1).split("/") if t.strip()]
        name = head[: attrs.start()].rstrip()
    rarity = None
    markers: list[str] = []
    special = parallel = False
    for token in tokens:
        bare = token.replace("★", "")
        if "★" in token:
            markers.append("★")
        if bare == "SP":
            special = True
            markers.append("SP")
        elif bare in ORDINARY_RARITIES and rarity is None:
            rarity = bare
        elif bare:
            markers.append(bare)
            parallel = parallel or bare in PARALLEL_MARKERS
    if tag:
        markers.append(f"【{tag}】")
    special = special or rarity in SPECIAL_RARITIES
    graded = bool(GRADED_WORDS.search(text))
    sealed = any(m in SEALED_MARKERS for m in markers)
    bare_markers = tuple(markers)
    kind = kind_for(
        tuple(m for m in bare_markers if m not in PARALLEL_MARKERS and m != "SP"),
        special=special, parallel=parallel, graded=graded, sealed=sealed, title=text,
    )
    return ParsedTitle(title=title, name=name or None, card_code=code, rarity=rarity,
                       markers=bare_markers, kind=kind)
