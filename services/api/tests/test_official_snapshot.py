"""Coverage for the raw official-catalogue snapshot layer.

Hermetic. The HTML fixture is a real excerpt of the live OP-01 series page
(captured 2026-08-22, four entries kept verbatim); everything else is built in
the test. Nothing here reaches Bandai or a real database - the collector's
network layer is exercised through a stub fetcher.
"""

from pathlib import Path

import pytest

from app.services.official_cardlist import has_real_pagination, parse_card_list
from app.services.official_snapshot import (
    CLASS_INVARIANT,
    CLASS_MISSING,
    CLASS_VARIES,
    Snapshot,
    asset_url_parts,
    classify_field,
    normalize_for_comparison,
    occurrence_matrix,
    raw_suffix,
    suffix_family,
    suffix_family_analysis,
    suffix_index,
    suffix_inventory,
    variance_report,
)

FIXTURE = Path(__file__).parent / "fixtures" / "official_cardlist" / "series_550101_excerpt.html"
CARDLIST = "https://www.onepiece-cardgame.com/images/cardlist/card"


@pytest.fixture()
def page():
    return parse_card_list(FIXTURE.read_text(encoding="utf-8"), "550101")


# --- series discovery ----------------------------------------------------------


def test_series_discovery_reads_the_catalogues_own_picker(page):
    assert len(page.series_index) == 3
    assert page.series is not None
    assert page.series.official_code == "OP-01"
    assert {s.series_id for s in page.series_index} == {"550101", "550301", "550901"}
    # Uncoded groupings (the promotional/limited buckets) are legitimate
    # catalogue members and must survive discovery rather than being dropped.
    assert any(s.official_code is None for s in page.series_index)
    # The empty prompt option is not a series.
    assert all(s.series_id.isdigit() for s in page.series_index)


def test_no_server_side_pagination_is_claimed_without_a_real_href():
    assert has_real_pagination(FIXTURE.read_text(encoding="utf-8")) is False
    assert has_real_pagination('<a class="nextBtn" href="?series=1&page=2">NEXT</a>') is True
    assert has_real_pagination('<a class="nextBtn" href="javascript:void(0);">NEXT</a>') is False


# --- raw field preservation -----------------------------------------------------


def test_every_published_block_is_captured_verbatim(page):
    base = next(e for e in page.entries if e.entry_id == "OP01-001")
    names = {f.name for f in base.fields}
    assert {"cost", "attribute", "power", "counter", "color", "block", "feature", "text"} <= names
    # A Leader's cost block is headed ライフ, not コスト. Normalising that away
    # would destroy the distinction between a life total and a play cost.
    assert base.field("cost").label == "ライフ"
    assert base.field("cost").value == "5"
    assert base.field("attribute").image_alt == "斬"
    assert base.field("counter").value == "-"  # published '-', not absent


def test_raw_rarity_and_text_are_never_rewritten(page):
    base = next(e for e in page.entries if e.entry_id == "OP01-001")
    assert base.rarity == "L"
    assert base.category == "LEADER"
    assert base.card_name == "ロロノア・ゾロ"
    assert "【ドン‼×1】" in base.field("text").value


def test_a_trigger_block_is_kept_when_present_and_absent_when_not(page):
    trigger = next(e for e in page.entries if e.entry_id == "OP01-009")
    assert trigger.field("trigger") is not None
    assert "【トリガー】" in trigger.field("trigger").value
    base = next(e for e in page.entries if e.entry_id == "OP01-001")
    assert base.field("trigger") is None


def test_the_remarks_block_is_not_mistaken_for_product_membership(page):
    """Bandai reuses the getInfo class for a 備考 note.

    OP01-010 carries an illustrator-misprint remark in a second getInfo block.
    Keying product membership on the class would read that remark as a
    product; it is keyed on the 入手情報 heading instead.
    """
    entry = next(e for e in page.entries if e.entry_id == "OP01-010")
    blocks = [f for f in entry.fields if f.name == "getInfo"]
    assert len(blocks) == 2
    assert {b.label for b in blocks} == {"入手情報", "備考"}
    assert entry.product_names == ("ROMANCE DAWN【OP-01】",)


def test_each_entry_carries_the_digest_of_its_own_source(page):
    digests = [e.fragment_sha256 for e in page.entries]
    assert all(d and len(d) == 64 for d in digests)
    # Two different entries are two different fragments.
    assert len(set(digests)) == len(digests)


# --- suffixes -------------------------------------------------------------------


def test_base_pn_and_rn_are_read_from_the_basename():
    assert raw_suffix("OP01-001.png", "OP01-001") == ""
    assert raw_suffix("OP01-001_p2.png", "OP01-001") == "_p2"
    assert raw_suffix("OP01-001_r1.png", "OP01-001") == "_r1"
    # An asset naming another card is unreadable evidence, not a suffix.
    assert raw_suffix("OP01-002.png", "OP01-001") is None


def test_an_unexpected_suffix_family_is_preserved_not_discarded():
    """This tranche discovers the vocabulary; it does not police it."""
    assert suffix_family("_x9") == "x"
    assert suffix_index("_x9") == 9
    assert suffix_family("_zz3") == "zz"
    # Only genuinely unreadable shapes fall through.
    assert suffix_family("_pA") == "unparseable"
    assert suffix_family(None) == "unparseable"


def test_suffix_inventory_counts_every_pattern_observed():
    rows = [
        {"card_code": "A-1", "entry_id": "A-1", "image_url": f"{CARDLIST}/A-1.png"},
        {"card_code": "A-1", "entry_id": "A-1_p1", "image_url": f"{CARDLIST}/A-1_p1.png"},
        {"card_code": "A-1", "entry_id": "A-1_r1", "image_url": f"{CARDLIST}/A-1_r1.png"},
        {"card_code": "A-1", "entry_id": "A-1_q7", "image_url": f"{CARDLIST}/A-1_q7.png"},
        {"card_code": "A-1", "entry_id": "bad", "image_url": f"{CARDLIST}/OTHER.png"},
    ]
    inventory = suffix_inventory(rows)
    assert inventory["families"] == {"base": 1, "p": 1, "r": 1, "q": 1, "unparseable": 1}
    assert inventory["exact_suffixes"]["_q7"] == 1
    assert inventory["unparseable_examples"][0]["basename"] == "OTHER.png"


# --- asset identity ---------------------------------------------------------------


def test_the_cache_buster_is_recorded_apart_from_identity():
    parts = asset_url_parts(f"{CARDLIST}/OP01-001.png?260821")
    assert parts["basename"] == "OP01-001.png"
    assert parts["query_string"] == "260821"
    assert parts["url_path"].endswith("/OP01-001.png")
    # Two cache busters, one asset name.
    other = asset_url_parts(f"{CARDLIST}/OP01-001.png?999999")
    assert other["basename"] == parts["basename"]
    assert other["query_string"] != parts["query_string"]


def test_identical_bytes_at_two_urls_are_stored_once(tmp_path):
    snapshot = Snapshot(tmp_path)
    payload = b"\x89PNG\r\n\x1a\n identical bytes"
    first_digest, first_path = snapshot.write_image(payload)
    second_digest, second_path = snapshot.write_image(payload)
    assert first_digest == second_digest
    assert first_path == second_path
    stored = list((tmp_path / "images").rglob("*.png"))
    assert len(stored) == 1


def test_images_are_addressed_by_content_not_by_url(tmp_path):
    snapshot = Snapshot(tmp_path)
    digest, path = snapshot.write_image(b"some bytes")
    assert digest in path.name
    assert path.parent.name == digest[:2]
    assert snapshot.has_image(digest)


# --- snapshot io and resume ---------------------------------------------------------


def test_pages_round_trip_through_the_snapshot(tmp_path):
    snapshot = Snapshot(tmp_path)
    html = FIXTURE.read_text(encoding="utf-8")
    assert snapshot.has_page("550101") is False
    snapshot.write_page("550101", html)
    assert snapshot.has_page("550101") is True
    assert snapshot.read_page("550101") == html
    # Stored compressed, so the corpus stays small.
    assert snapshot.page_path("550101").stat().st_size < len(html.encode())


def test_resume_reuses_what_is_already_stored(tmp_path):
    """A resumed run must not re-fetch a page or asset it already holds."""
    from app import collect_official_cardlist_snapshot as cli

    snapshot = Snapshot(tmp_path)
    snapshot.write_page("550101", FIXTURE.read_text(encoding="utf-8"))

    class _Fetcher:
        requests = 0
        retried = 0

        def get(self, url):
            _Fetcher.requests += 1
            raise AssertionError(f"resume re-fetched {url}")

    series = parse_card_list(FIXTURE.read_text(encoding="utf-8"), "550101").series_index
    result = cli.collect_pages(
        snapshot, [s for s in series if s.series_id == "550101"], _Fetcher(),
        resume=True, workers=1,
    )
    assert result["entries"] == 4
    assert _Fetcher.requests == 0


def test_resume_keeps_previously_recorded_assets(tmp_path):
    from app import collect_official_cardlist_snapshot as cli

    snapshot = Snapshot(tmp_path)
    url = f"{CARDLIST}/OP01-001.png?260821"
    snapshot.save("entries.jsonl", [{"image_url": url, "card_code": "OP01-001"}])
    snapshot.save("assets.jsonl", [{"url": url, "sha256": "a" * 64, "basename": "OP01-001.png"}])

    class _Fetcher:
        def get(self, url):
            raise AssertionError("resume re-fetched an asset it already had")

    result = cli.collect_images(snapshot, _Fetcher(), resume=True, workers=1)
    assert result["asset_urls"] == 1
    assert result["distinct_digests"] == 1


# --- variance -----------------------------------------------------------------------


def test_classify_field_separates_invariant_varying_and_inconsistent():
    assert classify_field(["SR", "SR", "SR"]).classification == CLASS_INVARIANT
    assert classify_field(["SR", "SPカード"]).classification == CLASS_VARIES
    # Present for one printing and absent for another is its own finding.
    assert classify_field(["SR", None]).classification == CLASS_MISSING
    assert classify_field([None, None]).classification == CLASS_MISSING


def test_formatting_only_differences_are_distinguished_from_material_ones():
    """Full-width vs ASCII is presentation; SR vs SP is substance."""
    formatting = classify_field(["５０００", "5000"])
    assert formatting.classification == CLASS_VARIES
    assert formatting.formatting_only is True
    material = classify_field(["5000", "6000"])
    assert material.formatting_only is False
    # Raw values survive either way.
    assert formatting.raw_values == ["5000", "５０００"]


def test_normalize_is_only_used_for_comparison():
    assert normalize_for_comparison("５０００") == "5000"
    assert normalize_for_comparison("a  b") == "a b"
    assert normalize_for_comparison(None) is None


def _row(code, entry_id, series, product, url, **fields):
    blocks = [{"name": k, "label": k, "value": v, "image_alt": None, "image_src": None}
              for k, v in fields.items() if k not in ("rarity", "category", "card_name")]
    return {
        "card_code": code, "entry_id": entry_id, "source_series_id": series,
        "product_code": product, "product_title": product, "product_names": [product or ""],
        "image_url": url, "fields": blocks,
        "rarity": fields.get("rarity", "SR"),
        "category": fields.get("category", "CHARACTER"),
        "card_name": fields.get("card_name", "name"),
    }


def test_the_occurrence_matrix_groups_by_card_code_across_products():
    rows = [
        _row("OP02-013", "OP02-013", "550102", "OP-02", f"{CARDLIST}/OP02-013.png", power="5000"),
        _row("OP02-013", "OP02-013_p3", "550108", "OP-08",
             f"{CARDLIST}/OP02-013_p3.png", rarity="SPカード", power="5000"),
    ]
    matrix = occurrence_matrix(rows, {})
    assert len(matrix) == 1
    card = matrix[0]
    assert card["occurrence_count"] == 2
    assert card["distinct_products"] == 2
    assert card["variance"]["rarity"]["classification"] == CLASS_VARIES
    assert card["variance"]["rarity"]["raw_values"] == ["SPカード", "SR"]
    assert card["variance"]["power"]["classification"] == CLASS_INVARIANT
    assert card["occurrences"][1]["raw_suffix"] == "_p3"


def test_variance_report_counts_and_examples_are_correct():
    rows = [
        _row("A-1", "A-1", "1", "P1", f"{CARDLIST}/A-1.png", power="1000"),
        _row("A-1", "A-1_p1", "2", "P2", f"{CARDLIST}/A-1_p1.png", power="2000"),
        _row("B-1", "B-1", "1", "P1", f"{CARDLIST}/B-1.png", power="3000"),
    ]
    report = variance_report(occurrence_matrix(rows, {}))
    assert report["card_codes_total"] == 2
    assert report["card_codes_with_multiple_occurrences"] == 1
    assert report["card_codes_spanning_multiple_products"] == 1
    assert report["fields"]["power"]["card_codes_varying"] == 1
    assert report["fields"]["power"]["materially_different"] == 1
    assert report["fields"]["power"]["examples"][0]["card_code"] == "A-1"


def test_suffix_family_analysis_reports_mixed_families_and_reuse():
    rows = [
        _row("A-1", "A-1", "1", "P1", f"{CARDLIST}/A-1.png"),
        _row("A-1", "A-1_p1", "1", "P1", f"{CARDLIST}/A-1_p1.png"),
        _row("A-1", "A-1_r1", "2", "P2", f"{CARDLIST}/A-1_r1.png"),
        _row("B-1", "B-1_p1", "1", "P1", f"{CARDLIST}/B-1_p1.png"),
        _row("B-1", "B-1_p1", "2", "P2", f"{CARDLIST}/B-1_p1.png"),
    ]
    analysis = suffix_family_analysis(occurrence_matrix(rows, {}))
    assert "A-1" in analysis["cards_with_more_than_one_letter_family"]
    assert analysis["index_counts_per_family"]["p"] == {1: 3}
    assert analysis["index_counts_per_family"]["r"] == {1: 1}
    assert analysis["same_suffix_across_multiple_products_count"] == 1


# --- no canonical writes -------------------------------------------------------------


def test_the_snapshot_layer_writes_no_canonical_row():
    """Structural: the evidence layer cannot touch a canonical table."""
    import app.services.official_snapshot as module

    source = Path(module.__file__).read_text()
    code = "\n".join(l for l in source.splitlines() if not l.strip().startswith("#"))
    for forbidden in ("session.add", "session.commit", "CanonicalCard(", "CardPrint(",
                      "ReleaseProduct(", "SourceCardMapping("):
        assert forbidden not in code, forbidden


def test_the_collector_cli_has_no_canonical_write_flag():
    from app import collect_official_cardlist_snapshot as cli

    options = {o for a in cli.build_parser()._actions for o in a.option_strings}
    for forbidden in ("--apply", "--write", "--persist", "--import", "--commit", "--force"):
        assert forbidden not in options, forbidden
    assert "--pages-only" in options and "--analyze" in options


def test_the_collector_never_constructs_a_canonical_row():
    from app import collect_official_cardlist_snapshot as cli

    source = Path(cli.__file__).read_text()
    code = "\n".join(l for l in source.splitlines() if not l.strip().startswith("#"))
    for forbidden in ("session.add", "session.commit", "CanonicalCard(", "CardPrint(",
                      "ReleaseProduct(", "SourceCardMapping("):
        assert forbidden not in code, forbidden


def test_a_refusal_status_stops_collection_rather_than_escalating():
    """403/429 must end the run, not trigger a workaround."""
    import urllib.error

    from app.collect_official_cardlist_snapshot import CollectionStopped, RateLimitedFetcher

    fetcher = RateLimitedFetcher(min_interval=0)

    def _raise(*a, **k):
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)

    import urllib.request

    original = urllib.request.urlopen
    urllib.request.urlopen = _raise
    try:
        with pytest.raises(CollectionStopped, match="429"):
            fetcher.get("https://example.test/x")
    finally:
        urllib.request.urlopen = original


# --- the recorded corpus baseline ---------------------------------------------------

BASELINE = (
    Path(__file__).parent
    / "fixtures"
    / "official_cardlist"
    / "corpus_baseline_2026-08-22.json"
)
LIVE_SNAPSHOT = Path(__file__).parents[3] / "data/official_snapshots/bandai_jp/current"


@pytest.fixture()
def baseline():
    import json

    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_the_recorded_corpus_shape(baseline):
    """The complete JP catalogue as measured on 2026-08-22.

    A dated baseline, not a contract: Bandai publishes new products, so this
    exists to be diffed against on the next capture, and a change here should
    be a deliberate re-record rather than a surprise.
    """
    assert baseline["series_total"] == 62
    assert baseline["series_coded"] == 59
    assert baseline["series_uncoded"] == 3
    assert baseline["entry_occurrences"] == 4962
    assert baseline["distinct_card_codes"] == 2823
    assert baseline["distinct_image_urls"] == 4962
    # Fewer digests than URLs: identical bytes served at several addresses.
    assert baseline["distinct_image_digests"] == 4810


def test_only_base_p_and_r_families_exist_in_the_corpus(baseline):
    assert set(baseline["suffix_families"]) == {"base", "p", "r"}
    assert sum(baseline["suffix_families"].values()) == baseline["entry_occurrences"]
    assert baseline["unparseable_assets"] == 0


def test_the_observed_suffix_indices_are_p1_to_p10_and_r1_to_r3(baseline):
    p_indices = sorted(int(i) for i in baseline["suffix_indices"]["p"])
    r_indices = sorted(int(i) for i in baseline["suffix_indices"]["r"])
    assert p_indices == list(range(1, 11))
    assert r_indices == [1, 2, 3]
    # p10 is real: a single-digit assumption about the suffix would break.
    assert baseline["suffix_indices"]["p"]["10"] == 1


def test_the_approved_identity_parser_cannot_yet_read_the_r_family(baseline):
    """461 occurrences (9.3%) are unresolvable, and all of them are _rN.

    Recorded here so the size of the gap is visible. The parser is
    deliberately NOT changed in this tranche - the vocabulary is discovered
    first, and widening an identity rule is its own decision.
    """
    assert baseline["occurrences_unresolvable_by_approved_variant_parser"] == 461
    assert baseline["unresolvable_are_all_r_family"] is True
    assert baseline["suffix_families"]["r"] == 461


def test_the_raw_suffix_survives_what_the_identity_parser_refuses():
    """The two layers disagree on purpose, and the raw layer keeps the evidence.

    parse_official_artwork_variant is the *identity* rule and returns None for
    an _rN address it has no vocabulary for. The raw evidence layer must still
    record exactly what Bandai published, or the information needed to decide
    that rule would be lost the moment it was collected.
    """
    from app.services.official_artwork_variant import parse_official_artwork_variant

    url = f"{CARDLIST}/OP01-024_r1.png?260821"
    assert parse_official_artwork_variant(url, "OP01-024") is None
    assert raw_suffix("OP01-024_r1.png", "OP01-024") == "_r1"
    assert suffix_family("_r1") == "r"
    assert suffix_index("_r1") == 1


@pytest.mark.skipif(not LIVE_SNAPSHOT.exists(), reason="no local snapshot to compare")
def test_the_local_snapshot_still_matches_the_recorded_baseline(baseline):
    """Runs only where a snapshot has been collected; skipped in CI."""
    snapshot = Snapshot(LIVE_SNAPSHOT)
    entries = snapshot.load("entries.jsonl")
    assert len(entries) == baseline["entry_occurrences"]
    assert len({e["card_code"] for e in entries}) == baseline["distinct_card_codes"]
    assert suffix_inventory(entries)["families"] == baseline["suffix_families"]
