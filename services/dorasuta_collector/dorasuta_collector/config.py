"""Dorasuta asks: what one run fetches (plan §3.1, N5), MEASURED structure from SV §2.1.

Light mode: page 1 of every series daily (rows are grouped by rarity heading, SEC/SP/parallel
first) plus the remaining pages on a 6-day sweep, so every row is at most 7 days old. About 105
requests a day (ESTIMATE). The budget row is 200 per 86,400 s.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

SOURCE = "dorasuta"
HOSTS = frozenset({"dorasuta.jp"})
BASE_URL = "https://dorasuta.jp"
ROBOTS_URL = BASE_URL + "/robots.txt"
GAME_PATH = "/onepiece-cardgame"
SERIES_LIST_URL = BASE_URL + GAME_PATH + "/series-list"
PARSER_VERSION = "dorasuta-list-v1"
ROWS_PER_PAGE = 40
SWEEP_DAYS = 6
MAX_REQUESTS_PER_RUN = 150

SERIES_ENV = "DORASUTA_SERIES"  # comma list of sid[:page_count], set per rollout step (D1, D2)


def list_page_url(sid: int, page: int = 1) -> str:
    """`product-list?sid=N`, with the site's GET pager parameters after page 1 (SV §2.1)."""
    query = [("sid", str(sid))]
    if page > 1:
        query += [
            ("form110200_mode", "search"),
            ("form110200_params[0]", "pager"),
            ("form110200_params[1]", str(page)),
        ]
    return f"{BASE_URL}{GAME_PATH}/product-list?{urlencode(query)}"


@dataclass(frozen=True)
class Series:
    sid: int
    page_count: int = 1


def parse_series(value: str | None) -> tuple[Series, ...]:
    """`7202:7,7210` -> Series(7202, 7), Series(7210, 1). Refuses anything else."""
    out: list[Series] = []
    for item in (value or "").split(","):
        item = item.strip()
        if not item:
            continue
        sid, _, pages = item.partition(":")
        if not sid.isdigit() or (pages and not pages.isdigit()) or (pages and int(pages) < 1):
            raise ValueError(f"{SERIES_ENV} item {item!r} is not sid or sid:pages")
        out.append(Series(int(sid), int(pages) if pages else 1))
    if len({s.sid for s in out}) != len(out):
        raise ValueError(f"{SERIES_ENV} repeats a series")
    return tuple(out)


def plan_pages(series: tuple[Series, ...], day_number: int) -> list[str]:
    """Page 1 of every series, then this day's share of every later page.

    Page p (p >= 2) of a series is due when (p - 2 + sid) % SWEEP_DAYS == day_number % SWEEP_DAYS,
    so each later page is fetched once per 6 days and the load is spread across series.
    """
    pages = [list_page_url(s.sid) for s in series]
    for s in series:
        for page in range(2, s.page_count + 1):
            if (page - 2 + s.sid) % SWEEP_DAYS == day_number % SWEEP_DAYS:
                pages.append(list_page_url(s.sid, page))
    if len(pages) + 1 > MAX_REQUESTS_PER_RUN:
        raise ValueError(f"{len(pages)} pages exceed the per-run cap of {MAX_REQUESTS_PER_RUN - 1}")
    return pages
