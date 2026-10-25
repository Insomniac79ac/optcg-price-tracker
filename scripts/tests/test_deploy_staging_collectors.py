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
OTHER_IDS = {n: f"{i:08d}-1111-0000-0000-000000000000" for i, n in enumerate(sorted(delivery.NAMES))}
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
        # The trigger preflight reads every delivered collector, not only the requested three.
        others = {n: {"serviceId": OTHER_IDS[n]} for n in delivery.NAMES if n not in NAMES}
        return {**others, **{n: self.node(n) for n in NAMES}}

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

    def reupload(self, name, row, **kwargs):
        self.log.append(("reupload", name, row["commit"]))
        self.active[name] = "re-" + name
        return {"id": "re-" + name, "status": "SUCCESS",
                "meta": {"cliMessage": delivery.MARKER + row["commit"], "imageDigest": "sha256:" + "5" * 64}}

    def restore(self, name, values, commit, digest):
        self.log.append(("restore", name, commit, digest))
        assert values == FLAGS
        self.active[name] = "old-" + name
        return {"service": name}


NO_TRIGGER = {"triggers": [], "auto_deploy": False}
TRIGGER = {"triggers": [{"id": "t", "provider": "github", "repository": "Insomniac79ac/optcg-price-tracker",
                         "branch": "staging"}], "auto_deploy": False}


def run_main(fleet, tmp_path, monkeypatch, source=None, triggers=None, commit_present=True, reup=None):
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
    monkeypatch.setattr(delivery, "deploy_triggers", triggers or (lambda sid: NO_TRIGGER))
    monkeypatch.setattr(delivery.time, "sleep", lambda s: None)
    monkeypatch.setattr(cv, "read_variables", fleet.variables)
    monkeypatch.setattr(cv, "original_source",
                        source or (lambda node, commit, image, *a, **k: {"id": "src"}))
    monkeypatch.setattr(cv, "restore", fleet.restore)
    monkeypatch.setattr(delivery, "has_commit", lambda commit: commit_present)
    monkeypatch.setattr(delivery, "reupload", reup or fleet.reupload)
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


def no_source(*a, **k):
    raise delivery.state.VerificationError(delivery.NO_REDEPLOYABLE)


def test_no_redeployable_image_falls_back_to_reupload_of_the_same_commit(tmp_path, monkeypatch):
    fleet = Fleet(fail_on="yuyutei-collector-shard-1")
    monkeypatch.setattr(delivery, "inspect", fleet.inspect)
    try:
        run_main(fleet, tmp_path, monkeypatch, source=no_source)
    except delivery.state.VerificationError as error:
        assert "every released collector restored to its previous commit" in str(error)
    else:
        raise AssertionError("rollout must refuse")
    assert not [s for s in fleet.log if s[0] == "restore"]
    assert [s for s in fleet.log if s[0] == "reupload"] == [("reupload", n, OLD) for n in reversed(NAMES)]
    assert all(v.startswith("re-") for v in fleet.active.values())


def test_success_receipt_records_the_rollback_mode(tmp_path, monkeypatch):
    fleet = Fleet()
    code, output = run_main(fleet, tmp_path, monkeypatch, source=no_source)
    assert code == 0
    receipt = json.loads(output.read_text())
    assert {r["rollback"] for r in receipt["before"].values()} == {"reupload"}
    fleet = Fleet()
    code, output = run_main(fleet, tmp_path / "b", monkeypatch)
    assert {r["rollback"] for r in json.loads(output.read_text())["before"].values()} == {"redeploy"}


def test_missing_rollback_source_and_commit_refuses_before_any_upload(tmp_path, monkeypatch):
    fleet = Fleet()
    try:
        run_main(fleet, tmp_path, monkeypatch, source=no_source, commit_present=False)
    except delivery.state.VerificationError:
        pass
    else:
        raise AssertionError("must refuse without a proven rollback")
    assert not [s for s in fleet.log if s[0] == "upload"]


def test_github_trigger_on_any_collector_refuses_before_any_upload(tmp_path, monkeypatch):
    fleet = Fleet()
    shard_8 = OTHER_IDS["yuyutei-collector-shard-8"]  # not a requested collector
    try:
        run_main(fleet, tmp_path, monkeypatch,
                 triggers=lambda sid: TRIGGER if sid == shard_8 else NO_TRIGGER)
    except delivery.state.VerificationError as error:
        assert "yuyutei-collector-shard-8" in str(error)
    else:
        raise AssertionError("a collector GitHub trigger must refuse the release")
    assert fleet.log == []  # no slot wait, no upload, no restore
    assert not (tmp_path / "receipt.json").exists()


def test_auto_deploy_enabled_refuses_like_a_trigger(tmp_path, monkeypatch):
    fleet = Fleet()
    try:
        run_main(fleet, tmp_path, monkeypatch,
                 triggers=lambda sid: {"triggers": [], "auto_deploy": True})
    except delivery.state.VerificationError:
        pass
    else:
        raise AssertionError("auto-deploy enabled must refuse")
    assert fleet.log == []


def test_no_trigger_proceeds_and_receipt_records_the_check(tmp_path, monkeypatch):
    fleet = Fleet()
    checked = []
    code, output = run_main(fleet, tmp_path, monkeypatch,
                            triggers=lambda sid: checked.append(sid) or NO_TRIGGER)
    assert code == 0
    assert len(set(checked)) == len(delivery.NAMES) == 10  # all ten, not only the requested three
    receipt = json.loads(output.read_text())
    assert set(receipt["github_trigger_preflight"]) == delivery.NAMES


def test_missing_collector_or_unreadable_status_fails_closed():
    live = {n: {"serviceId": OTHER_IDS[n]} for n in delivery.NAMES}
    partial = dict(live)
    partial.pop("snkrdunk-collector")
    for args, read in ((partial, lambda sid: NO_TRIGGER),
                       (live, lambda sid: {"triggers": [], "auto_deploy": None})):
        try:
            delivery.refuse_github_triggers(args, read=read)
        except delivery.state.VerificationError:
            pass
        else:
            raise AssertionError("must fail closed")


def test_rollback_restore_never_runs_the_trigger_check(tmp_path, monkeypatch):
    fleet = Fleet(fail_on="yuyutei-collector-shard-1")
    calls = []

    def triggers(sid):
        calls.append(sid)
        return NO_TRIGGER

    try:
        run_main(fleet, tmp_path, monkeypatch, triggers=triggers)
    except delivery.state.VerificationError:
        pass
    assert len(calls) == len(delivery.NAMES)  # once, in the preflight; restores add none
    assert [s for s in fleet.log if s[0] == "restore"]


class Completed:
    def __init__(self, code=0):
        self.returncode, self.stdout, self.stderr = code, "", ""


def reupload_row():
    return {"commit": OLD, "service_id": IDS["snkrdunk-collector"], "deployment_id": "prev",
            "schedule_utc": "27,57 * * * *", "start_command": "python --due-work", "variables": dict(FLAGS)}


def test_reupload_uploads_the_previous_commit_from_a_worktree_with_markers(tmp_path, monkeypatch):
    monkeypatch.setattr(delivery.state, "ROOT", tmp_path)
    calls, seen = [], {}

    def run(cmd, cwd=None, **kwargs):
        calls.append((cmd[:3], str(cwd)))
        if cmd[:3] == ["git", "worktree", "add"]:
            tree = Path(cmd[4])
            for path in ("services/api/app/services", "services/snkrdunk_collector/snkrdunk_collector"):
                (tree / path).mkdir(parents=True)
        if cmd[:2] == ["railway", "up"]:
            seen["message"] = cmd[-1]
            seen["cwd"] = cwd
            seen["markers"] = sorted((p.read_text() for p in Path(cwd).rglob("*.py")))
        return Completed()

    states = iter([None, {"id": "re", "status": "BUILDING"}, {"id": "re", "status": "SUCCESS"}])
    result = delivery.reupload("snkrdunk-collector", reupload_row(), run=run, known={"prev"},
                               find=lambda row, commit, known: next(states),
                               clock=lambda: 0, sleep=lambda s: None)
    assert result["id"] == "re"
    assert seen["message"] == delivery.MARKER + OLD
    assert seen["markers"] == ["REVISION = " + repr(OLD) + "\n"] * 2
    assert [c[0] for c in calls] == [["git", "worktree", "add"], ["railway", "up", "--project"],
                                    ["git", "worktree", "remove"], ["git", "worktree", "prune"]]


def test_reupload_skipped_means_previous_must_still_be_active_and_failure_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(delivery.state, "ROOT", tmp_path)

    def run(cmd, cwd=None, **kwargs):
        if cmd[:3] == ["git", "worktree", "add"]:
            (Path(cmd[4]) / "services/api/app/services").mkdir(parents=True)
            (Path(cmd[4]) / "services/snkrdunk_collector/snkrdunk_collector").mkdir(parents=True)
        return Completed()

    monkeypatch.setattr(delivery, "read_deployment",
                        lambda i, s, c: {"id": i, "status": "SUCCESS", "meta": {}})
    skipped = {"id": "sk", "status": "SKIPPED", "meta": {"skippedReason": "No changes to watched files"}}
    out = delivery.reupload("snkrdunk-collector", reupload_row(), run=run, known=set(),
                            find=lambda *a: skipped, clock=lambda: 0, sleep=lambda s: None)
    assert out["id"] == "prev"
    try:
        delivery.reupload("snkrdunk-collector", reupload_row(), run=run, known=set(),
                          find=lambda *a: {"id": "sk", "status": "SKIPPED", "meta": {"skippedReason": "other"}},
                          clock=lambda: 0, sleep=lambda s: None)
    except delivery.state.VerificationError as error:
        assert "Unrecognized skipped" in str(error)
    else:
        raise AssertionError("unknown skip reason must refuse")
    for status in ("FAILED", "CRASHED"):
        try:
            delivery.reupload("snkrdunk-collector", reupload_row(), run=run, known=set(),
                              find=lambda *a: {"id": "x", "status": status}, clock=lambda: 0, sleep=lambda s: None)
        except delivery.state.VerificationError:
            pass
        else:
            raise AssertionError(status)

    def bad_checkout(cmd, cwd=None, **kwargs):
        return Completed(1 if cmd[:3] == ["git", "worktree", "add"] else 0)

    try:
        delivery.reupload("snkrdunk-collector", reupload_row(), run=bad_checkout, known=set(),
                          find=lambda *a: None, clock=lambda: 0, sleep=lambda s: None)
    except delivery.state.VerificationError as error:
        assert "checkout failed" in str(error)
    else:
        raise AssertionError("checkout failure must refuse")


def test_reupload_removes_and_prunes_the_worktree_when_upload_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(delivery.state, "ROOT", tmp_path)
    calls = []

    def run(cmd, cwd=None, **kwargs):
        calls.append(cmd[:3])
        if cmd[:3] == ["git", "worktree", "add"]:
            for path in ("services/api/app/services", "services/snkrdunk_collector/snkrdunk_collector"):
                (Path(cmd[4]) / path).mkdir(parents=True)
        return Completed(1 if cmd[:2] == ["railway", "up"] else 0)

    try:
        delivery.reupload("snkrdunk-collector", reupload_row(), run=run, known=set(),
                          find=lambda *a: None, clock=lambda: 0, sleep=lambda s: None)
    except delivery.state.VerificationError as error:
        assert "Rollback upload failed" in str(error)
    else:
        raise AssertionError("upload failure must refuse")
    assert calls[-2:] == [["git", "worktree", "remove"], ["git", "worktree", "prune"]]


def test_new_upload_ignores_deployments_that_existed_before(monkeypatch):
    rows = [{"id": "old-same-marker", "meta": {"cliMessage": delivery.MARKER + OLD}},
            {"id": "fresh", "meta": {"cliMessage": delivery.MARKER + OLD}}]
    monkeypatch.setattr(delivery.state, "command_json", lambda *a: rows)
    monkeypatch.setattr(delivery, "read_deployment", lambda i, s, c: {"id": i, "status": "SUCCESS"})
    row = {"service_id": IDS["snkrdunk-collector"]}
    assert delivery.new_upload(row, OLD, {"old-same-marker"})["id"] == "fresh"
    assert delivery.new_upload(row, OLD, {"old-same-marker", "fresh"}) is None


def test_rollback_after_a_skip_requires_the_previous_deployment_to_be_active(monkeypatch):
    import collector_variables as cv

    row = reupload_row()
    node = {"serviceId": row["service_id"], "cronSchedule": row["schedule_utc"],
            "startCommand": row["start_command"], "latestDeployment": {"id": "something-else"}}
    monkeypatch.setattr(delivery, "inspect", lambda: {"snkrdunk-collector": node})
    monkeypatch.setattr(delivery, "read_deployment", lambda i, s, c: {"id": i, "status": "SUCCESS", "meta": {}})
    monkeypatch.setattr(cv, "read_variables", lambda sid: dict(FLAGS))
    try:
        delivery.verify_reupload("snkrdunk-collector", row, {"id": "prev"})
    except delivery.state.VerificationError as error:
        assert "not the active deployment" in str(error)
    else:
        raise AssertionError("an inactive previous deployment must not count as rolled back")
    node["latestDeployment"] = {"id": "prev"}
    assert delivery.verify_reupload("snkrdunk-collector", row, {"id": "prev"})["mode"] == "reupload"


def test_mixed_rollback_modes_and_one_failure_does_not_stop_the_rest(monkeypatch):
    import collector_variables as cv

    before = {}
    for i, name in enumerate(NAMES):
        before[name] = {**reupload_row(), "service_id": IDS[name], "digest": "sha256:" + "1" * 64,
                        "rollback": "reupload" if i % 2 == 0 else "redeploy"}
    done = []
    monkeypatch.setattr(cv, "restore", lambda name, *a: done.append(("restore", name)) or {"service": name})

    def reup(name, row):
        done.append(("reupload", name))
        if name == "snkrdunk-collector":
            raise delivery.state.VerificationError("Rollback upload failed: " + name)
        return {"id": "re-" + name}

    monkeypatch.setattr(delivery, "verify_reupload", lambda name, row, dep: {"mode": "reupload"})
    results = delivery.roll_back(list(NAMES), before, slot=lambda *a: None, reup=reup)
    assert done == [("reupload", NAMES[2]), ("restore", NAMES[1]), ("reupload", NAMES[0])]
    assert results[NAMES[0]]["ok"] is False and results[NAMES[1]]["ok"] and results[NAMES[2]]["ok"]


def test_other_rollback_source_errors_refuse_instead_of_falling_back(tmp_path, monkeypatch):
    fleet = Fleet()

    def provider_error(*a, **k):
        raise delivery.state.VerificationError("Railway query failed (server)")

    try:
        run_main(fleet, tmp_path, monkeypatch, source=provider_error)
    except delivery.state.VerificationError as error:
        assert "Railway query failed" in str(error)
    else:
        raise AssertionError("a provider error must refuse, not switch to reupload")
    assert not [s for s in fleet.log if s[0] == "upload"]


def test_fallback_message_matches_collector_variables():
    import collector_variables as cv

    try:
        cv.original_source({"serviceId": "s", "latestDeployment": {}}, "c" * 40, "sha256:" + "1" * 64,
                           read=lambda *a: {}, listing=lambda sid: [])
    except delivery.state.VerificationError as error:
        assert str(error) == delivery.NO_REDEPLOYABLE
    else:
        raise AssertionError("original_source must refuse with no copies")


def test_reupload_nonce_changes_the_marker_but_not_the_revision(tmp_path, monkeypatch):
    monkeypatch.setattr(delivery.state, "ROOT", tmp_path)
    seen = {}

    def run(cmd, cwd=None, **kwargs):
        if cmd[:3] == ["git", "worktree", "add"]:
            for path in ("services/api/app/services", "services/snkrdunk_collector/snkrdunk_collector"):
                (Path(cmd[4]) / path).mkdir(parents=True)
        if cmd[:2] == ["railway", "up"]:
            seen["markers"] = sorted(p.read_text() for p in Path(cwd).rglob("*.py"))
        return Completed()

    delivery.reupload("snkrdunk-collector", reupload_row(), run=run, known=set(), nonce="K=v@T",
                      find=lambda *a: {"id": "n", "status": "SUCCESS"}, clock=lambda: 0, sleep=lambda s: None)
    assert seen["markers"] == ["REVISION = " + repr(OLD) + "\nUPLOAD = 'K=v@T'\n"] * 2


def test_has_commit_rejects_malformed_and_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(delivery.state, "ROOT", tmp_path)
    assert delivery.has_commit("not-a-sha") is False
    assert delivery.has_commit("a" * 40, run=lambda *a, **k: Completed(1)) is False
    assert delivery.has_commit("a" * 40, run=lambda *a, **k: Completed(0)) is True


if __name__ == "__main__":
    unittest.main()
