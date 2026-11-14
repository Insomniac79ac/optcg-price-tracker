"""OP-18 release date stays tied to its frozen Bandai evidence and the linear history."""

import json
import runpy
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.release_product import RELEASE_DATE_SOURCES

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "docs/evidence/op18-release-date-2026-11-12.json"
MIGRATION = ROOT / "services/api/alembic/versions/cb7419af37e9_op18_release_date.py"


def test_migration_matches_evidence_and_is_the_single_head():
    evidence = json.loads(EVIDENCE.read_text())
    migration = runpy.run_path(str(MIGRATION))
    rows = tuple((r["source_catalogue"], r["official_code"], r["release_date"], r["classification"])
                 for r in evidence["accepted_mapping"])
    assert rows == migration["ACCEPTED_RELEASE_DATES"] == (
        ("bandai_jp", "OP-18", "2026-11-21", "DATE_VERIFIED_SINGLE_SOURCE"),)
    assert {r[3] for r in rows} <= set(RELEASE_DATE_SOURCES)
    assert all(o["source_url"].startswith("https://www.onepiece-cardgame.com/products/")
               for o in evidence["observations"])
    config = Config()
    config.set_main_option("script_location", str(ROOT / "services/api/alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [migration["revision"]]
    assert migration["down_revision"] == "001d92ba8eb9"
