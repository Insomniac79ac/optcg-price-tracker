"""The one Yuyu-Tei/Atlas card-code grammar, for every module in this service.

WHY THIS MODULE EXISTS. The pattern used to be declared twice, under the same
name, with two different meanings: `discover.CARD_CODE_RE` covered all five
catalogue shapes, while `extractor.CARD_CODE_RE` was still the older OP-only
pattern. Nothing linked them, so they drifted - and the drift was invisible
because the two definitions shared a name and both looked authoritative. The
comments in discovery_listing and discovery_probe even described their import
as "the same grammar the rest of the collector uses", which by then was false.

WHAT THE DRIFT COST, measured on staging 2026-09-01: the collector fetched
four approved EB-01 product pages, all HTTP 200, all serving the card code,
price and stock in exactly the same markup as an OP page - and wrote nothing.
The OP-only pattern could not match "EB01-055", so `_find_main_detail_container`
(which gates on a card code appearing in the container text) selected no
container at all, and the card-code, price and stock readers that take that
container were each starved in turn. The failure surfaced as
`displayed=None`, `dom_price_candidates=[]`, `dom_stock_element=null` - three
symptoms, one cause, none of them pointing at a regex.

DEPENDENCY-FREE ON PURPOSE. Only `re`. `extractor` is otherwise pure parsing
(re + BeautifulSoup) and must stay importable without Playwright; importing
the grammar from `discover`, which pulls in `playwright.sync_api` at module
level, would drag a browser dependency into extraction and its tests. So the
grammar lives here, below both, and both import it.
"""

from __future__ import annotations

import re

# Every card-code shape Atlas actually holds, derived from canonical_cards on
# 2026-09-01 rather than guessed - all 2,710 codes fall into exactly five:
#
#   OP##-###   2,033    ST##-###  382    EB##-###  245
#   PRB##-###     19    P-###      31
#
# `P-###` is listed last and kept separate because promos carry no two-digit
# set number; it must not be folded into the ##-### branch. PRB is tried
# before the P branch so "PRB01-001" can never be read as a promo.
#
# Word-bounded at both ends so a code embedded in a longer token (an image
# path, a URL slug, a longer identifier) is not mistaken for a card code.
CARD_CODE_RE = re.compile(r"\b(?:(?:OP|ST|EB|PRB)\d{2}-\d{3}|P-\d{3})\b")

__all__ = ["CARD_CODE_RE"]
