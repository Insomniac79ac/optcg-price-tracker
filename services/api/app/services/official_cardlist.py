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
    a classification, and the whole point of official_asset_variant is that
    those two facts are separate (see app.services.official_asset_variant);
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

import hashlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

# The catalogue this module reads. Named with the same vocabulary
# app.models.release_product.SOURCE_CATALOGUES uses, so a page and a product
# row can be compared without translating between two spellings.
SOURCE_CATALOGUE = "bandai_jp"

CARD_LIST_BASE_URL = "https://www.onepiece-cardgame.com/cardlist/"

# The field blocks Bandai publishes inside an entry's `<dd>`, named by its own
# div class. Captured verbatim and keyed by that class rather than translated
# into Atlas words: the raw layer's job is to preserve what was published, and
# a card whose `cost` block is labelled ライフ (a Leader's life) rather than
# コスト is exactly the kind of distinction a normalising reader would destroy.
FIELD_CLASSES = (
    "cost", "attribute", "power", "counter", "color",
    "block", "feature", "text", "trigger", "getInfo",
)

# The `getInfo` class is NOT reliably the obtain-information block: Bandai
# reuses it for a 備考 (remarks) note as well - OP01-010 carries one about an
# illustrator misprint. Only the heading distinguishes them, so product
# membership is keyed on this label and never on the class alone.
OBTAIN_INFO_LABEL = "入手情報"

# One card entry in the source document, from its opening tag to its close.
ENTRY_OPEN_RE = re.compile(r'<dl class="modalCol"', re.IGNORECASE)
ENTRY_CLOSE = "</dl>"

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


def _clean_multiline(text: str) -> str:
    """Collapse whitespace per line, keeping the line breaks themselves.

    A `<br>` inside 入手情報 separates two products, so flattening it would
    merge two distinct facts into one string.
    """
    lines = [WHITESPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


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
class RawField:
    """One published field block, exactly as the page carries it.

    `name` is Bandai's own div class, `label` its own heading (ライフ / コスト /
    パワー ...), and `value` the text as written - '-' included, because '-' is
    what Bandai publishes for "no counter" and is not the same evidence as an
    absent block. `image_alt`/`image_src` carry the attribute icon, which is a
    picture rather than text in the source.
    """

    name: str
    label: str
    value: str
    image_alt: str | None = None
    image_src: str | None = None


def iter_entry_fragments(html: str) -> list[str]:
    """Every `<dl class="modalCol">...</dl>` substring, in document order.

    Used to hash each entry's own source. modalCol elements do not nest, so
    the first `</dl>` after an opening tag closes it - verified against the
    live catalogue, where the fragment count always equals the parsed entry
    count (the parser asserts exactly that before attaching any hash).
    """
    fragments: list[str] = []
    for match in ENTRY_OPEN_RE.finditer(html):
        end = html.find(ENTRY_CLOSE, match.start())
        if end == -1:
            fragments.append(html[match.start():])
            continue
        fragments.append(html[match.start(): end + len(ENTRY_CLOSE)])
    return fragments


def has_real_pagination(html: str) -> bool:
    """Whether the page carries server-side pagination we would be missing.

    The Card List renders a `pagerCol` containing PREV/NEXT, but they are
    `javascript:void(0)` controls that step through the card *modals* and the
    `pager` div itself is empty - one series page holds every card in that
    series. This exists so that stops being an assumption: if Bandai ever
    gives those controls a real href, the crawler says so instead of silently
    collecting the first page only.
    """
    for match in re.finditer(r'<a[^>]*class="[^"]*(?:prevBtn|nextBtn)[^"]*"[^>]*>', html, re.I):
        href = re.search(r'href="([^"]*)"', match.group(0))
        if href and href.group(1).strip().lower() not in ("", "#", "javascript:void(0);", "javascript:void(0)"):
            return True
    return False


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
    # Everything else the page publishes, verbatim. Defaulted so the 4B-1
    # planner and its tests construct entries exactly as before.
    fields: tuple[RawField, ...] = ()
    fragment_sha256: str | None = None

    def field(self, name: str) -> RawField | None:
        for candidate in self.fields:
            if candidate.name == name:
                return candidate
        return None

    @property
    def is_wellformed(self) -> bool:
        """Whether the entry carries the fields identity planning requires.

        Deliberately does not consider the image address: whether the asset
        names this card is official_asset_variant's judgement to make, not
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
        self._image_url: str | None = None
        # Verbatim field blocks, keyed by Bandai's own div class.
        self._fields: list[RawField] = []
        self._field_name: str | None = None
        self._field_depth = 0
        self._field_label: list[str] = []
        self._field_value: list[str] = []
        self._field_img: tuple[str | None, str | None] = (None, None)

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

    def _close_field(self) -> None:
        if self._field_name is None:
            return
        self._fields.append(
            RawField(
                name=self._field_name,
                label=_clean("".join(self._field_label)),
                value=_clean_multiline("".join(self._field_value)),
                image_alt=self._field_img[0],
                image_src=self._field_img[1],
            )
        )
        self._field_name = None
        self._field_label = []
        self._field_value = []
        self._field_img = (None, None)

    def _reset_entry(self) -> None:
        self._in_entry = False
        self._entry_id = ""
        self._fields = []
        self._field_name = None
        self._field_label = []
        self._field_value = []
        self._field_img = (None, None)
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
            elif "frontCol" in classes:
                self._in_front_col, self._front_col_depth = True, self._depth
            named = classes.intersection(FIELD_CLASSES)
            if named:
                self._close_field()
                self._field_name = sorted(named)[0]
                self._field_depth = self._depth
                if self._field_name == "getInfo":
                    self._region, self._region_depth = "getinfo", self._depth
            return

        if tag == "span" and self._region == "info":
            self._in_span = True
            self._info_spans.append("")
            return

        if tag == "h3":
            # The label inside getInfo ('入手情報') is chrome, not a product.
            self._in_h3 = True
            return

        if tag == "img" and self._field_name is not None and not self._in_front_col:
            # The attribute block carries its value as an icon, not as text.
            self._field_img = (self._attr(attrs, "alt"), self._attr(attrs, "src"))
            return

        if tag == "img" and self._in_front_col and self._image_url is None:
            # The lazy loader keeps the real address in data-src; src is a
            # shared placeholder gif.
            self._image_url = self._attr(attrs, "data-src") or self._attr(attrs, "src")
            return

        if tag == "br" and self._field_name is not None:
            # A line break is structure, not wording: kept as a newline so a
            # multi-product 入手情報 block stays separable.
            (self._field_label if self._in_h3 else self._field_value).append("\n")

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

        if self._field_name is not None and self._depth <= self._field_depth:
            self._close_field()

        if tag == "dl" and self._in_entry and self._depth <= self._dl_depth:
            self._finish_entry()

        self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if self._option_value is not None:
            self._option_text.append(data)
            return
        if not self._in_entry:
            return
        if self._field_name is not None:
            (self._field_label if self._in_h3 else self._field_value).append(data)
            return
        if self._in_h3:
            return
        if self._region == "info" and self._in_span and self._info_spans:
            self._info_spans[-1] += data
        elif self._region == "name":
            self._card_name.append(data)

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
        self._close_field()
        spans = [_clean(s) for s in self._info_spans]
        fields = tuple(self._fields)
        obtain = next(
            (f for f in fields if f.name == "getInfo" and f.label == OBTAIN_INFO_LABEL), None
        )
        products = tuple(obtain.value.split("\n")) if obtain and obtain.value else ()
        self.entries.append(
            OfficialCardEntry(
                entry_id=self._entry_id.strip(),
                card_code=spans[0] if len(spans) > 0 else "",
                rarity=spans[1] if len(spans) > 1 else "",
                category=spans[2] if len(spans) > 2 else "",
                card_name=_clean("".join(self._card_name)),
                image_url=(self._image_url or "").strip() or None,
                product_names=products,
                fields=fields,
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
    parse_official_asset_variant already ignores them when reading identity.
    """
    parser = _CardListParser()
    parser.feed(html)
    parser.close()

    # Each entry's own source, hashed. Only attached when the fragment count
    # matches the parsed count - a mismatch means the scan and the parser
    # disagree about what an entry is, and a hash of the wrong fragment would
    # be worse than none.
    fragments = iter_entry_fragments(html)
    aligned = len(fragments) == len(parser.entries)
    digests = (
        [hashlib.sha256(f.encode("utf-8")).hexdigest() for f in fragments]
        if aligned
        else [None] * len(parser.entries)
    )

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
            fields=e.fields,
            fragment_sha256=digest,
        )
        for e, digest in zip(parser.entries, digests)
    )
    return OfficialCardListPage(
        series_id=series_id,
        source_url=card_list_url(series_id),
        source_catalogue=SOURCE_CATALOGUE,
        series_index=tuple(parser.series),
        entries=entries,
    )
