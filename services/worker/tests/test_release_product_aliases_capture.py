"""The 2026-11-03 alias rows, re-derived from the committed Bandai capture.

The frozen catalogues the older rows were proven against are not in the
repository and their Asia-EN half is gone, so rows added on or after
2026-11-03 are proven against ops-readonly `bandai-label-evidence` run
41626034881, committed verbatim at docs/agent/evidence/. These tests run
always (the file is committed) and re-derive the module's three checks:

  1. the alias key equals a published series title, with or without its
     bracketed code, normalised exactly as the module does;
  2. that title names exactly one product code across BOTH catalogues;
  3. Bandai's JP and Asia-EN series for that code list the same card codes.

The SNKRDUNK labels are verbatim from stored candidates (the capture's own
label list), so the rows are pinned against the real corpus.
"""

import json
import pathlib
import re

import pytest

from worker.matching.release_product_aliases import alias_evidence, known_aliases, normalise_label, resolve_product_code

CAPTURE = pathlib.Path(__file__).resolve().parents[3] / "docs" / "agent" / "evidence" / "bandai-label-evidence-20261103.json"
RUN_ID = "41626034881"
BRACKETS = re.compile(r"[\[【].*?[\]】]")


def capture():
    return json.loads(CAPTURE.read_text(encoding="utf-8"))


def captured_rows():
    """{key: code} for the aliases whose recorded evidence cites the capture."""
    rows = {key: code for key, code in known_aliases().items() if RUN_ID in (alias_evidence(key) or "")}
    assert len(rows) == 15
    return rows


def title_index():
    index = {}
    data = capture()
    for catalogue in ("bandai_jp", "bandai_asia_en"):
        for series_id, name in data["pickers"][catalogue]:
            code = next((c["code"] for c in data["codes"] if series_id in c["jp"] + c["en"]), None)
            for form in (name, BRACKETS.sub("", name)):
                key = normalise_label(form)
                if key:
                    index.setdefault(key, set()).add(code)
    return index


def test_the_capture_is_the_run_the_rows_cite():
    data = capture()
    assert str(data["run_id"]) == RUN_ID
    assert len(data["pickers"]["bandai_jp"]) == 63 and len(data["pickers"]["bandai_asia_en"]) == 63


def test_checks_1_and_2_every_captured_row_is_one_published_title_naming_one_product():
    index = title_index()
    for key, code in captured_rows().items():
        assert key in index, f"{key!r} matches no published Bandai series title in the capture"
        assert index[key] == {code}, f"{key!r} names {sorted(map(str, index[key]))}, not only {code}"


def test_check_3_jp_and_asia_en_list_the_same_cards():
    by_code = {c["code"]: c for c in capture()["codes"]}
    for code in set(captured_rows().values()):
        row = by_code[code]
        assert len(row["jp"]) == 1 and len(row["en"]) == 1, f"{code}: not one series per catalogue"
        assert row["same_membership"] is True and row["jp_n"] == row["en_n"] > 0, f"{code}: contents differ"


def test_every_official_label_snkrdunk_printed_now_resolves():
    for label in capture()["labels"]:
        if label["verdict"] == "official_unique":
            assert resolve_product_code(label["label"]) == label["codes"][0], label["label"]


@pytest.mark.parametrize(
    "label",
    [
        # SNKRDUNK's own OP-07 renderings: no Bandai title, so no official row.
        "Booster Pack 500 Yeas in the Future",
        "Booster Pack The Future After 500 years",
        # Near misses and fragments of the new rows.
        "Booster Pack Two Legend",
        "Booster Pack Royal Bloods",
        "Royal Blood",
        "Extra Booster EGGHEAD",
        "Booster Pack Wings of the Captain",
        "Booster Pack Legacy of the Masters",
    ],
)
def test_near_misses_and_unpublished_renderings_stay_unresolved(label):
    assert resolve_product_code(label) is None
