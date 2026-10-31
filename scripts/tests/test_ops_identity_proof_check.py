"""identity-proof-check: the validator's refusal is named per review, nothing else changes.

The resolver itself is tested in services/api; here a stand-in analysis calls the real resolve()
path (registry lookup, staging gate, validate) so the recording, verdicts and restoration are
pinned without a database."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "services/api"))
from ops import identity_proof_check as ipc, run  # noqa: E402

PROOFS = [{"source_candidate_id": 1, "selected_card_print_id": 11, "work_id": 101, "actor": "claude:t"},
          {"source_candidate_id": 2, "selected_card_print_id": 22, "work_id": 102, "actor": "claude:t"},
          {"source_candidate_id": 3, "selected_card_print_id": 33, "work_id": 103, "actor": "claude:t"},
          {"source_candidate_id": 4, "selected_card_print_id": 44, "work_id": 104, "actor": "claude:t"}]


def plan(cid, status="ambiguous"):
    return SimpleNamespace(source_candidate_id=cid, resolution_status=status, resolution_reasons=("r",))


def fake_validate(db, plan_, siblings, proof):
    if plan_.source_candidate_id == 2:
        raise ValueError("review is not bound to the current evidence")
    return "digest"


def fake_analysis(session, filters, **kwargs):
    from app.services import physical_artwork_proof as pap

    assert filters.candidate_ids == (1, 2, 3, 4) and kwargs["ignore_existing_mappings"] is True
    outcomes = []
    for cid in (1, 2, 3):
        p = plan(cid, "exact" if cid == 3 else "ambiguous")
        if p.resolution_status == "ambiguous":
            pap.resolve(session, p, [])
        outcomes.append(SimpleNamespace(candidate_id=cid, source_name="yuyutei", proposal=p))
    return SimpleNamespace(outcomes=outcomes)


class Check(unittest.TestCase):
    def test_each_review_gets_a_verdict_and_the_refusal_is_named(self):
        from app.services import physical_artwork_proof as pap
        import app.env as app_env

        session = mock.Mock()
        with mock.patch.object(pap, "validate", fake_validate), \
                mock.patch("app.services.source_mapping_proposals.analyse_source_mapping_proposals", fake_analysis):
            before = (pap.validate, pap.registry, app_env.get_app_env)
            rows = {r["source_candidate_id"]: r for r in ipc.check(session, PROOFS)}
            self.assertEqual((pap.validate, pap.registry, app_env.get_app_env), before)  # restored
        self.assertEqual(rows[1]["verdict"], "resolved")
        self.assertEqual(rows[2]["verdict"], "refused")
        self.assertEqual(rows[2]["refusal"], "ValueError: review is not bound to the current evidence")
        self.assertEqual(rows[3]["verdict"], "not_ambiguous_now:exact")
        self.assertEqual(rows[4]["verdict"], "candidate_not_analysed")
        session.rollback.assert_called()

    def test_registered_as_read_only(self):
        self.assertEqual(run.RUNBOOKS["identity-proof-check"][:2], ("read", False))


if __name__ == "__main__":
    unittest.main()
