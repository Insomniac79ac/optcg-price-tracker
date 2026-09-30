"""One captured product, independent raw/PSA10 outcomes; no source requests."""

from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from snkrdunk_collector.extractor import extract_product

HTML = (Path(__file__).parent / "fixtures/product_page_reduced.html").read_text()


def parse(html):
    return extract_product(
        html, "https://snkrdunk.com/apparels/104428", "OP01-001", "parallel"
    )["extracted"]


def alter(label, content):
    soup = BeautifulSoup(HTML, "html.parser")
    variant = next(p for p in soup.find_all("p") if p.get_text(strip=True) == label)
    chip = variant.parent
    if content is None:
        chip.decompose()
    else:
        chip.clear()
        chip.append(
            BeautifulSoup(f'<p class="c__variant">{label}</p>{content}', "html.parser")
        )
    return str(soup)


def test_mixed_grades_exact_psa10_and_raw_floor_share_extraction():
    values = parse(HTML)
    assert values["raw_floor_jpy"] == 24500
    assert values["raw_floor_condition"] == "B"
    assert values["psa10"] == {"outcome": "captured", "price_jpy": 50000}


@pytest.mark.parametrize(
    "content,outcome",
    [
        (None, "absent"),
        ('<p class="c__awaiting">出品待ち</p>', "no_listing"),
        ('<p class="c__price">要確認</p>', "parsing_failure"),
        ('<p class="c__price">¥0</p>', "parsing_failure"),
        ('<p class="c__price">¥5,000〜¥8,000</p>', "parsing_failure"),
        (
            '<p class="c__price">¥5,000</p><p class="c__awaiting">出品待ち</p>',
            "parsing_failure",
        ),
    ],
)
def test_psa10_unavailable_never_suppresses_raw(content, outcome):
    values = parse(alter("PSA10", content))
    assert values["raw_floor_jpy"] == 24500
    assert values["psa10"] == {"outcome": outcome, "price_jpy": None}


def test_psa10_available_without_raw():
    soup = BeautifulSoup(HTML, "html.parser")
    for label in {"A", "B"}:
        chip = next(
            p for p in soup.find_all("p") if p.get_text(strip=True) == label
        ).parent
        chip.find("p", class_="css3__price").replace_with(
            BeautifulSoup('<p class="css3__awaiting">出品待ち</p>', "html.parser")
        )
    values = parse(str(soup))
    assert values["raw_floor_jpy"] is None
    assert values["psa10"]["price_jpy"] == 50000


def test_duplicate_psa10_is_ambiguous():
    soup = BeautifulSoup(HTML, "html.parser")
    chip = next(
        p for p in soup.find_all("p") if p.get_text(strip=True) == "PSA10"
    ).parent
    chip.parent.append(BeautifulSoup(str(chip), "html.parser"))
    assert parse(str(soup))["psa10"]["outcome"] == "parsing_failure"
