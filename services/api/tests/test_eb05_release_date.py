"""EB-05 release date stays tied to its frozen Bandai evidence and the linear history."""

import json
import runpy
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.release_product import RELEASE_DATE_SOURCES

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "docs/evidence/eb05-release-date-2026-11-24.json"
MIGRATION = ROOT / "services/api/alembic/versions/e216c1c45131_eb05_release_date.py"


def test_migration_matches_evidence_and_is_the_single_head():
    evidence = json.loads(EVIDENCE.read_text())
    migration = runpy.run_path(str(MIGRATION))
    rows = tuple((r["source_catalogue"], r["official_code"], r["release_date"], r["classification"])
                 for r in evidence["accepted_mapping"])
    assert rows == migration["ACCEPTED_RELEASE_DATES"] == (
        ("bandai_jp", "EB-05", "2026-10-31", "DATE_VERIFIED_SINGLE_SOURCE"),)
    assert {r[3] for r in rows} <= set(RELEASE_DATE_SOURCES)
    assert all(o["source_url"].startswith("https://www.onepiece-cardgame.com/products/")
               for o in evidence["observations"])
    config = Config()
    config.set_main_option("script_location", str(ROOT / "services/api/alembic"))
    scripts = ScriptDirectory.from_config(config)
    # Later revisions may sit on top of it; it must stay in the one linear history.
    assert len(scripts.get_heads()) == 1
    assert migration["revision"] in {r.revision for r in scripts.walk_revisions()}
    assert migration["down_revision"] == "7d2f9b4e1a63"
