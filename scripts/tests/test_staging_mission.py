import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import staging_mission as sm
from staging_policy import RED
import yaml

FLEET = {"schema_version": 1,
         "deployment_verification": {"api_sha": "merge", "revision": "c4e8a1d7b902",
                                     "checks": ["scripts/verify_yuyu_raw_reader_component.py"],
                                     "yuyu_reader_component": "b" * 40},
         "operational_notes": ["carried"]}


def mission(files, **extra):
    return {"schema_version": 1, "mission": "fixture", "target": "staging", "classification": "GREEN",
            "red_decisions": {key: False for key in RED},
            "impacts": [{"files": files, "effects": ["application"], "reason": "Bounded fixture change"}],
            **extra}


class ComposeTests(unittest.TestCase):
    def test_fleet_plus_mission_requests(self):
        m = mission(["app.py"], deployment_verification={"collector_services": [{"name": "x"}],
                                                         "yuyu_reader_component": "merge"})
        c = sm.compose(m, FLEET)
        v = c["deployment_verification"]
        self.assertEqual(v["revision"], "c4e8a1d7b902")
        self.assertEqual(v["collector_services"], [{"name": "x"}])
        self.assertEqual(v["yuyu_reader_component"], "merge")
        self.assertEqual(c["operational_notes"], ["carried"])
        self.assertEqual(c["mission"], "fixture")

    def test_no_mission_is_fleet_only(self):
        c = sm.compose({}, FLEET)
        self.assertEqual(c["deployment_verification"], FLEET["deployment_verification"])
        self.assertNotIn("collector_services", c["deployment_verification"])

    def test_mission_may_not_replace_fleet_expectations(self):
        for key, value in (("api_sha", "a" * 40), ("revision", "000000000000"), ("checks", []),
                           ("yuyu_capacity_cadence", False)):
            with self.subTest(key=key):
                with self.assertRaisesRegex(sm.MissionError, "fleet expectations"):
                    sm.compose(mission([], deployment_verification={key: value}), FLEET)

    def test_fleet_may_not_request_or_float(self):
        for key, value in (("collector_services", [{"name": "x"}]), ("raw_dependency_migration", {}),
                           ("yuyu_reader_component", "merge"), ("snkr_component", "abc")):
            with self.subTest(key=key):
                fleet = copy.deepcopy(FLEET)
                fleet["deployment_verification"][key] = value
                with self.assertRaises(sm.MissionError):
                    sm.compose(mission([]), fleet)

    def test_malformed_inputs_refused(self):
        for m, fleet in ((mission([], operational_notes=["x"]), FLEET),
                         (mission([], deployment_verification=[]), FLEET),
                         (mission([], deployment_verification={"snkr_component": "HEAD"}), FLEET),
                         ([], FLEET), (mission([]), {**FLEET, "schema_version": 2}),
                         (mission([]), {**FLEET, "impacts": []}),
                         (mission([]), {"schema_version": 1})):
            with self.assertRaises(sm.MissionError):
                sm.compose(m, fleet)

    def test_added_mission_rules(self):
        one = "docs/agent/missions/claude-x.json"
        self.assertEqual(sm.added_mission([("A", one)]), one)
        self.assertIsNone(sm.added_mission([], allow_none=True))
        for rows, message in (([], "found 0"),
                              ([("A", one), ("A", "docs/agent/missions/y.json")], "found 2"),
                              ([("M", one)], "never changed"), ([("D", one)], "never changed"),
                              ([("A", one), ("M", "docs/agent/missions/old.json")], "never changed"),
                              ([("A", "docs/agent/missions/sub/x.json")], "<name>.json"),
                              ([("A", "docs/agent/missions/x.yaml")], "<name>.json")):
            with self.subTest(rows=rows):
                with self.assertRaisesRegex(sm.MissionError, message):
                    sm.added_mission(rows)

    def test_verifiers_read_delivery_manifest_else_fleet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs/agent").mkdir(parents=True)
            (root / sm.FLEET).write_text(json.dumps(FLEET))
            composed = root / "composed.json"
            composed.write_text(json.dumps({"deployment_verification": {"api_sha": "c" * 40}}))
            with patch.dict(os.environ, {sm.MANIFEST_ENV: ""}):
                self.assertEqual(sm.deployment_verification(root)["revision"], "c4e8a1d7b902")
            with patch.dict(os.environ, {sm.MANIFEST_ENV: str(composed)}):
                self.assertEqual(sm.deployment_verification(root)["api_sha"], "c" * 40)


class Repo:
    def __init__(self, case):
        tmp = tempfile.TemporaryDirectory()
        case.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.run("init", "-q", "-b", "staging")
        for key, value in (("user.email", "t@example.invalid"), ("user.name", "t"),
                           ("maintenance.auto", "false"), ("gc.auto", "0")):
            self.run("config", key, value)
        self.write({sm.FLEET: json.dumps(FLEET), "app.py": "x = 1\n", "lib.py": "y = 1\n",
                    "docs/agent/missions/earlier.json": json.dumps(mission(["lib.py"]))})
        self.commit("base")

    def run(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True,
                              text=True).stdout.strip()

    def write(self, files):
        for path, text in files.items():
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text(text)

    def commit(self, message):
        self.run("add", "-A")
        self.run("commit", "-qm", message)
        return self.run("rev-parse", "HEAD")

    def evidence(self, path, base="staging", head="HEAD"):
        cwd = Path.cwd()
        try:
            os.chdir(self.root)
            return sm.change_evidence(base, head, path)
        finally:
            os.chdir(cwd)

    def legacy_sha(self, path):
        """The retired two-dot hash: base tip to head, no full index."""
        patch = subprocess.check_output(["git", "diff", "--binary", "staging", "HEAD", "--", ".",
                                         f":(exclude){path}"], cwd=self.root)
        return hashlib.sha256(patch).hexdigest()

    def seal(self, path, files, **extra):
        """Write the PR's mission with the hash of its current change, then commit."""
        self.write({path: json.dumps(mission(files, **extra))})
        self.commit("mission")
        _, sha = self.evidence(path)
        self.write({path: json.dumps(mission(files, diff_sha256=sha, **extra))})
        return self.commit("seal mission")

    def policy(self, base="staging", head="HEAD"):
        out = self.root.parent / (self.root.name + "-policy.json")
        proc = subprocess.run([sys.executable, str(SCRIPTS / "staging_policy.py"), "--base", base,
                               "--head", head, "--output", str(out)], cwd=self.root,
                              capture_output=True, text=True)
        result = json.loads(out.read_text())
        out.unlink()
        return proc.returncode, result


class PolicyGitTests(unittest.TestCase):
    MISSION = "docs/agent/missions/claude-feature.json"

    def pr(self):
        repo = Repo(self)
        repo.run("checkout", "-qb", "feature")
        repo.write({"app.py": "x = 2\n"})
        repo.commit("feature")
        return repo

    def assertRefused(self, repo, message):
        code, result = repo.policy()
        self.assertEqual(code, 1, result)
        self.assertFalse(result["eligible"])
        self.assertTrue(any(message in e for e in result["errors"]), result["errors"])

    def test_one_added_mission_is_admitted(self):
        repo = self.pr()
        repo.seal(self.MISSION, ["app.py"])
        code, result = repo.policy()
        self.assertEqual((code, result["classification"], result["errors"]), (0, "GREEN", []))

    def test_merging_staging_in_keeps_the_hash(self):
        repo = self.pr()
        repo.seal(self.MISSION, ["app.py"])
        sealed, legacy = repo.evidence(self.MISSION), repo.legacy_sha(self.MISSION)
        repo.run("checkout", "-q", "staging")
        repo.write({"lib.py": "y = 2\n", "docs/agent/missions/other.json": json.dumps(mission(["lib.py"]))})
        repo.commit("another PR merged")
        repo.run("checkout", "-q", "feature")
        # Staging moved: the retired two-dot hash is stale, the PR's own change is not.
        self.assertNotEqual(repo.legacy_sha(self.MISSION), legacy)
        self.assertEqual(repo.evidence(self.MISSION), sealed)
        self.assertEqual(repo.policy()[0], 0)
        repo.run("merge", "-q", "--no-edit", "staging")
        self.assertEqual(repo.evidence(self.MISSION), sealed)
        code, result = repo.policy()
        self.assertEqual((code, result["errors"]), (0, []))

    def test_hash_uses_full_index_lines(self):
        repo = self.pr()
        repo.seal(self.MISSION, ["app.py"])
        cwd = Path.cwd()
        os.chdir(repo.root)
        try:
            patch_text = subprocess.check_output(["git", "diff", "--binary", "--full-index", "staging",
                                                  "HEAD", "--", "app.py"], text=True)
            files, sha = sm.change_evidence("staging", "HEAD", self.MISSION)
        finally:
            os.chdir(cwd)
        self.assertEqual(files, ["app.py"])
        self.assertEqual(sha, hashlib.sha256(patch_text.encode()).hexdigest())
        self.assertRegex(patch_text, r"index [0-9a-f]{40}\.\.[0-9a-f]{40}")

    def test_zero_missions_refused(self):
        self.assertRefused(self.pr(), "found 0")

    def test_two_missions_refused(self):
        repo = self.pr()
        repo.write({"docs/agent/missions/second.json": "{}"})
        repo.commit("second")
        repo.seal(self.MISSION, ["app.py"])
        self.assertRefused(repo, "found 2")

    def test_edited_or_removed_existing_mission_refused(self):
        for change in ("edit", "remove"):
            with self.subTest(change=change):
                repo = self.pr()
                if change == "edit":
                    repo.write({"docs/agent/missions/earlier.json": json.dumps(mission(["lib.py", "x"]))})
                else:
                    (repo.root / "docs/agent/missions/earlier.json").unlink()
                repo.commit(change)
                repo.seal(self.MISSION, ["app.py"])
                self.assertRefused(repo, "never changed or removed")

    def test_stale_hash_refused(self):
        repo = self.pr()
        repo.seal(self.MISSION, ["app.py"])
        repo.write({"app.py": "x = 3\n"})
        repo.commit("after sealing")
        self.assertRefused(repo, "Impact evidence is stale")

    def test_fleet_change_must_be_declared(self):
        repo = self.pr()
        fleet = copy.deepcopy(FLEET)
        fleet["deployment_verification"]["revision"] = "d" * 12
        repo.write({sm.FLEET: json.dumps(fleet)})
        repo.commit("move fleet")
        repo.seal(self.MISSION, ["app.py"])
        self.assertRefused(repo, "cover each changed file exactly once")
        repo.seal(self.MISSION, ["app.py", sm.FLEET])
        code, result = repo.policy()
        self.assertEqual((code, result["errors"]), (0, []))

    def test_mission_overriding_fleet_refused(self):
        repo = self.pr()
        repo.seal(self.MISSION, ["app.py"], deployment_verification={"revision": "d" * 12})
        self.assertRefused(repo, "may not set fleet expectations")

    def test_rename_must_cover_both_paths(self):
        repo = Repo(self)
        repo.run("checkout", "-qb", "feature")
        repo.run("mv", "lib.py", "lib2.py")
        repo.commit("rename")
        repo.seal(self.MISSION, ["lib2.py"])
        self.assertRefused(repo, "cover each changed file exactly once")
        repo.seal(self.MISSION, ["lib.py", "lib2.py"])
        self.assertEqual(repo.policy()[0], 0)

    def test_legacy_manifest_requests_must_be_declared(self):
        # A revert of the per-PR switch restores STAGING_MISSION.json, which the
        # restored old delivery would act on.
        repo = self.pr()
        rollout = {"deployment_verification": {"collector_services": [{"name": "snkrdunk-collector"}]}}
        repo.write({sm.LEGACY_MANIFEST: json.dumps(rollout)})
        repo.commit("restore legacy manifest")
        repo.seal(self.MISSION, ["app.py", sm.LEGACY_MANIFEST])
        self.assertRefused(repo, "does not declare")
        repo.seal(self.MISSION, ["app.py", sm.LEGACY_MANIFEST],
                  deployment_verification=rollout["deployment_verification"])
        self.assertEqual(repo.policy()[0], 0)
        repo.write({sm.LEGACY_MANIFEST: json.dumps({"deployment_verification": {}})})
        repo.commit("strip requests")
        repo.seal(self.MISSION, ["app.py", sm.LEGACY_MANIFEST])
        self.assertEqual(repo.policy()[0], 0)

    def test_compose_cli_for_delivery(self):
        repo = self.pr()
        repo.seal(self.MISSION, ["app.py"], deployment_verification={"collector_services": [{"name": "x"}]})
        repo.run("checkout", "-q", "staging")
        repo.run("merge", "-q", "--no-ff", "--no-edit", "feature")
        merge = repo.run("rev-parse", "HEAD")
        out = repo.root.parent / (repo.root.name + "-composed.json")
        self.addCleanup(lambda: out.unlink(missing_ok=True))
        cli = lambda *extra: subprocess.run(
            [sys.executable, str(SCRIPTS / "staging_mission.py"), "compose", "--base", merge + "^1",
             "--head", merge, "--output", str(out), *extra], cwd=repo.root, capture_output=True, text=True)
        self.assertEqual(cli().returncode, 0)
        v = json.loads(out.read_text())["deployment_verification"]
        self.assertEqual((v["collector_services"], v["revision"]), ([{"name": "x"}], "c4e8a1d7b902"))
        # A merge without a mission (PRODUCT lane): fleet only with --allow-none, else refused.
        repo.write({"docs/x.md": "product\n"})
        merge = repo.commit("product")
        out.unlink()
        self.assertEqual(cli().returncode, 1)
        self.assertFalse(out.exists())
        self.assertEqual(cli("--allow-none").returncode, 0)
        self.assertNotIn("collector_services", json.loads(out.read_text())["deployment_verification"])


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        root = SCRIPTS.parent
        load = lambda p: yaml.load((root / p).read_text(), Loader=yaml.BaseLoader)
        self.ci = load(".github/workflows/ci.yml")
        self.delivery = load(".github/workflows/staging-delivery.yml")
        self.verify = load(".github/workflows/staging-verify.yml")

    def steps(self, job):
        return {step.get("name", ""): step for step in job["steps"]}

    def test_delivery_reads_only_the_composed_manifest(self):
        for job in (self.ci["jobs"]["staging-automerge"], self.delivery["jobs"]["deliver"]):
            steps = self.steps(job)
            scope = steps["Decide documentation-only or product-lane delivery scope"]["run"]
            self.assertIn("python scripts/staging_mission.py compose", scope)
            self.assertIn('if [ "$decision" != full ]; then none=(--allow-none); fi', scope)
            self.assertIn("exit 1", scope)
            raw = steps["Apply reviewed additive RAW dependency migration"]
            rollout = steps["Deploy mission-scoped staging collectors"]
            verify = steps["Verify native Git deployment and regenerate state"]
            for step in (raw, rollout):
                self.assertIn('--manifest "$MANIFEST"', step["run"])
                self.assertEqual(step["env"]["MANIFEST"], "${{ steps.scope.outputs.manifest }}")
            self.assertEqual(verify["env"]["STAGING_MISSION_MANIFEST"], "${{ steps.scope.outputs.manifest }}")
            for step in job["steps"]:
                self.assertNotIn("STAGING_MISSION.json", step.get("run", ""))

    def test_hand_merge_verification_composes_fleet_and_mission(self):
        run = self.verify["jobs"]["verify"]["steps"][-3]["run"]
        self.assertIn('staging_mission.py compose --base "$EXPECTED^1" --head "$EXPECTED" --allow-none', run)
        self.assertNotIn("STAGING_MISSION.json", run)

    def test_policy_gate_runs_base_policy_with_legacy_bootstrap_only(self):
        run = self.steps(self.ci["jobs"]["policy-gate"])["Evaluate lane and mission against exact PR diff"]["run"]
        self.assertIn("python /tmp/base/scripts/staging_policy.py", run)
        self.assertIn("if [ ! -f /tmp/base/scripts/staging_mission.py ]; then", run)
        legacy = run.split("if [ ! -f /tmp/base/scripts/staging_mission.py ]; then", 1)[1].split("fi", 1)[0]
        self.assertIn("STAGING_MISSION.json", legacy)
        self.assertEqual(run.count("STAGING_MISSION.json"), 1)


if __name__ == "__main__":
    unittest.main()
