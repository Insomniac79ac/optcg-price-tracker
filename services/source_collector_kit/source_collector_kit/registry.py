"""Parsers by version. A RAW row names its parser version, so a stored page can be re-parsed
(verify-lossless) by exactly the code that read it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ListingRow:
    """One product row as the list page shows it, verbatim where it is text."""

    source_product_key: str
    url: str
    title: str
    condition_label: str | None
    price_jpy: int | None
    stock: int | None
    sold_out: bool = False
    on_sale: bool = False


@dataclass(frozen=True)
class ParsedPage:
    rows: tuple[ListingRow, ...]
    group_key: str
    group_title: str | None = None
    header_total: int | None = None
    page_count: int | None = None
    failures: tuple[str, ...] = field(default_factory=tuple)


Parser = Callable[[str, str], ParsedPage]
_PARSERS: dict[str, Parser] = {}


class ParserUnavailable(RuntimeError):
    """No parser is registered for this version, so no run starts."""


def register(version: str) -> Callable[[Parser], Parser]:
    def decorate(parser: Parser) -> Parser:
        if version in _PARSERS and _PARSERS[version] is not parser:
            raise ValueError(f"parser {version} is already registered")
        _PARSERS[version] = parser
        return parser

    return decorate


def parser_for(version: str) -> Parser:
    try:
        return _PARSERS[version]
    except KeyError:
        raise ParserUnavailable(f"no parser registered for {version}") from None


def registered() -> tuple[str, ...]:
    return tuple(sorted(_PARSERS))
