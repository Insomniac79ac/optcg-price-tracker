from pathlib import Path
import re
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collector_variables as cv

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "b" * 40
SID = "2d7ab69b-ec1f-4c66-8da1-9c8769a6d14a"
IMAGE = "sha256:" + "1" * 64


def deployment(identity, status="SUCCESS", redeploy=False, image=IMAGE):
    return {"id": identity, "status": status, "canRedeploy": redeploy,
            "meta": {"cliMessage": cv.MARKER + COMMIT, "imageDigest": image}}


def node(latest):
    return {"serviceId": SID, "cronSchedule": "27,57 * * * *",
            "startCommand": "python -m snkrdunk_collector.collect --due-work",
            "latestDeployment": {"id": latest, "status": "SUCCESS"}}


class Harness:
    """Fake Railway: active upload clone, an older redeployable upload, a GitHub build."""

    def __init__(self, stage_starts_deploy=False, clone_image=IMAGE, readback="true"):
        self.deployments = {
            "active": deployment("active"),
            "upload": deployment("upload", "REMOVED", redeploy=True),
            "github": {"id": "github", "status": "REMOVED", "canRedeploy": True,
                       "meta": {"imageDigest": "sha256:" + "2" * 64}},
        }
        self.latest = "active"
        self.stage_starts_deploy = stage_starts_deploy
        self.clone_image = clone_image
        self.readback = readback
        self.commands = []
        self.redeployed = []

    def inspect(self):
        return {"snkrdunk-collector": node(self.latest)}

    def read(self, identity, service_id, commit):
        row = self.deployments[identity]
        if service_id != SID or row["meta"].get("cliMessage") != cv.MARKER + commit:
            raise cv.state.VerificationError("Uploaded deployment destination/source mismatch")
        return row

    def run(self, command, **kwargs):
        self.commands.append(command)
        if command[-1] == "--help":
            return Mock(returncode=0, stdout="      --skip-deploys   Skip triggering deploys")
        if self.stage_starts_deploy:
            self.latest = "github"
        return Mock(returncode=0, stdout="")

    def railway(self, query):
        source = re.search(r'deploymentRedeploy\(id:"([^"]+)"', query).group(1)
        self.redeployed.append(source)
        self.deployments["clone"] = deployment("clone", image=self.clone_image)
        self.latest = "clone"
        return {"deploymentRedeploy": {"id": "clone"}}

    def change(self, assignments=None):
        return cv.change(
            "snkrdunk-collector", assignments or {"RAW_DICTIONARY_STORAGE_ENABLED": "true"},
            COMMIT, inspect=self.inspect, read=self.read, run=self.run, railway=self.railway,
            variables=lambda sid: {"RAW_DICTIONARY_STORAGE_ENABLED": self.readback},
            listing=lambda sid: ["active", "github", "upload"],
            sleep=lambda s: None)


class AssignmentTests(unittest.TestCase):
    def test_only_writer_keys_and_staging_app_env(self):
        self.assertEqual(cv.parse_assignments(["APP_ENV=staging", "RAW_DICTIONARY_STORAGE_MODE=daily-v1"]),
                         {"APP_ENV": "staging", "RAW_DICTIONARY_STORAGE_MODE": "daily-v1"})
        for item in ["APP_ENV=production", "DUE_MAX_PRODUCTS_PER_RUN=70", "YUYUTEI_REQUEST_DELAY_MS=0",
                     "RAW_DICTIONARY_STORAGE_ENABLED=yes", "RAW_DICTIONARY_STORAGE_ENABLED"]:
            with self.assertRaises(cv.state.VerificationError):
                cv.parse_assignments([item])
        with self.assertRaises(cv.state.VerificationError):
            cv.parse_assignments([])

    def test_non_collector_refused(self):
        with self.assertRaises(cv.state.VerificationError):
            cv.service_node("optcg-price-tracker", inspect=lambda: {})


class ChangeTests(unittest.TestCase):
    def test_stages_with_skip_deploys_then_redeploys_identical_upload(self):
        fake = Harness()
        receipt = fake.change()
        stage = [c for c in fake.commands if c[-1] != "--help"]
        self.assertEqual(len(stage), 1)
        self.assertIn("--skip-deploys", stage[0])
        self.assertEqual(stage[0][-1], "RAW_DICTIONARY_STORAGE_ENABLED=true")
        # Active clone is not redeployable; the older marked upload of the same image is.
        self.assertEqual(fake.redeployed, ["upload"])
        self.assertEqual((receipt["deployment"], receipt["image_digest"]), ("clone", IMAGE))
        self.assertEqual(receipt["marker"], cv.MARKER + COMMIT)

    def test_github_rebuild_is_never_a_source_or_active(self):
        fake = Harness()
        fake.latest = "github"
        with self.assertRaises(cv.state.VerificationError):
            fake.change()
        self.assertEqual(fake.redeployed, [])
        self.assertEqual([c for c in fake.commands if c[-1] != "--help"], [])

    def test_staging_that_starts_a_deploy_refuses(self):
        fake = Harness(stage_starts_deploy=True)
        with self.assertRaises(cv.state.VerificationError):
            fake.change()
        self.assertEqual(fake.redeployed, [])

    def test_different_image_refused(self):
        with self.assertRaises(cv.state.VerificationError):
            Harness(clone_image="sha256:" + "3" * 64).change()

    def test_readback_mismatch_refused(self):
        with self.assertRaises(cv.state.VerificationError):
            Harness(readback="false").change()

    def test_cli_without_skip_deploys_refused(self):
        fake = Harness()
        fake.run = lambda command, **kw: Mock(returncode=0, stdout="no such flag")
        with self.assertRaises(cv.state.VerificationError):
            fake.change()
        self.assertEqual(fake.redeployed, [])

    def test_no_redeployable_identical_upload_refused(self):
        fake = Harness()
        fake.deployments["upload"]["canRedeploy"] = False
        with self.assertRaises(cv.state.VerificationError):
            fake.change()


class OnlyPathTests(unittest.TestCase):
    PATTERN = re.compile(r"variable['\"]?\s*,\s*['\"]set|variable\s+set|variableUpsert|"
                         r"variableCollectionUpsert|variables\s+--set")

    def test_no_other_tooling_sets_railway_variables(self):
        offenders = []
        for base in ("scripts", "services", "deploy", ".github"):
            for path in (ROOT / base).rglob("*"):
                if (not path.is_file() or path.suffix not in {".py", ".sh", ".yml", ".yaml", ".js", ".ts"}
                        or "tests" in path.parts or "node_modules" in path.parts):
                    continue
                if path.name == "collector_variables.py":
                    continue
                text = path.read_text(errors="ignore")
                # Admin-login secret setter (defaults to the API service). It
                # always passes --skip-deploys, so it never triggers a rebuild,
                # and sets only ADMIN_LOGIN_* keys. Editing it changes collector
                # image inputs (services/api), so its collector refusal is
                # deferred to the next collector release.
                if path.name == "generate_admin_password_hash.py":
                    keys = set(re.findall(r'railway_set\("([A-Z_]+)"', text))
                    if "--skip-deploys" in text and keys and all(k.startswith("ADMIN_LOGIN_") for k in keys):
                        continue
                if self.PATTERN.search(text):
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], "Use scripts/collector_variables.py for collector variables")


if __name__ == "__main__":
    unittest.main()
