"""Mock-only controls for the release evidence audit; never fetch Bandai."""

import gzip
import hashlib
import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "release_evidence", Path(__file__).resolve().parents[1] / "verify_bandai_release_evidence.py"
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

IDENTITY = {"official_code": "OP-17", "display_name": "ブースターパック 世界最強の戦士【OP-17】"}
URL = "https://www.onepiece-cardgame.com/products/boosters/op17/"


def detail(fields, name=IDENTITY["display_name"]):
    return f'<div class="detailColStatus"><h4>{name}</h4>{fields}</div>'.encode()


def test_uses_release_label_inside_exact_product_not_news_or_application_date():
    raw = b'<time datetime="2026-08-01">2026.08.01</time>' + detail(
        '<dl><dt>応募受付期間</dt><dd>2026.08.07 - 2026.08.18</dd></dl>'
        '<dl><dt>発売日</dt><dd>2026.08.22(土)</dd></dl>'
        '<dl><dt>再販日</dt><dd>2026.09.01</dd></dl>'
    )
    observations = audit.extract_detail(raw, IDENTITY)
    assert [o["dates"] for o in observations] == [["2026-08-22"]]


def test_no_release_label_is_not_an_accepted_date():
    with pytest.raises(ValueError, match="No explicit release date"):
        audit.extract_detail(detail('<dt>予約開始日</dt><dd>2026.08.22</dd>'), IDENTITY)


def test_name_and_code_both_required():
    with pytest.raises(ValueError, match="identity"):
        audit.extract_detail(detail('<dt>発売日</dt><dd>2026.08.22</dd>', '別商品【OP-17】'), IDENTITY)


def test_composite_page_has_explicit_identity_and_common_date():
    identity = {"official_code": "ST-01", "display_name": "スタートデッキ 麦わらの一味【ST-01】"}
    raw = detail('<dl><dt>発売日</dt><dd>2022.07.08(金)</dd></dl>',
                 identity["display_name"] + '<br>スタートデッキ 最悪の世代【ST-02】')
    assert audit.extract_detail(raw, identity)[0]["dates"] == ["2022-07-08"]


def test_scheduled_label_retained_verbatim():
    observations = audit.extract_detail(detail('<dt>発売予定日</dt><dd>2027年1月23日(土)</dd>'), IDENTITY)
    assert observations[0]["published_label"] == "発売予定日"
    assert observations[0]["dates"] == ["2027-01-23"]


def test_index_newsdate_class_requires_release_label_and_matching_identity_url():
    def index(label, url):
        return (f'<a class="linkListColItem" href="{url}">'
                f'<h4 class="linkListColTitle">{IDENTITY["display_name"]}</h4>'
                f'<p class="linkListColDate"><span class="head">{label}</span>'
                '<time class="newsDate" datetime="2026-08-22">2026.08.22(土)</time></p></a>').encode()
    assert audit.extract_index(index("発売日", URL), IDENTITY, URL)[0]["dates"] == ["2026-08-22"]
    with pytest.raises(ValueError, match="not labelled as release"):
        audit.extract_index(index("記事公開日", URL), IDENTITY, URL)
    with pytest.raises(ValueError, match="identity URLs disagree"):
        audit.extract_index(index("発売日", URL + "other"), IDENTITY, URL)


def test_conflict_leaves_date_null_and_duplicate_url_is_not_corroboration():
    one = {"source_url": URL, "observations": [{"dates": ["2026-08-22"]}]}
    another = {"source_url": "https://www.onepiece-cardgame.com/products/", "observations": [{"dates": ["2026-08-29"]}]}
    assert audit.classify([one, another]) == ("DATE_CONFLICT", None)
    assert audit.classify([one, one]) == ("DATE_VERIFIED_SINGLE_SOURCE", "2026-08-22")


def test_raw_digest_recomputed_before_extraction(tmp_path):
    raw = b"<html>preserved bytes</html>"
    (tmp_path / "page.html.gz").write_bytes(gzip.compress(raw))
    record = {"source_catalogue": "bandai_jp", "source_url": URL, "final_url": URL,
              "fetched_at": "2026-09-24T10:00:00+00:00", "raw_path": "page.html.gz",
              "sha256": hashlib.sha256(raw).hexdigest(), "byte_length": len(raw),
              "label": "mock", "parser_version": "mock_v1", "content_type": "text/html"}
    assert audit.verify_raw(tmp_path, record) == raw
    record["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Digest mismatch"):
        audit.verify_raw(tmp_path, record)


def test_asia_or_english_product_url_is_rejected():
    with pytest.raises(ValueError, match="Non-JP official URL"):
        audit.official_url("https://en.onepiece-cardgame.com/products/boosters/op17/")
