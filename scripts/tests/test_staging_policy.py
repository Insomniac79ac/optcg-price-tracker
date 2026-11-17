import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from staging_policy import evaluate, RED
import yaml


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
        # Not even with an approval link: there is no production.
        self.m["owner_approvals"] = {"production": "https://github.com/Insomniac79ac/optcg-price-tracker/issues/1"}
        self.assertFalse(self.result()["eligible"])

    def approved_red(self):
        self.m["classification"] = "RED"
        self.m["impacts"][0]["effects"] = ["application", "security_or_secrets_policy"]
        self.m["owner_approvals"] = {
            "security_or_secrets_policy": "https://github.com/Insomniac79ac/optcg-price-tracker/issues/293"}
        self.m["safeguards"] = {
            "impact": {"resources": ["staging-api"], "routes": ["/me"],
                       "dependencies": ["staging-web"], "deployment_impact": "API redeploy",
                       "database_writes": 0, "source_requests": 0, "estimated_runtime_minutes": 10},
            "recovery": {key: "evidence" for key in ["artifact", "procedure", "trigger", "backup", "validation"]},
            "verification": {"required_checks": ["engineering-gate"], "post_change": ["health"],
                             "observation_window": "one deployment"}}

    def test_approved_red_passes_but_is_owner_merge_only(self):
        self.approved_red()
        result = self.result()
        self.assertEqual(result["classification"], "RED")
        self.assertTrue(result["eligible"], result["errors"])
        self.assertIs(result["owner_merge_only"], True)

    def test_red_needs_a_valid_approval_for_every_category(self):
        self.approved_red()
        for approvals in ({}, {"security_or_secrets_policy": "owner said yes"},
                          {"security_or_secrets_policy": "https://github.com/someone-else/repo/issues/1"},
                          ["https://github.com/Insomniac79ac/optcg-price-tracker/issues/293"]):
            self.m["owner_approvals"] = approvals
            result = self.result()
            self.assertFalse(result["eligible"])
            self.assertIn("security_or_secrets_policy", result["errors"][0])
        self.m["owner_approvals"] = {
            "security_or_secrets_policy": "https://github.com/Insomniac79ac/optcg-price-tracker/issues/293"}
        self.m["red_decisions"]["pricing_methodology"] = True
        self.assertFalse(self.result()["eligible"])

    def test_approved_red_still_needs_every_other_check(self):
        self.approved_red()
        original = copy.deepcopy(self.m)
        for mutation in (lambda m: m.update(diff_sha256="old"),
                         lambda m: m.update(classification="AMBER"),
                         lambda m: m["safeguards"]["recovery"].pop("validation"),
                         lambda m: m["owner_approvals"].update(pricing_methodology=m["owner_approvals"]["security_or_secrets_policy"])):
            self.m = copy.deepcopy(original)
            mutation(self.m)
            self.assertFalse(self.result()["eligible"])

    def test_approved_red_cannot_request_rollout_or_migration(self):
        self.approved_red()
        for key, value in (("collector_services", ["snkrdunk-collector"]), ("raw_dependency_migration", {"x": 1})):
            self.m["deployment_verification"] = {"api_sha": "a" * 40, "revision": "c4e8a1d7b902", key: value}
            self.assertFalse(self.result()["eligible"])

    def test_green_and_amber_are_never_owner_merge_only(self):
        self.assertNotIn("owner_merge_only", self.result())

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


class NativeDeliveryRegressionTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2]
        self.ci = yaml.load((root / '.github/workflows/ci.yml').read_text(), Loader=yaml.BaseLoader)
        self.delivery = yaml.load((root / '.github/workflows/staging-delivery.yml').read_text(), Loader=yaml.BaseLoader)

    def test_native_arming_cannot_wait_for_its_required_gate(self):
        # Waiting for engineering-gate made --auto fall through to a direct
        # merge. Keep that gate required and independent of the lease owner.
        needs = self.ci['jobs']['staging-automerge']['needs']
        self.assertIn('policy-gate', needs)
        self.assertIn('staging-credential-presence', needs)
        self.assertNotIn('engineering-gate', needs)
        self.assertNotIn('staging-automerge', self.ci['jobs']['engineering-gate']['needs'])
        self.assertIn('frontend-build', self.ci['jobs']['engineering-gate']['needs'])
        self.assertIn('backend-tests', self.ci['jobs']['engineering-gate']['needs'])

    def test_environment_secret_resolution_has_no_reusable_boundary(self):
        job = self.ci['jobs']['staging-automerge']
        self.assertNotIn('uses', job)
        self.assertEqual(job['environment'], 'staging-delivery')
        self.assertEqual(job['environment'], self.ci['jobs']['staging-credential-presence']['environment'])
        self.assertEqual(job['steps'][0]['env']['STAGING_RAILWAY_TOKEN'], '${{ secrets.STAGING_RAILWAY_TOKEN }}')
        self.assertEqual(job['steps'][0]['env']['STAGING_VERCEL_READ_TOKEN'], '${{ secrets.STAGING_VERCEL_READ_TOKEN }}')

    def test_no_direct_merge_fallback_and_head_remains_pinned(self):
        job = self.ci['jobs']['staging-automerge']
        self.assertNotIn('uses', job, 'Environment secrets must resolve in a normal job')
        arm, wait = job['steps'][:2]
        self.assertIn('enablePullRequestAutoMerge', arm['run'])
        self.assertIn('expectedHeadOid:$head', arm['run'])
        self.assertNotIn('gh pr merge', arm['run'])
        self.assertIn(".head.sha", wait['run'])
        self.assertEqual(wait['env']['HEAD'], '${{ github.event.pull_request.head.sha }}')
        self.assertEqual(job['concurrency']['group'], 'card-pirate-staging-delivery')
        self.assertEqual(job['concurrency']['cancel-in-progress'], 'false')
        self.assertIn('Required staging environment secret unavailable: $name', arm['run'])

    def test_approved_red_is_never_armed(self):
        # Owner 2026-11-17: approved RED work passes policy-gate but only the owner merges it.
        self.assertIn('owner_merge_only', self.ci['jobs']['policy-gate']['outputs'])
        live = self.ci['jobs']['staging-pr-live']['steps'][0]
        self.assertEqual(live['env']['OWNER_MERGE_ONLY'], '${{ needs.policy-gate.outputs.owner_merge_only }}')
        self.assertIn('env.OWNER_MERGE_ONLY != "true"', live['run'])
        arm = self.ci['jobs']['staging-automerge']['steps'][0]
        self.assertEqual(arm['env']['OWNER_MERGE_ONLY'], '${{ needs.policy-gate.outputs.owner_merge_only }}')
        self.assertIn('approved RED work is merged by the owner by hand', arm['run'])

    def test_behind_or_conflicting_pr_fails_fast(self):
        # Owner 2026-11-17: #294 waited 30 minutes behind staging and timed out.
        arm, wait = self.ci['jobs']['staging-automerge']['steps'][:2]
        for step in (arm, wait):
            self.assertIn('behind|dirty)', step['run'])
            self.assertIn('Never use GitHub', step['run'])


if __name__ == "__main__":
    unittest.main()
