import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from staging_policy import evaluate, RED


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.m = {"schema_version": 1, "mission": "fixture", "target": "staging",
                  "classification": "GREEN", "diff_sha256": "digest",
                  "red_decisions": {key: False for key in RED},
                  "deployment_verification": {"api_sha": "a" * 40, "revision": "c4e8a1d7b902"},
                  "impacts": [{"files": ["app.py"], "effects": ["application"],
                               "reason": "Fix bounded rendering bug"}]}

    def result(self, files=None):
        return evaluate(self.m, files or ["app.py"], "digest")

    def test_green(self):
        self.assertTrue(self.result()["eligible"])

    def test_red_overrides_harmless_path_and_green_claim(self):
        self.m["impacts"][0]["effects"].append("pricing_methodology")
        result = self.result()
        self.assertEqual(result["classification"], "RED")
        self.assertFalse(result["eligible"])
        self.assertIn("pricing_methodology", result["errors"][0])

    def test_production_refused(self):
        self.m["target"] = "production"
        self.assertEqual(self.result()["classification"], "RED")

    def test_stale_missing_duplicate_and_unknown_evidence_fail(self):
        original = copy.deepcopy(self.m)
        for mutation in (lambda m: m.update(diff_sha256="old"),
                         lambda m: m.update(impacts=[]),
                         lambda m: m["impacts"].append(m["impacts"][0]),
                         lambda m: m["impacts"][0].update(effects=["safe_trust_me"])):
            self.m = copy.deepcopy(original)
            mutation(self.m)
            self.assertFalse(self.result()["eligible"])

    def test_infrastructure_floor_and_explicit_effect(self):
        self.m["impacts"][0]["files"] = [".github/workflows/ci.yml"]
        self.assertEqual(self.result([".github/workflows/ci.yml"])["classification"], "AMBER")
        self.m["impacts"][0]["files"] = ["app.py"]
        self.m["impacts"][0]["effects"] = ["service_cutover"]
        self.assertEqual(self.result()["classification"], "AMBER")
        self.assertFalse(self.result()["eligible"])

    def test_amber_requires_all_safeguards_without_human_approval(self):
        self.m["classification"] = "AMBER"
        self.m["impacts"][0]["effects"] = ["infrastructure"]
        self.m["safeguards"] = {
            "impact": {"resources": ["staging-web"], "routes": ["/"],
                       "dependencies": ["staging-api"], "deployment_impact": "rebuild",
                       "database_writes": 0, "source_requests": 0, "estimated_runtime_minutes": 10},
            "recovery": {key: "evidence" for key in ["artifact", "procedure", "trigger", "backup", "validation"]},
            "verification": {"required_checks": ["engineering-gate"], "post_change": ["health"],
                             "observation_window": "one deployment"}}
        self.assertTrue(self.result()["eligible"])
        del self.m["safeguards"]["recovery"]["validation"]
        self.assertFalse(self.result()["eligible"])


if __name__ == "__main__":
    unittest.main()
