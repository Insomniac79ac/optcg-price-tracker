"""Turning one Yuyu-Tei listing row into the facts a candidate records.

WHY THE LISTING IS ENOUGH. Measured on 2026-09-01 across op01, op13 and eb01:
a category row carries the card code, a rarity token, the JP name with its
variant annotations, the price, the stock state and the artwork URL. Nothing
here opens a product page, so discovery costs exactly one request per set.

WHAT IS PRESERVED VERBATIM. `name_jp` keeps Yuyu-Tei's own annotations -
(パラレル), (スーパーパラレル), (レッドスーパーパラレル), (刻印なし) - and
`raw_listing_text` keeps the entire row. Those annotations are the only
listing-level evidence separating the 2+ prints behind one card code, so
stripping or normalising them would throw away the input the later exact-print
matcher depends on. Nothing in this module rewrites source text; it only reads
values out of it.

WHERE IT FAILS CLOSED. A field is None when the row does not state it
unambiguously - a second, different price on the row yields no price rather
than a guessed one, matching extractor.py's refusal to accept ambiguous DOM
price candidates. A missing field is a recorded measurement; an invented one
would be a lie the approval UI could not detect.

PRICE COMES FROM A NODE, EVERY OTHER FIELD FROM THE TEXT. This asymmetry is
deliberate and was measured (live listing DOM, op01/op13/eb01, 2026-09-02).
Code, rarity, name, image and stock are all unambiguous in the flattened row
text, so they still read from it. The price is not, in two distinct ways:

  * a SALE row shows the current price in `strong.d-block.text-end` and the
    FORMER price in a separate `<del>`. Flattened, that is just two numbers
    with no label, and no positional rule can tell them apart - 45 rows.
  * a card whose NAME begins with 円 (OP01-027 円卓) lets a price regex span
    the card code and read "027 円" as a price - 1 row.

Both vanish when the price is read from its own node: `<del>` is never
selected, and the card code lives in a `SPAN` this selector cannot match.
`select_listing_price` below therefore takes the node texts the scrape
collected and NEVER falls back to scanning `raw_listing_text` - a fallback
would quietly restore both bugs on exactly the rows they affect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from yuyutei_collector.discover import CARD_CODE_RE
from yuyutei_collector.discovery_probe import PRODUCT_PATH_RE

# "12,800 円" / "¥3,980". Yuyu-Tei always suffixes 円 on a listing row.
PRICE_RE = re.compile(r"([\d,]+)\s*円")

# The one node that carries a row's CURRENT sell price. Declared here, beside
# the parser that consumes what it selects, and applied by
# discovery_probe._scrape_listing's querySelectorAll - the two must stay in
# agreement, which is why the string is stated once and referenced in both
# directions by comment.
#
# THE CLASS LIST IS A SUBSET MATCH, NOT AN EXACT ONE. A sale row's node is
# `d-block text-end text-danger` and an ordinary row's is `d-block text-end`;
# adding `text-danger` here would silently stop pricing every non-sale row,
# which is the large majority. `<del>` (the struck former price) is a
# different tag and can never match.
PRICE_NODE_SELECTOR = "strong.d-block.text-end"

# The rarity token sits between the card code and the JP name: "OP13-118 P-SEC
# モンキー・D・ルフィ(パラレル)". Accepted only as a SHORT, fully upper-case
# ASCII token (SEC, P-SEC, P-SR, SR, UC, ...) so a Japanese name can never be
# read as a rarity. Anything else leaves detected_rarity None - rarity is
# descriptive metadata here, never identity, so refusing to guess costs
# nothing.
RARITY_TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")
RARITY_TOKEN_MAX_LEN = 8

# Same stock vocabulary the product-page extractor uses
# (extractor._find_stock_element), so a candidate's availability and an
# observation's stock_status can never mean different things.
STOCK_QUANTITY_RE = re.compile(r"(\d+)\s*点")
_STOCK_WINDOW = 16


@dataclass(frozen=True)
class ListingProduct:
    """One product as the listing page presented it."""

    series: str
    product_id: str
    source_url: str
    detected_card_code: str | None
    detected_rarity: str | None
    name_jp: str | None
    image_url: str | None
    price_jpy: int | None
    availability: str | None
    raw_listing_text: str
    # True when the block offered more than one CURRENT-price node, or when
    # the single one held two or more different numbers. price_jpy is then
    # None on purpose.
    #
    # A struck former price is deliberately NOT one of these cases any more:
    # it lives in a `<del>`, which `PRICE_NODE_SELECTOR` does not match, so a
    # sale row is now an ordinary priced row rather than an ambiguous one.
    price_ambiguous: bool = False


def parse_price(text: str) -> tuple[int | None, bool]:
    """(price, ambiguous). One distinct price -> that price. None -> (None,
    False). Two or more distinct prices -> (None, True): the row does not say
    which is current, and picking the first or the smallest would be a guess.

    Unchanged by the DOM-scoping change: it is still the numeric validator, and
    it is now handed ONE price node's text instead of a whole flattened row.
    Its ambiguity branch stays live and still matters - a single node holding
    two different numbers is refused here exactly as before."""
    values = {int(m.replace(",", "")) for m in PRICE_RE.findall(text)}
    values.discard(0)
    if len(values) == 1:
        return values.pop(), False
    return None, len(values) > 1


def select_listing_price(price_texts: list[str] | None) -> tuple[int | None, bool]:
    """(price, ambiguous) for one product block, from its price NODES.

    The block's current sell price lives in `PRICE_NODE_SELECTOR`; the scrape
    collects the text of every node matching it (see
    discovery_probe._scrape_listing), so the COUNT is evidence this function
    can act on:

      * exactly one  -> hand that node's text to `parse_price`, which applies
        the unchanged numeric validation and its own ambiguity check;
      * zero         -> the block states no current price. (None, False): an
        absence, not a disagreement;
      * two or more  -> the block offers several current-price nodes and does
        not say which governs. (None, True) - refused, never the first one.

    THERE IS NO FLATTENED-TEXT FALLBACK, and that is the point of the whole
    change rather than an oversight. Falling back to `raw_listing_text`
    whenever this returns None would re-admit precisely the rows the node
    scoping exists to fix: every sale row (whose flattened text carries the
    struck former price too) and 円卓 (whose flattened text lets a price regex
    span the card code). A row this function cannot price is left unpriced,
    and the operator sees a candidate with no price rather than a wrong one.
    """
    texts = [text for text in (price_texts or []) if text and text.strip()]
    if len(texts) != 1:
        return None, len(texts) > 1
    return parse_price(texts[0])


def parse_availability(text: str) -> str | None:
    """The stock state the row displays, or None if it shows no 在庫 field.

    Only the short window after 在庫 is inspected, so a × or ◯ elsewhere in the
    row (cart controls, promotional text) cannot be mistaken for stock."""
    index = text.find("在庫")
    if index == -1:
        return None
    window = text[index : index + _STOCK_WINDOW]
    if "在庫あり" in window:
        return "in_stock"
    if "在庫切れ" in window or "品切れ" in window:
        return "out_of_stock"
    if "×" in window:
        return "out_of_stock"
    if "○" in window or "◯" in window:
        return "in_stock"
    quantity = STOCK_QUANTITY_RE.search(window)
    if quantity:
        return "in_stock" if int(quantity.group(1)) > 0 else "out_of_stock"
    # The field is present but says something this vocabulary does not cover.
    # Recorded as such rather than collapsed into in/out of stock.
    return "unknown_present_marker"


def split_rarity_and_name(label: str, card_code: str | None) -> tuple[str | None, str | None]:
    """('P-SEC', 'モンキー・D・ルフィ(パラレル)') from the anchor label.

    The name is returned exactly as displayed, annotations included. When no
    rarity token is recognised the whole remainder becomes the name - losing a
    rarity is recoverable, losing the name is not."""
    tokens = label.split()
    if card_code and tokens and tokens[0] == card_code:
        tokens = tokens[1:]
    rarity = None
    if tokens and len(tokens[0]) <= RARITY_TOKEN_MAX_LEN and RARITY_TOKEN_RE.match(tokens[0]):
        rarity = tokens[0]
        tokens = tokens[1:]
    name = " ".join(tokens).strip()
    return rarity, name or None


def parse_listing_row(row: dict[str, Any]) -> ListingProduct | None:
    """One raw anchor (as discovery_probe._scrape_listing yields them) as a
    ListingProduct, or None when the anchor is not a product link."""
    match = PRODUCT_PATH_RE.search(urlparse(row.get("href") or "").path)
    if match is None:
        return None
    series, product_id = match.group(1), match.group(2)

    label = (row.get("text") or "").strip() or (row.get("img_alt") or "").strip()
    card_text = (row.get("card_text") or "").strip()
    # Code is read from the label first and the surrounding row second, using
    # the same grammar the rest of the collector uses (discover.CARD_CODE_RE),
    # so discovery and collection can never disagree on what a code looks like.
    code_match = CARD_CODE_RE.search(label) or CARD_CODE_RE.search(card_text)
    card_code = code_match.group(0) if code_match else None

    rarity, name_jp = split_rarity_and_name(label or card_text, card_code)
    # Price from the block's own price nodes - never from `card_text`, which
    # is kept verbatim below as `raw_listing_text` and is the audit trail, not
    # the price source. A row scraped without `price_texts` is treated as
    # "no price node found" and fails closed, rather than falling back.
    price_jpy, price_ambiguous = select_listing_price(row.get("price_texts"))

    image_src = (row.get("img_src") or "").strip()
    return ListingProduct(
        series=series,
        product_id=product_id,
        # Canonical form: query strings and fragments dropped, so the same
        # product reached by two different links is one product.
        source_url=f"https://yuyu-tei.jp/sell/opc/card/{series}/{product_id}",
        detected_card_code=card_code,
        detected_rarity=rarity,
        name_jp=name_jp,
        image_url=image_src or None,
        price_jpy=price_jpy,
        availability=parse_availability(card_text or label),
        raw_listing_text=card_text or label,
        price_ambiguous=price_ambiguous,
    )
