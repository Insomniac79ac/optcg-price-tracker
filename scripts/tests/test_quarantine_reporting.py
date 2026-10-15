"""Quarantined (blocked) work is its own category, outside overdue and deadline compliance.

Owner decision 2026-10-14. Offline fixtures only; no live reads.
"""

import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "services/api"), str(ROOT / "scripts")]
from app.services import operational_health as health
from app.services.operational_health_sql import ELIGIBLE
import generate_staging_state as generator
import quarantine_reporting as quarantine
from test_generate_staging_state import fixture
from test_operational_health import healthy

NOW = "2026-10-04T08:02:00+00:00"
BUDGET = {
    "name": "snkrdunk", "enabled": True, "request_limit": 3100, "window_seconds": 1800,
    "window_started_at": "2026-10-04T08:00:00+00:00", "used_requests": 10, "reserved_requests": 0,
    "paused_until": None, "permanent_pause": False, "open_reservations": 0, "reservation_mismatch": False,
}


def items(n, *, since="2026-10-02T15:54:46+00:00", checked=None):
    return [{"source": "snkrdunk", "shard": None, "checked_at": checked, "since": since} for _ in range(n)]


def due(eligible=353, overdue=0, quarantined=0, never=0):
    return [dict(source="snkrdunk", shard=None, eligible=eligible, due=overdue, overdue=overdue,
                 quarantined=quarantined, never_checked=never, over_24h=overdue - never, between_23_24h=0)]


def run(misses=0, never=0):
    r = healthy("snkrdunk")
    r["freshness"].update(deadline_misses=misses, never_checked=never)
    return r


def snkr(result):
    return result["snkrdunk"]


class QuarantineHealthTests(unittest.TestCase):
    def aggregate(self, rows, runs, listed):
        return quarantine.aggregate(health, rows, runs, [BUDGET], NOW, listed)

    def test_quarantined_items_are_not_overdue(self):
        listed = items(22) + items(44, checked="2026-10-01T00:00:00+00:00")
        result = self.aggregate(due(overdue=66, quarantined=66, never=22), [run(66, 22)], listed)
        self.assertEqual(snkr(result)["status"], "HEALTHY")
        self.assertNotIn("due_work_deficit", snkr(result)["reasons"])
        self.assertEqual(snkr(result)["due_work"]["overdue"], 0)
        self.assertEqual(result["raw_due_work"]["deadline_misses"], 0)
        self.assertNotEqual(snkr(result)["deadline_compliance"], "not_met")

    def test_count_and_oldest_age_are_visible(self):
        listed = items(22) + items(44, checked="2026-10-01T00:00:00+00:00", since="2026-10-03T00:00:00+00:00")
        result = self.aggregate(due(overdue=66, quarantined=66, never=22), [run(66, 22)], listed)
        q = snkr(result)["quarantine"]
        self.assertEqual((q["count"], q["overdue"], q["never_checked"]), (66, 66, 22))
        self.assertEqual(q["oldest_blocked_since"], "2026-10-02T15:54:46+00:00")
        self.assertEqual(q["oldest_blocked_age_hours"], 40.1)
        self.assertEqual(q["oldest_successful_check_age_hours"], 80.0)
        self.assertEqual(snkr(result)["identity_quarantine"], 66)
        self.assertEqual(snkr(result)["due_work"]["quarantined"], 66)
        self.assertEqual(result["raw_due_work"]["quarantine"]["count"], 66)

    def test_zero_quarantine_is_still_reported(self):
        result = self.aggregate(due(), [run()], [])
        q = result["yuyu"]["quarantine"]
        self.assertEqual((q["count"], q["oldest_blocked_since"], q["oldest_blocked_age_hours"]), (0, None, None))
        self.assertEqual(snkr(result)["status"], "HEALTHY")

    def test_real_overdue_work_still_fails(self):
        # 66 quarantined plus 4 actionable items past 24 h.
        result = self.aggregate(due(overdue=70, quarantined=66, never=22), [run(70, 22)], items(22) + items(44, checked="2026-10-01T00:00:00+00:00"))
        self.assertEqual(snkr(result)["status"], "DEGRADED")
        self.assertIn("due_work_deficit", snkr(result)["reasons"])
        self.assertIn("deadline_misses", snkr(result)["reasons"])
        self.assertEqual(snkr(result)["due_work"]["overdue"], 4)
        self.assertEqual(snkr(result)["deadline_compliance"], "not_met")
        self.assertEqual(result["raw_due_work"]["deadline_misses"], 4)

    def test_run_keeps_items_blocked_after_it_started(self):
        # Blocked only after the run began: the run's miss may have been real; keep it.
        late = items(1, since="2026-10-04T08:00:30+00:00")
        result = self.aggregate(due(overdue=1, quarantined=1, never=1), [run(1, 1)], late)
        self.assertEqual(snkr(result)["due_work"]["overdue"], 0)
        self.assertEqual(snkr(result)["status"], "DEGRADED")
        self.assertIn("deadline_misses", snkr(result)["reasons"])

    def test_run_keeps_items_not_yet_overdue_at_its_start(self):
        fresh = items(1, checked="2026-10-03T12:00:00+00:00")  # 20 h old at the run start
        adjusted = quarantine.actionable_run(run(1, 0), quarantine._items(fresh))
        self.assertEqual(adjusted["freshness"]["deadline_misses"], 1)

    def test_list_disagreeing_with_authoritative_count_excludes_nothing(self):
        result = self.aggregate(due(overdue=66, quarantined=66, never=22), [run(66, 22)], items(65))
        self.assertEqual(snkr(result)["status"], "DEGRADED")
        self.assertEqual(snkr(result)["due_work"]["overdue"], 66)
        self.assertEqual(snkr(result)["quarantine"]["reporting"], "inconsistent; not excluded")

    def test_older_evidence_without_the_list_keeps_strict_reporting(self):
        result = self.aggregate(due(overdue=66, quarantined=66, never=22), [run(66, 22)], None)
        self.assertEqual(snkr(result)["status"], "DEGRADED")
        self.assertEqual(snkr(result)["quarantine"], {"count": 66, "reporting": "not_reported"})

    def test_inputs_are_not_mutated(self):
        rows, runs, listed = due(overdue=66, quarantined=66, never=22), [run(66, 22)], items(66)
        before = copy.deepcopy((rows, runs, listed))
        self.aggregate(rows, runs, listed)
        self.assertEqual((rows, runs, listed), before)

    def test_query_uses_the_shared_eligible_population_read_only(self):
        sql = quarantine.QUARANTINE_SQL
        self.assertIn(ELIGIBLE, sql)
        self.assertTrue(sql.lstrip().lower().startswith("with "))
        self.assertIn("e.state='blocked'", sql)
        self.assertNotIn(";", sql)


class QuarantineFreshnessTests(unittest.TestCase):
    ROW = {"name": "snkrdunk", "total": 353, "never_successfully_checked": 22, "check_older_than_24h": 44,
           "price_older_than_24h": 4, "no_listing": 278}

    def row(self, **extra):
        return self.ROW | {"quarantined": 66, "quarantined_never_successfully_checked": 22,
                           "quarantined_check_older_than_24h": 44,
                           "quarantined_oldest_since": "2026-10-02T15:54:46+00:00"} | extra

    def test_only_quarantined_misses_meet_no_deficit(self):
        out = quarantine.freshness([self.row()], NOW)
        self.assertFalse(quarantine.deficit(out))
        q = out["snkrdunk"]["quarantine"]
        self.assertEqual((q["count"], q["oldest_blocked_age_hours"]), (66, 40.1))

    def test_actionable_miss_is_still_a_deficit(self):
        out = quarantine.freshness([self.row(check_older_than_24h=45)], NOW)
        self.assertTrue(quarantine.deficit(out))
        self.assertEqual(out["snkrdunk"]["actionable_check_older_than_24h"], 1)

    def test_older_rows_keep_the_strict_meaning(self):
        old = self.ROW | {k: None for k in quarantine.QUARANTINE_COLUMNS}  # sanitize fills absent fields
        out = quarantine.freshness([old], NOW)
        self.assertTrue(quarantine.deficit(out))
        self.assertNotIn("quarantine", out["snkrdunk"])
        self.assertNotIn("quarantined", out["snkrdunk"])


class QuarantineStateTests(unittest.TestCase):
    def evidence(self, older_than_24h):
        evidence = fixture()
        db = evidence["database"]
        db["freshness"] = [
            {"name": "snkrdunk", "total": 353, "never_successfully_checked": 22,
             "check_older_than_24h": older_than_24h, "price_older_than_24h": 0, "no_listing": 0,
             "quarantined": 66, "quarantined_never_successfully_checked": 22,
             "quarantined_check_older_than_24h": 44, "quarantined_oldest_since": "2026-10-02T15:54:46+00:00"},
            {"name": "yuyutei", "total": 2619, "never_successfully_checked": 0, "check_older_than_24h": 0,
             "price_older_than_24h": 0, "no_listing": 0, "quarantined": 0,
             "quarantined_never_successfully_checked": 0, "quarantined_check_older_than_24h": 0,
             "quarantined_oldest_since": None},
        ]
        db["quarantined_work"] = []
        return evidence

    def build(self, evidence):
        return generator.build_state(generator.sanitize(evidence))

    def test_quarantine_replaces_the_deadline_blocker_and_stays_visible(self):
        state = self.build(self.evidence(44))
        ids = [b["id"] for b in state["blockers"]]
        self.assertNotIn("freshness-deadline-deficit", ids)
        blocker = next(b for b in state["blockers"] if b["id"] == "quarantined-refresh-work")
        self.assertEqual((blocker["count"], blocker["oldest_blocked_since"]), (66, "2026-10-02T15:54:46+00:00"))
        self.assertNotEqual(state["freshness"]["deadline_compliance_status"], "not_met")
        self.assertEqual(state["freshness"]["by_source"]["snkrdunk"]["quarantine"]["count"], 66)

    def test_actionable_miss_keeps_the_deadline_blocker(self):
        state = self.build(self.evidence(45))
        self.assertIn("freshness-deadline-deficit", [b["id"] for b in state["blockers"]])
        self.assertEqual(state["freshness"]["deadline_compliance_status"], "not_met")

    def test_sanitize_keeps_only_item_fields(self):
        evidence = self.evidence(44)
        evidence["database"]["quarantined_work"] = [
            {"source": "snkrdunk", "shard": None, "checked_at": None, "since": "2026-10-02T15:54:46+00:00",
             "secret": "must disappear"}]
        clean = generator.sanitize(evidence)
        self.assertEqual(set(clean["database"]["quarantined_work"][0]), set(quarantine.ITEM_FIELDS))


if __name__ == "__main__":
    unittest.main()
