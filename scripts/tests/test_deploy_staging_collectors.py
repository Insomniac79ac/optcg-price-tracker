import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deploy_staging_collectors as delivery


class CollectorDeliveryTests(unittest.TestCase):
    expected = "a" * 40
    name = "yuyutei-collector-shard-2"
    service_id = "0169974d-e181-4454-8a0d-65733a76cdb3"

    def service(self, deployment):
        return {"serviceId": self.service_id, "startCommand": "python --due-work",
                "cronSchedule": "6,36 * * * *", "latestDeployment": deployment}

    def deployment(self, identity, status):
        return {"id": identity, "status": status, "meta": {
            "cliMessage": "Structured RAW health exact commit " + self.expected,
            "skippedReason": "No changes to watched files"}}

    def test_follow_child_despite_stale_latest_parent(self):
        parent = self.deployment("parent", "FAILED")
        child = self.deployment("child", "SUCCESS")
        before = {"service_id": self.service_id, "start_command": "python --due-work",
                  "schedule_utc": "6,36 * * * *"}
        with patch.object(delivery, "read_deployment", return_value=child) as read:
            result = delivery.rollout_deployment(self.service(parent), before, "child", self.expected)
        self.assertEqual(result, child)
        read.assert_called_once_with("child", self.service_id, self.expected)

    def test_configuration_change_refused_while_tracking_child(self):
        before = {"service_id": self.service_id, "start_command": "different --due-work",
                  "schedule_utc": "6,36 * * * *"}
        with patch.object(delivery, "read_deployment") as read:
            with self.assertRaises(delivery.state.VerificationError):
                delivery.rollout_deployment(self.service({}), before, "child", self.expected)
        read.assert_not_called()

    def test_main_skipped_parent_redeploys_once_and_receipts_successful_child(self):
        row = {"name": self.name, "service_id": self.service_id, "recovery_deployment_id": "old"}
        parent = self.deployment("parent", "SKIPPED")
        child = self.deployment("child", "SUCCESS")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in ("services/api/app/services", "services/yuyutei_collector/yuyutei_collector"):
                (root / path).mkdir(parents=True)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"target": "staging", "classification": "AMBER",
                                           "deployment_verification": {"collector_services": [row]}}))
            output = root / "receipt.json"
            def upload(*args):
                for marker in delivery.build_markers([row]):
                    self.assertEqual(marker.read_text(), "REVISION = " + repr(self.expected) + "\n")
            with patch.object(delivery.state, "ROOT", root), \
                 patch.object(delivery.subprocess, "check_output", return_value=self.expected), \
                 patch.object(delivery.state, "command_json", return_value={"commit": {"sha": self.expected}}), \
                 patch.object(delivery, "inspect", return_value={self.name: self.service(parent)}), \
                 patch.object(delivery, "upload", side_effect=upload), \
                 patch.object(delivery, "redeploy_uploaded", return_value=child) as redeploy, \
                 patch.object(delivery, "read_deployment", return_value=child) as read, \
                 patch.object(delivery.time, "sleep"):
                self.assertEqual(delivery.main(["--manifest", str(manifest), "--expected", self.expected,
                                                "--output", str(output)]), 0)
                redeploy.assert_called_once()
                read.assert_called_once_with("child", self.service_id, self.expected)
                self.assertEqual(json.loads(output.read_text())["deployments"][self.name]["deployment_id"], "child")
                self.assertTrue(all(not p.exists() for p in delivery.build_markers([row])))

    def test_non_redeployable_failure_refused_without_mutation(self):
        row = {"name": self.name, "service_id": self.service_id}
        failed = self.deployment("parent", "FAILED")
        with patch.object(delivery, "read_deployment", return_value={**failed, "canRedeploy": False}), \
             patch.object(delivery.state, "railway") as railway:
            with self.assertRaisesRegex(delivery.state.VerificationError, "cannot be redeployed"):
                delivery.redeploy_uploaded(row, failed, self.expected)
        railway.assert_not_called()


if __name__ == "__main__":
    unittest.main()
