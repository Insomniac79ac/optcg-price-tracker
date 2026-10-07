import copy
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_snkr_published_discovery_component as check


class ComponentVerificationTests(unittest.TestCase):
    def setUp(self):
        self.head = "f" * 40
        self.receipt = {
            "identity": {
                "service": "snkrdunk-collector",
                "revision": check.SNKR,
                "deployment_id": "real-deployment",
                "finished_at": "2026-10-07T09:30:00Z",
            },
            "exit": {"terminal_state": "completed"},
            "safety": {
                "singleton": "held",
                **{
                    k: 0
                    for k in [
                        "claims_remaining",
                        "expired_claims",
                        "reservations_remaining",
                        "reservation_overruns",
                        "duplicate_requests",
                    ]
                },
            },
            "failure": {"http_403": 0, "http_429": 0, "challenge": 0},
        }
        self.live = {
            "mode": "live",
            "repository": {"sha": self.head},
            "railway": {
                "services": [
                    {
                        "name": "optcg-price-tracker",
                        "service_id": "api",
                        "git_sha": check.API,
                        "status": "SUCCESS",
                    },
                    {
                        "name": "snkrdunk-collector",
                        "service_id": check.SERVICE,
                        "deployment_id": "real-deployment",
                        "status": "SUCCESS",
                        "reported_sha": check.SNKR,
                        "schedule_utc": "27,57 * * * *",
                        "due_work_configured": True,
                    },
                ]
            },
            "database": {"operational_runs": [self.receipt]},
        }

    def test_unchanged_adopted_source_does_not_require_untriggered_api_build(self):
        result = check.verify(self.live, self.head)
        self.assertEqual(result["api_component"], check.API)
        self.assertEqual(result["snkr_component"], check.SNKR)

    def test_byte_continuity_fails_for_changed_runtime_inputs(self):
        check.continuity(
            check.API, self.head, check.API_PATHS, run=Mock(return_value="")
        )
        with self.assertRaises(check.state.VerificationError):
            check.continuity(
                check.API,
                self.head,
                check.API_PATHS,
                run=Mock(return_value="services/api/app/services/freshness_queue.py\n"),
            )

    def test_real_git_shallow_history_cannot_prove_retained_component_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            origin = root / "origin"
            origin.mkdir()

            def git(cwd, *args):
                return subprocess.check_output(
                    ["git", *args], cwd=cwd, text=True, stderr=subprocess.PIPE
                ).strip()

            git(origin, "init", "-q")
            git(origin, "config", "user.name", "Disposable test fixture")
            git(origin, "config", "user.email", "fixture@example.test")
            source = origin / "services/api/fixture.py"
            source.parent.mkdir(parents=True)
            source.write_text("unchanged API bytes\n")
            git(origin, "add", ".")
            git(origin, "commit", "-qm", "fixture baseline")
            baseline = git(origin, "rev-parse", "HEAD")
            (origin / "docs.txt").write_text("later documentation\n")
            git(origin, "add", ".")
            git(origin, "commit", "-qm", "fixture delivery")
            shallow = root / "shallow"
            git(root, "clone", "-q", "--depth=1", origin.as_uri(), str(shallow))
            head = git(shallow, "rev-parse", "HEAD")
            with patch.object(check.state, "ROOT", shallow):
                with self.assertRaises(subprocess.CalledProcessError):
                    check.continuity(baseline, head, check.API_PATHS)
                git(shallow, "fetch", "-q", "--unshallow")
                check.continuity(baseline, head, check.API_PATHS)
                source = shallow / "services/api/fixture.py"
                source.write_text("changed API bytes\n")
                git(shallow, "config", "user.name", "Disposable test fixture")
                git(shallow, "config", "user.email", "fixture@example.test")
                git(shallow, "add", ".")
                git(shallow, "commit", "-qm", "fixture changed API")
                with self.assertRaises(check.state.VerificationError):
                    check.continuity(
                        baseline, git(shallow, "rev-parse", "HEAD"), check.API_PATHS
                    )

    def test_deployment_marker_cannot_replace_actual_runtime_receipt(self):
        for field, value in [
            ("revision", check.API),
            ("deployment_id", "old"),
            ("finished_at", None),
        ]:
            live = copy.deepcopy(self.live)
            live["database"]["operational_runs"][0]["identity"][field] = value
            with self.assertRaises(check.state.VerificationError):
                check.verify(live, self.head)

    def test_identity_and_safety_changes_remain_fail_closed(self):
        for mutate in [
            lambda e: e.update(mode="fixture"),
            lambda e: e["repository"].update(sha="0" * 40),
            lambda e: e["railway"]["services"][0].update(git_sha="0" * 40),
            lambda e: e["database"]["operational_runs"][0]["safety"].update(
                duplicate_requests=1
            ),
            lambda e: e["database"]["operational_runs"][0]["failure"].update(
                http_403=1
            ),
        ]:
            live = copy.deepcopy(self.live)
            mutate(live)
            with self.assertRaises(check.state.VerificationError):
                check.verify(live, self.head)

    def test_new_component_requires_its_own_actual_receipt(self):
        live = copy.deepcopy(self.live)
        live["railway"]["services"][1]["reported_sha"] = self.head
        with self.assertRaises(check.AdoptionPending):
            check.verify(live, self.head, self.head)
        live["database"]["operational_runs"][0]["identity"]["revision"] = self.head
        self.assertEqual(
            check.verify(live, self.head, self.head)["snkr_component"], self.head
        )

    def test_wait_is_bounded_read_only_and_accepts_natural_adoption(self):
        old = copy.deepcopy(self.live)
        old["database"]["operational_runs"][0]["identity"]["deployment_id"] = "prior"
        sleep = Mock()
        collect = Mock(side_effect=[old, self.live])
        result = check.wait_for_adoption(
            self.head,
            check.SNKR,
            collect=collect,
            clock=Mock(side_effect=[0, 1]),
            sleep=sleep,
            timeout=40,
        )
        self.assertEqual(result["source_jobs_triggered"], 0)
        sleep.assert_called_once_with(30)
        with self.assertRaisesRegex(check.state.VerificationError, "deadline"):
            check.wait_for_adoption(
                self.head,
                check.SNKR,
                collect=Mock(return_value=old),
                clock=Mock(side_effect=[0, 2]),
                sleep=sleep,
                timeout=1,
            )

    def test_wait_never_retries_a_denial_or_wrong_deployment(self):
        for mutate in [
            lambda e: e["database"]["operational_runs"][0]["failure"].update(
                http_429=1
            ),
            lambda e: e["railway"]["services"][1].update(reported_sha=check.API),
        ]:
            live = copy.deepcopy(self.live)
            mutate(live)
            sleep = Mock()
            with self.assertRaises(check.state.VerificationError):
                check.wait_for_adoption(
                    self.head, check.SNKR, collect=Mock(return_value=live), sleep=sleep
                )
            sleep.assert_not_called()
