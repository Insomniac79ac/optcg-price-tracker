"""Parses the Japanese official ONE PIECE Card List into structured evidence.

WHY THIS EXISTS. Atlas already trusts Bandai's Card List as the authority for
card code, official name, official asset and product membership - but until
now it only ever read that authority one asset at a time, through addresses
recorded by hand into a manifest (see app.persist_official_display_evidence).
There was no way to ask the catalogue *what it contains*, which is exactly
what planning an import requires.

This module is the smallest helper that closes that gap, and nothing more. It
turns one already-fetched Card List page into records. It does not fetch, does
not touch the database, does not decide anything, and does not interpret:

  * it never infers `treatment` - the `_pN` suffix is an artwork address, not
    a classification, and the whole point of official_artwork_variant is that
    those two facts are separate (see app.services.official_artwork_variant);
  * it never normalizes a product name into an identity - the repo's own
    normalize_release_text collapses 30 distinct Bandai products into 13 keys,
    which is why ReleaseProduct is keyed on a surrogate id and a frozen
    `(catalogue, code)` pair instead (see app.models.release_product);
  * it never repairs a malformed entry. An entry that does not parse is
    returned with the fields it actually had, so the caller can refuse it.

WHAT THE PAGE GIVES US. Each card is one `<dl class="modalCol" id="...">`. The
`id` is Bandai's own **card list entry id** - `OP01-001` for the bare artwork,
`OP01-001_p2` for a further official artwork of the same card. That id is the
catalogue's own way of separating artworks that share a card code, rarity,
category and product, and it is the same identifier
app.services.official_display_evidence already records as `variant_id`.

Two properties of the suffix matter and are not this module's to smooth over:
the numbering spans products, and it is per catalogue - the JP and Asia-EN
catalogues serve byte-identical files under swapped suffixes. Everything here
is therefore scoped to the catalogue it was read from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin

# The catalogue this module reads. Named with the same vocabulary
# app.models.release_product.SOURCE_CATALOGUES uses, so a page and a product
# row can be compared without translating between two spellings.
SOURCE_CATALOGUE = "bandai_jp"

CARD_LIST_BASE_URL = "https://www.onepiece-cardgame.com/cardlist/"

# Bandai wraps a product's own code in full-width brackets at the end of its
# title: 'ブースターパック ROMANCE DAWN【OP-01】'. Products genuinely without a
# code exist and are numerous (223 name-only limited/promotional products in
# the 2026-08-21 sample), so a missing bracket is normal data, never an error.
PRODUCT_CODE_RE = re.compile(r"【([^】]+)】\s*$")

# Series titles carry a literal responsive line break inside the <option>
# text. It is presentation, not part of the name.
INLINE_BREAK_RE = re.compile(r"<br[^>]*>", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")

# HTML void elements never receive an end tag, so they must not move the tag
# depth the region tracking below relies on. `<img>` and `<br>` both appear
# inside every card entry, so getting this wrong silently un-nests the whole
# page - the `</dl>` that closes an entry stops matching its own `<dl>`.
VOID_TAGS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
)


def card_list_url(series_id: str) -> str:
    """The canonical JP Card List address for one series."""
    return f"{CARD_LIST_BASE_URL}?series={series_id}"


def product_code_from_display_name(display_name: str | None) -> str | None:
    """The official product code Bandai brackets at the end of a title.

    Returns None for an uncoded product, which is a legitimate and common
    state - never a placeholder, and never derived from the prose that
    remains.
    """
    if not display_name:
        return None
    match = PRODUCT_CODE_RE.search(display_name.strip())
    if not match:
        return None
    code = match.group(1).strip()
    return code or None


def _clean(text: str) -> str:
    """Collapse presentation whitespace without altering the wording."""
    return WHITESPACE_RE.sub(" ", INLINE_BREAK_RE.sub(" ", text)).strip()


@dataclass(frozen=True)
class OfficialSeries:
    """One product as the catalogue's own series picker names it."""

    series_id: str
    display_name: str
    official_code: str | None

    @property
    def source_url(self) -> str:
        return card_list_url(self.series_id)


@dataclass(frozen=True)
class OfficialCardEntry:
    """One card list entry - i.e. one official artwork of one card.

    `entry_id` is Bandai's identifier for this artwork, not a code we minted.
    `product_names` is what the entry's 入手情報 (obtain information) block
    lists verbatim; a card reprinted into several products names several.
    """

    entry_id: str
    card_code: str
    rarity: str
    category: str
    card_name: str
    image_url: str | None
    product_names: tuple[str, ...]

    @property
    def is_wellformed(self) -> bool:
        """Whether the entry carries the fields identity planning requires.

        Deliberately does not consider the image address: whether the asset
        names this card is official_artwork_variant's judgement to make, not
        this parser's.
        """
        return bool(self.entry_id and self.card_code and self.card_name)


@dataclass(frozen=True)
class OfficialCardListPage:
    """One parsed Card List series page."""

    series_id: str
    source_url: str
    source_catalogue: str
    series_index: tuple[OfficialSeries, ...]
    entries: tuple[OfficialCardEntry, ...]

    @property
    def series(self) -> OfficialSeries | None:
        """This page's own product, as named by the catalogue's series picker."""
        for candidate in self.series_index:
            if candidate.series_id == self.series_id:
                return candidate
        return None

    def entries_for_card(self, card_code: str) -> tuple[OfficialCardEntry, ...]:
        """Every official artwork this page publishes for one card code.

        The plural is the point: a card code with two entries is a card with
        two official artworks, which is precisely the case that must not be
        collapsed into one print.
        """
        wanted = (card_code or "").strip().upper()
        return tuple(e for e in self.entries if e.card_code.upper() == wanted)


class _CardListParser(HTMLParser):
    """Stateful reader for one Card List page.

    Written against the page's actual structure rather than a generic scrape:
    each card is a `<dl class="modalCol">`, and the fields live in known
    descendants of it. Anything outside a modalCol is ignored, which is what
    keeps the `<a class="modalOpen">` thumbnails that sit *between* entries
    from being read as the next entry's artwork.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.series: list[OfficialSeries] = []
        self.entries: list[OfficialCardEntry] = []

        self._option_value: str | None = None
        self._option_text: list[str] = []

        self._dl_depth = 0
        # Tracked separately from the id: a modalCol with a blank id is a
        # malformed entry the caller must be able to see and refuse, not one
        # to drop on the floor.
        self._in_entry = False
        self._entry_id: str = ""
        self._info_spans: list[str] = []
        self._card_name: list[str] = []
        self._get_info: list[str] = []
        self._image_url: str | None = None

        # Which capturing region we are inside, and at what tag depth it
        # started, so nested markup closes the right region.
        self._region: str | None = None
        self._region_depth = 0
        self._depth = 0
        self._in_front_col = False
        self._front_col_depth = 0
        self._in_span = False
        self._in_h3 = False

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _attr(attrs: list[tuple[str, str | None]], name: str) -> str | None:
        for key, value in attrs:
            if key == name:
                return value
        return None

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
        return set((_CardListParser._attr(attrs, "class") or "").split())

    def _reset_entry(self) -> None:
        self._in_entry = False
        self._entry_id = ""
        self._info_spans = []
        self._card_name = []
        self._get_info = []
        self._image_url = None
        self._region = None
        self._in_front_col = False
        self._in_span = False

    # -- HTMLParser hooks -------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in VOID_TAGS:
            self._depth += 1
        classes = self._classes(attrs)

        if tag == "option":
            self._option_value = self._attr(attrs, "value")
            self._option_text = []
            return

        if tag == "dl" and "modalCol" in classes:
            self._reset_entry()
            self._in_entry = True
            self._dl_depth = self._depth
            self._entry_id = (self._attr(attrs, "id") or "").strip()
            return

        if not self._in_entry:
            return

        if tag == "div":
            if "infoCol" in classes:
                self._region, self._region_depth = "info", self._depth
            elif "cardName" in classes:
                self._region, self._region_depth = "name", self._depth
            elif "getInfo" in classes:
                self._region, self._region_depth = "getinfo", self._depth
            elif "frontCol" in classes:
                self._in_front_col, self._front_col_depth = True, self._depth
            return

        if tag == "span" and self._region == "info":
            self._in_span = True
            self._info_spans.append("")
            return

        if tag == "h3":
            # The label inside getInfo ('入手情報') is chrome, not a product.
            self._in_h3 = True
            return

        if tag == "img" and self._in_front_col and self._image_url is None:
            # The lazy loader keeps the real address in data-src; src is a
            # shared placeholder gif.
            self._image_url = self._attr(attrs, "data-src") or self._attr(attrs, "src")
            return

        if tag == "br" and self._region == "getinfo":
            # One product per line inside 入手情報.
            self._get_info.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # An explicitly self-closing tag (<br/>) carries its own end, so it is
        # read for content but must not move the depth either way.
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return

        if tag == "option":
            self._finish_option()
            self._depth = max(0, self._depth - 1)
            return

        if tag == "span" and self._in_span:
            self._in_span = False

        if tag == "h3":
            self._in_h3 = False

        if self._region is not None and self._depth <= self._region_depth:
            self._region = None

        if self._in_front_col and self._depth <= self._front_col_depth:
            self._in_front_col = False

        if tag == "dl" and self._in_entry and self._depth <= self._dl_depth:
            self._finish_entry()

        self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if self._option_value is not None:
            self._option_text.append(data)
            return
        if not self._in_entry or self._in_h3:
            return
        if self._region == "info" and self._in_span and self._info_spans:
            self._info_spans[-1] += data
        elif self._region == "name":
            self._card_name.append(data)
        elif self._region == "getinfo":
            self._get_info.append(data)

    # -- record construction ---------------------------------------------
    def _finish_option(self) -> None:
        value = (self._option_value or "").strip()
        text = _clean("".join(self._option_text))
        self._option_value = None
        self._option_text = []
        # The picker's first entry is a prompt with no series value.
        if not value or not value.isdigit() or not text:
            return
        self.series.append(
            OfficialSeries(
                series_id=value,
                display_name=text,
                official_code=product_code_from_display_name(text),
            )
        )

    def _finish_entry(self) -> None:
        spans = [_clean(s) for s in self._info_spans]
        products = tuple(
            _clean(part) for part in "".join(self._get_info).split("\n") if _clean(part)
        )
        self.entries.append(
            OfficialCardEntry(
                entry_id=self._entry_id.strip(),
                card_code=spans[0] if len(spans) > 0 else "",
                rarity=spans[1] if len(spans) > 1 else "",
                category=spans[2] if len(spans) > 2 else "",
                card_name=_clean("".join(self._card_name)),
                image_url=(self._image_url or "").strip() or None,
                product_names=products,
            )
        )
        self._reset_entry()


def parse_card_list(
    html: str, series_id: str, *, base_url: str | None = None
) -> OfficialCardListPage:
    """Parse one already-fetched JP Card List series page.

    `base_url` resolves the page's relative asset addresses; it defaults to
    the canonical address for `series_id`, which is where the page came from.
    Query strings on those addresses are Bandai's cache buster and are kept
    verbatim - discarding them here would quietly change the evidence, and
    parse_official_artwork_variant already ignores them when reading identity.
    """
    parser = _CardListParser()
    parser.feed(html)
    parser.close()

    resolved_base = base_url or card_list_url(series_id)
    entries = tuple(
        OfficialCardEntry(
            entry_id=e.entry_id,
            card_code=e.card_code,
            rarity=e.rarity,
            category=e.category,
            card_name=e.card_name,
            image_url=urljoin(resolved_base, e.image_url) if e.image_url else None,
            product_names=e.product_names,
        )
        for e in parser.entries
    )
    return OfficialCardListPage(
        series_id=series_id,
        source_url=card_list_url(series_id),
        source_catalogue=SOURCE_CATALOGUE,
        series_index=tuple(parser.series),
        entries=entries,
    )
