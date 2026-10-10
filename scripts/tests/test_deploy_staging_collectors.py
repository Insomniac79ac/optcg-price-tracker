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

    def test_non_redeployable_failure_refused_without_mutation(self):
        row = {"name": self.name, "service_id": self.service_id}
        failed = self.deployment("parent", "FAILED")
        with patch.object(delivery, "read_deployment", return_value={**failed, "canRedeploy": False}), \
             patch.object(delivery.state, "railway") as railway:
            with self.assertRaisesRegex(delivery.state.VerificationError, "cannot be redeployed"):
                delivery.redeploy_uploaded(row, failed, self.expected)
        railway.assert_not_called()




# --- Sequential rollout (2026-10-10, session 8) ---------------------------

from datetime import datetime, timezone

EXPECTED = "a" * 40
OLD = "c" * 40
NAMES = ["snkrdunk-collector", "yuyutei-collector-shard-0", "yuyutei-collector-shard-1"]
IDS = {n: f"{i:08d}-0000-0000-0000-000000000000" for i, n in enumerate(NAMES)}
FLAGS = {"RAW_DICTIONARY_STORAGE_ENABLED": "true", "RAW_DICTIONARY_STORAGE_MODE": "daily-v1",
         "APP_ENV": "staging"}


def at(minute, second=0):
    return datetime(2026, 10, 10, 8, minute, second, tzinfo=timezone.utc)


def test_cron_minutes_parses_only_plain_minute_lists():
    assert delivery.cron_minutes("6,36 * * * *") == [6, 36]
    for bad in ("*/5 * * * *", "6,36 * * * 1", "", None, "61 * * * *"):
        try:
            delivery.cron_minutes(bad)
        except delivery.state.VerificationError:
            continue
        raise AssertionError(bad)


def test_claim_prefix_maps_every_collector():
    assert delivery.claim_prefix("snkrdunk-collector") == "snkrdunk-due"
    assert delivery.claim_prefix("yuyutei-collector-shard-3") == "yuyutei-due-3"
    assert delivery.claim_prefix("yuyutei-collector-shard-4-v2") == "yuyutei-due-4"


def slot_outcome(minute, open_count=0):
    clock = iter(range(0, 10_000, 1))
    try:
        delivery.wait_for_slot("yuyutei-collector-shard-2", "6,36 * * * *",
                               now=lambda: at(minute), attempts=lambda prefix: open_count,
                               clock=lambda: next(clock) * 1000, sleep=lambda s: None)
        return True
    except delivery.state.VerificationError:
        return False


def test_slot_requires_gap_after_fire_before_next_and_no_open_attempt():
    assert slot_outcome(11)            # 5 min after :06, 25 before :36
    assert slot_outcome(28)            # 8 min before :36
    assert not slot_outcome(10)        # turn may still be running
    assert not slot_outcome(29)        # next fire too close for a build
    assert not slot_outcome(6)         # firing now
    assert not slot_outcome(15, open_count=1)  # its attempt is open


def test_forward_release_never_starts_where_it_could_reach_the_busy_window():
    for hour, allowed in ((6, True), (22, True), (23, False), (1, False), (2, False), (5, False)):
        try:
            delivery.outside_busy_window(datetime(2026, 10, 10, hour, 30, tzinfo=timezone.utc))
            assert allowed, hour
        except delivery.state.VerificationError:
            assert not allowed, hour


class Fleet:
    """Fake three-collector fleet recording every external action in order."""

    def __init__(self, fail_on=None, flag_drift_on=None):
        self.log = []
        self.fail_on = fail_on
        self.flag_drift_on = flag_drift_on
        self.active = {n: "old-" + n for n in NAMES}

    def node(self, name):
        latest = self.active[name]
        commit = EXPECTED if latest.startswith("new-") else OLD
        return {"serviceId": IDS[name], "startCommand": "python --due-work",
                "cronSchedule": "27,57 * * * *",
                "latestDeployment": {"id": latest, "status": "SUCCESS",
                                     "meta": {"cliMessage": delivery.MARKER + commit}}}

    def inspect(self):
        return {n: self.node(n) for n in NAMES}

    def read(self, identity, service_id, commit):
        return {"id": identity, "status": "SUCCESS", "canRedeploy": True,
                "meta": {"cliMessage": delivery.MARKER + commit,
                         "imageDigest": "sha256:" + ("9" if identity.startswith("new-") else "1") * 64}}

    def upload(self, row, expected):
        self.log.append(("upload", row["name"]))
        if row["name"] == self.fail_on:
            raise delivery.state.VerificationError("upload failed")
        self.active[row["name"]] = "new-" + row["name"]

    def slot(self, name, schedule, **kwargs):
        self.log.append(("slot", name))

    def variables(self, service_id):
        name = next(n for n, i in IDS.items() if i == service_id)
        if self.flag_drift_on == name and self.active[name].startswith("new-"):
            return {**FLAGS, "RAW_DICTIONARY_STORAGE_ENABLED": "false"}
        return dict(FLAGS)

    def restore(self, name, values, commit, digest):
        self.log.append(("restore", name, commit, digest))
        assert values == FLAGS
        self.active[name] = "old-" + name
        return {"service": name}


def run_main(fleet, tmp_path, monkeypatch, source=None):
    import collector_variables as cv

    for path in ("services/api/app/services", "services/yuyutei_collector/yuyutei_collector",
                 "services/snkrdunk_collector/snkrdunk_collector"):
        (tmp_path / path).mkdir(parents=True)
    rows = [{"name": n, "service_id": IDS[n], "recovery_deployment_id": "r"} for n in NAMES]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"target": "staging", "classification": "AMBER",
                                    "deployment_verification": {"collector_services": rows}}))
    output = tmp_path / "receipt.json"
    monkeypatch.setattr(delivery.state, "ROOT", tmp_path)
    monkeypatch.setattr(delivery.subprocess, "check_output", lambda *a, **k: EXPECTED)
    monkeypatch.setattr(delivery.state, "command_json", lambda *a: {"commit": {"sha": EXPECTED}})
    monkeypatch.setattr(delivery, "inspect", fleet.inspect)
    monkeypatch.setattr(delivery, "read_deployment", fleet.read)
    monkeypatch.setattr(delivery, "upload", fleet.upload)
    monkeypatch.setattr(delivery, "wait_for_slot", fleet.slot)
    monkeypatch.setattr(delivery, "outside_busy_window", lambda: None)
    monkeypatch.setattr(delivery.time, "sleep", lambda s: None)
    monkeypatch.setattr(cv, "read_variables", fleet.variables)
    monkeypatch.setattr(cv, "original_source",
                        source or (lambda node, commit, image, *a, **k: {"id": "src"}))
    monkeypatch.setattr(cv, "restore", fleet.restore)
    return delivery.main(["--manifest", str(manifest), "--expected", EXPECTED,
                          "--output", str(output)]), output


def test_rollout_is_one_collector_at_a_time_in_its_own_slot(tmp_path, monkeypatch):
    fleet = Fleet()
    code, output = run_main(fleet, tmp_path, monkeypatch)
    assert code == 0
    # Each collector's slot precedes its upload, and no upload interleaves.
    assert fleet.log == [step for n in NAMES for step in (("slot", n), ("upload", n))]
    receipt = json.loads(output.read_text())
    assert receipt["sequential"] is True
    assert receipt["before"]["snkrdunk-collector"]["commit"] == OLD
    assert receipt["before"]["snkrdunk-collector"]["image_digest"] == "sha256:" + "1" * 64
    assert all(d["image_digest"] == "sha256:" + "9" * 64 for d in receipt["deployments"].values())


def test_failure_restores_every_released_collector_newest_first(tmp_path, monkeypatch):
    fleet = Fleet(fail_on="yuyutei-collector-shard-1")
    try:
        run_main(fleet, tmp_path, monkeypatch)
    except delivery.state.VerificationError as error:
        assert "every released collector restored" in str(error)
    else:
        raise AssertionError("rollout must refuse")
    restores = [step for step in fleet.log if step[0] == "restore"]
    old_digest = "sha256:" + "1" * 64
    assert restores == [("restore", n, OLD, old_digest) for n in reversed(NAMES)]
    assert not (tmp_path / "receipt.json").exists()  # never a success receipt
    assert all(v.startswith("old-") for v in fleet.active.values())


def test_writer_flag_drift_after_release_rolls_back(tmp_path, monkeypatch):
    fleet = Fleet(flag_drift_on="yuyutei-collector-shard-0")
    try:
        run_main(fleet, tmp_path, monkeypatch)
    except delivery.state.VerificationError:
        pass
    else:
        raise AssertionError("flag drift must refuse")
    assert ("upload", "yuyutei-collector-shard-1") not in fleet.log
    assert [s[1] for s in fleet.log if s[0] == "restore"] == [
        "yuyutei-collector-shard-0", "snkrdunk-collector"]


def test_missing_rollback_source_refuses_before_any_upload(tmp_path, monkeypatch):
    fleet = Fleet()

    def no_source(*a, **k):
        raise delivery.state.VerificationError("No redeployable deployment")

    try:
        run_main(fleet, tmp_path, monkeypatch, source=no_source)
    except delivery.state.VerificationError:
        pass
    else:
        raise AssertionError("must refuse without a proven rollback")
    assert not [s for s in fleet.log if s[0] == "upload"]


if __name__ == "__main__":
    unittest.main()
