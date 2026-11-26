"""The three SNKRDUNK katakana EB names stay source renderings tied to their frozen evidence."""

import json
import runpy
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "docs/evidence/snkrdunk-katakana-eb-aliases-2026-11-19.json"
MIGRATION = ROOT / "services/api/alembic/versions/7d2f9b4e1a63_snkrdunk_katakana_eb_aliases.py"


def test_migration_matches_evidence_and_is_the_single_head():
    evidence = json.loads(EVIDENCE.read_text())
    migration = runpy.run_path(str(MIGRATION))
    rows = tuple((r["official_code"], r["alias_name"]) for r in evidence["accepted_mapping"])
    assert rows == migration["SOURCE_RENDERINGS"]
    assert all(r["alias_kind"] == "source_rendering" and r["source_url"] is None
               for r in evidence["accepted_mapping"])
    config = Config()
    config.set_main_option("script_location", str(ROOT / "services/api/alembic"))
    scripts = ScriptDirectory.from_config(config)
    # Later revisions may sit on top of it; it must stay in the one linear history.
    assert len(scripts.get_heads()) == 1
    assert migration["revision"] in {r.revision for r in scripts.walk_revisions()}
    assert migration["down_revision"] == "cb7419af37e9"


def test_no_rendering_is_a_bandai_name():
    bandai = (ROOT / "services/snkrdunk_collector/snkrdunk_collector/discovery_evidence/"
              "release_product_aliases.py").read_text()
    for _code, name in runpy.run_path(str(MIGRATION))["SOURCE_RENDERINGS"]:
        assert name not in bandai
