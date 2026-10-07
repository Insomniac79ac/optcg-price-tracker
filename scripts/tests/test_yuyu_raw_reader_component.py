import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_yuyu_raw_reader_component as check


class ReaderAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.head = "a" * 40
        services = []
        runs = []
        for shard in range(9):
            name = f"yuyutei-collector-shard-{shard}" + ("-v2" if shard == 4 else "")
            services.append(
                {
                    "name": name,
                    "status": "SUCCESS",
                    "reported_sha": self.head,
                    "deployment_id": f"actual-{shard}",
                    "due_work_configured": True,
                    "schedule_utc": f"{shard*3},{shard*3+30} * * * *",
                }
            )
            runs.append(
                {
                    "identity": {
                        "service": name,
                        "revision": self.head,
                        "deployment_id": f"actual-{shard}",
                        "finished_at": "2026-10-07T13:00:00Z",
                    },
                    "exit": {"terminal_state": "completed"},
                    "work": {"max_work": 16},
                    "safety": dict.fromkeys(
                        (
                            "claims_remaining",
                            "expired_claims",
                            "reservations_remaining",
                            "reservation_overruns",
                            "duplicate_requests",
                            "wrong_shard",
                        ),
                        0,
                    ),
                    "failure": dict.fromkeys(("http_403", "http_429", "challenge"), 0),
                }
            )
        self.live = {
            "mode": "live",
            "repository": {"sha": self.head},
            "railway": {"services": services},
            "database": {"operational_runs": runs},
        }

    def test_all_nine_actual_ordinary_components_required(self):
        r = check.verify(self.live, self.head)
        self.assertEqual(len(r["actual_natural_reader_components"]), 9)
        self.assertFalse(r["encoded_writes_enabled"])

    def test_old_or_missing_receipt_waits_without_source_invocation(self):
        for mutate in (
            lambda e: e["database"]["operational_runs"].pop(),
            lambda e: e["database"]["operational_runs"][0]["identity"].update(
                revision="b" * 40
            ),
            lambda e: e["database"]["operational_runs"][0]["identity"].update(
                deployment_id="old"
            ),
        ):
            live = copy.deepcopy(self.live)
            mutate(live)
            with self.assertRaises(check.AdoptionPending):
                check.verify(live, self.head)

    def test_changed_routing_schedule_denial_or_ownership_refuses(self):
        for mutate in (
            lambda e: e["railway"]["services"][0].update(schedule_utc="*/5 * * * *"),
            lambda e: e["railway"]["services"][0].update(
                name="yuyutei-collector-shard-1"
            ),
            lambda e: e["database"]["operational_runs"][0]["work"].update(max_work=24),
            lambda e: e["database"]["operational_runs"][0]["failure"].update(
                http_429=1
            ),
            lambda e: e["database"]["operational_runs"][0]["safety"].update(
                wrong_shard=1
            ),
            lambda e: e["database"]["operational_runs"][0]["safety"].update(
                reservations_remaining=1
            ),
        ):
            live = copy.deepcopy(self.live)
            mutate(live)
            with self.assertRaises(check.state.VerificationError):
                check.verify(live, self.head)


if __name__ == "__main__":
    unittest.main()
