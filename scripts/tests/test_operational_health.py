"""Historical outcome-shaped fixtures; no live requests or invented run receipts."""

import copy
import json
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "services/api"), str(ROOT / "scripts")]
from app.services import operational_health as health
from check_raw_health import decision
from test_generate_staging_state import fixture


def healthy(source="yuyutei"):
    result = health.empty_summary()
    result["identity"].update(
        source=source,
        service=(
            "yuyutei-collector-shard-0" if source == "yuyutei" else "snkrdunk-collector"
        ),
        shard=0 if source == "yuyutei" else None,
        execution_id="fixture",
        started_at="2026-10-04T08:00:00+00:00",
        finished_at="2026-10-04T08:01:00+00:00",
        runtime_seconds=60,
        trigger="unknown",
    )
    result["work"].update(
        eligible=70,
        due=0,
        selected=70,
        claimed=70,
        attempted=70,
        listed=70,
        no_listing=0,
        promotional_hidden=0,
        accepted_observations=70,
        raw_snapshots=70,
        max_work=70,
    )
    result["failure"].update({k: 0 for k in result["failure"]})
    result["freshness"].update(
        successful_checks=70, deadline_misses=0, never_checked=0, retries=0, backoff=0
    )
    result["safety"].update(
        claims_remaining=0,
        expired_claims=0,
        reservations_remaining=0,
        reservation_overruns=0,
        singleton="held" if source == "snkrdunk" else "not_required",
        duplicate_requests=0,
        wrong_shard=0,
        identity_integrity="guarded",
        promotion_policy="guarded" if source == "yuyutei" else "not_applicable",
        production_impact=False,
    )
    result["exit"].update(terminal_state="completed")
    return result


class HealthTests(unittest.TestCase):
    def test_healthy_yuyu_and_silent_reporting(self):
        result = health.classify(healthy())
        self.assertEqual(result["status"], "HEALTHY")
        self.assertFalse(result["human_report"])
        self.assertEqual(result["action"], "silent_state_update")

    def test_promotional_hidden_is_not_a_failed_price(self):
        run = healthy()
        run["work"]["promotional_hidden"] = 70
        self.assertEqual(health.classify(run)["status"], "HEALTHY")
        run["safety"]["promotion_policy"] = "violated"
        self.assertEqual(health.classify(run)["status"], "BLOCKED")

    def test_no_listing_is_successful_without_refreshing_old_price(self):
        run = healthy("snkrdunk")
        run["work"].update(listed=0, no_listing=70, accepted_observations=0)
        self.assertEqual(health.classify(run)["status"], "HEALTHY")

    def test_bounded_defects_and_recovery(self):
        for field in ("transient", "parsing", "optional_resource", "identity"):
            run = healthy()
            run["failure"][field] = 1
            result = health.classify(run)
            self.assertEqual(result["status"], "DEGRADED", field)
            self.assertEqual(result["action"], "autonomous_fix_forward")
            run["failure"][field] = 0
            self.assertEqual(health.classify(run)["status"], "HEALTHY")

    def test_snkrdunk_70_of_70_failure_never_healthy(self):
        run = healthy("snkrdunk")
        run["failure"]["transient"] = 70
        run["work"].update(listed=0, accepted_observations=0)
        run["freshness"]["successful_checks"] = 0
        self.assertEqual(health.classify(run)["status"], "DEGRADED")

    def test_denials_challenge_and_integrity_stop_affected_path(self):
        for field in ("http_403", "http_429", "challenge"):
            run = healthy()
            run["failure"][field] = 1
            self.assertEqual(health.classify(run)["status"], "BLOCKED")
        for field in (
            "reservation_overruns",
            "duplicate_requests",
            "wrong_shard",
            "production_impact",
        ):
            run = healthy()
            run["safety"][field] = 1
            self.assertEqual(health.classify(run)["status"], "BLOCKED")
        run = healthy()
        run["safety"]["identity_integrity"] = "violated"
        self.assertEqual(health.classify(run)["status"], "BLOCKED")

    def test_settled_expiry_degraded_stuck_expiry_blocked(self):
        run = healthy()
        run["safety"]["expired_claims"] = 1
        self.assertEqual(health.classify(run)["status"], "DEGRADED")
        run["safety"]["claims_remaining"] = 1
        self.assertEqual(health.classify(run)["status"], "BLOCKED")

    def test_normal_retry_and_backoff_does_not_reset_deadlines(self):
        run = healthy()
        run["freshness"].update(retries=1, backoff=1, deadline_misses=1)
        result = health.classify(run)
        self.assertEqual(result["status"], "DEGRADED")
        self.assertIn("deadline_misses", result["reasons"])

    def test_unknown_evidence_cannot_produce_healthy(self):
        for section, field in [
            ("work", "claimed"),
            ("safety", "reservations_remaining"),
            ("freshness", "deadline_misses"),
        ]:
            run = healthy()
            run[section][field] = None
            self.assertEqual(health.classify(run)["status"], "DEGRADED")
        run = healthy()
        run["exit"]["terminal_state"] = "running"
        self.assertEqual(health.classify(run)["status"], "DEGRADED")
        self.assertIsNone(run["exit"]["exit_code"])
        self.assertIsNone(run["identity"]["scheduled_at"])
        self.assertEqual(run["identity"]["trigger"], "unknown")

    def test_healthy_in_progress_cycle_does_not_create_noise(self):
        done = healthy()
        started = healthy()
        started["identity"].update(
            execution_id="active",
            started_at="2026-10-04T08:02:00+00:00",
            finished_at=None,
        )
        started["exit"]["terminal_state"] = "running"
        started["work"]["runtime_limit_seconds"] = 1200
        rows = [{"source": "yuyutei", "shard": 0}]
        result = health.aggregate(
            rows,
            [done, started],
            [{"name": "yuyutei", "reservation_mismatch": False}],
            "2026-10-04T08:03:00+00:00",
        )
        self.assertEqual(result["yuyu"]["status"], "HEALTHY")
        self.assertEqual(len(result["yuyu"]["active_executions"]), 1)
        result = health.aggregate(
            rows, [done, started], [], "2026-10-04T09:00:00+00:00"
        )
        self.assertEqual(result["yuyu"]["status"], "DEGRADED")

    def test_json_schema_stays_in_sync(self):
        schema = json.loads(
            (ROOT / "docs/agent/raw-operational-run.schema.json").read_text()
        )
        run = healthy()
        self.assertEqual(set(schema["required"]), set(run))
        for section, fields in health.SECTIONS.items():
            self.assertEqual(
                set(schema["properties"][section]["required"]), set(fields)
            )
            self.assertFalse(schema["properties"][section]["additionalProperties"])

    def test_schema_rejects_negative_metrics_and_non_utc(self):
        run = healthy()
        run["work"]["claimed"] = -1
        with self.assertRaises(ValueError):
            health.validate(run)
        run = healthy()
        run["identity"]["started_at"] = "2026-10-04T08:00:00"
        with self.assertRaises(ValueError):
            health.validate(run)
        run = healthy()
        run["schema_version"] = 999
        with self.assertRaises(ValueError):
            health.validate(run)

    def test_allowlist_drops_untrusted_secrets(self):
        run = healthy()
        run["secret"] = "must disappear"
        run["work"]["password"] = "must disappear"
        self.assertNotIn("must disappear", json.dumps(health.sanitize(run)))

    def test_aggregate_quarantine_eligible_and_unknown_natural(self):
        run = healthy("snkrdunk")
        rows = [
            dict(
                source="snkrdunk",
                shard=None,
                eligible=353,
                due=22,
                overdue=22,
                quarantined=22,
                never_checked=22,
            )
        ]
        result = health.aggregate(rows, [run], [], "2026-10-04T08:02:00+00:00")
        self.assertEqual(result["snkrdunk"]["status"], "DEGRADED")
        self.assertEqual(result["snkrdunk"]["identity_quarantine"], 22)
        self.assertIsNone(result["snkrdunk"]["latest_natural_run"])
        self.assertEqual(result["target_hours"], 24)
        self.assertEqual(result["dispatch_due_hours"], 23)

    def test_latest_recovery_supersedes_own_service_not_other_shard(self):
        old = healthy()
        old["failure"]["http_403"] = 1
        recovered = healthy()
        recovered["identity"]["started_at"] = "2026-10-04T08:02:00+00:00"
        recovered["identity"]["finished_at"] = "2026-10-04T08:03:00+00:00"
        other = copy.deepcopy(old)
        other["identity"].update(service="yuyutei-collector-shard-1", shard=1)
        rows = [{"source": "yuyutei", "shard": 0}, {"source": "yuyutei", "shard": 1}]
        result = health.aggregate(
            rows, [old, recovered, other], [], "2026-10-04T08:03:00+00:00"
        )
        self.assertEqual(result["yuyu"]["status"], "BLOCKED")
        self.assertEqual(
            result["yuyu"]["blocked_shards"], ["yuyutei-collector-shard-1"]
        )

    def test_orphaned_source_reservation_blocks_safe_receipt(self):
        run = healthy("snkrdunk")
        rows = [{"source": "snkrdunk", "shard": None}]
        budget = [
            {
                "name": "snkrdunk",
                "request_limit": 3100,
                "used_requests": 0,
                "reserved_requests": 300,
                "open_reservations": 0,
                "reservation_mismatch": True,
            }
        ]
        result = health.aggregate(rows, [run], budget, "2026-10-04T08:03:00+00:00")
        self.assertEqual(result["snkrdunk"]["status"], "BLOCKED")
        self.assertIn(
            "orphaned_or_unaccounted_reservations", result["snkrdunk"]["reasons"]
        )

    def test_database_integrity_cannot_hide_behind_run_health(self):
        evidence = fixture()
        evidence["database"]["duplicate_active_exact_print_source_groups"] = 1
        result = decision(evidence)
        self.assertEqual(
            result["operational_health"]["raw_due_work"]["status"], "BLOCKED"
        )
        self.assertEqual(result["mission_actions"][0]["action"], "stop_affected_path")

    def test_state_contains_actionable_health_with_no_logs(self):
        result = decision(fixture())
        self.assertEqual(
            result["operational_health"]["raw_due_work"]["status"], "DEGRADED"
        )
        self.assertTrue(result["mission_actions"])
        self.assertFalse(result["mission_actions"][0]["requires_intermediate_approval"])
        self.assertFalse(result["production_accessed"])


class CollectorRolloutTests(unittest.TestCase):
    def test_selection_rejects_production_and_unknown_services(self):
        import deploy_staging_collectors as deploy

        row = {
            "name": "snkrdunk-collector",
            "service_id": "2d7ab69b-ec1f-4c66-8da1-9c8769a6d14a",
            "recovery_deployment_id": "retained",
        }
        manifest = {
            "target": "staging",
            "classification": "AMBER",
            "deployment_verification": {"collector_services": [row]},
        }
        self.assertEqual(deploy.selection(manifest), [row])
        manifest["target"] = "production"
        with self.assertRaises(deploy.state.VerificationError):
            deploy.selection(manifest)
        manifest["target"] = "staging"
        row["name"] = "new-or-production-service"
        with self.assertRaises(deploy.state.VerificationError):
            deploy.selection(manifest)

    def test_noncollector_mission_has_no_provider_effect(self):
        import deploy_staging_collectors as deploy

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "mission.json"
            manifest.write_text("{}")
            with patch.object(deploy, "inspect") as inspect, patch.object(
                deploy.subprocess, "run"
            ) as run:
                self.assertEqual(
                    deploy.main(
                        [
                            "--manifest",
                            str(manifest),
                            "--expected",
                            "a" * 40,
                            "--output",
                            str(root / "result.json"),
                        ]
                    ),
                    0,
                )
                inspect.assert_not_called()
                run.assert_not_called()

    def test_failed_upload_cleans_build_marker_and_writes_no_success(self):
        import deploy_staging_collectors as deploy

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "services/api/app/services").mkdir(parents=True)
            row = {
                "name": "snkrdunk-collector",
                "service_id": "2d7ab69b-ec1f-4c66-8da1-9c8769a6d14a",
                "recovery_deployment_id": "retained",
            }
            manifest = root / "mission.json"
            manifest.write_text(
                json.dumps(
                    {
                        "target": "staging",
                        "classification": "AMBER",
                        "deployment_verification": {"collector_services": [row]},
                    }
                )
            )
            live = {
                row["name"]: {
                    "serviceId": row["service_id"],
                    "startCommand": "python -m snkrdunk_collector.collect --due-work",
                    "cronSchedule": "27,57 * * * *",
                    "latestDeployment": {"id": "retained"},
                }
            }
            with patch.object(deploy.state, "ROOT", root), patch.object(
                deploy, "inspect", return_value=live
            ), patch.object(
                deploy.subprocess, "check_output", return_value="a" * 40
            ), patch.object(
                deploy.state, "command_json", return_value={"commit": {"sha": "a" * 40}}
            ), patch.object(
                deploy.subprocess,
                "run",
                return_value=Mock(returncode=1, stderr="sensitive must never print"),
            ):
                with self.assertRaisesRegex(
                    deploy.state.VerificationError,
                    "Staging collector upload failed: snkrdunk-collector",
                ):
                    deploy.main(
                        [
                            "--manifest",
                            str(manifest),
                            "--expected",
                            "a" * 40,
                            "--output",
                            str(root / "result.json"),
                        ]
                    )
            self.assertFalse(
                (root / "services/api/app/services/collector_build.py").exists()
            )
            self.assertFalse((root / "result.json").exists())

    def test_successful_rollout_receipt_hashes_provider_commands(self):
        import deploy_staging_collectors as deploy

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "services/api/app/services").mkdir(parents=True)
            row = {
                "name": "snkrdunk-collector",
                "service_id": "2d7ab69b-ec1f-4c66-8da1-9c8769a6d14a",
                "recovery_deployment_id": "retained",
            }
            manifest = root / "mission.json"
            manifest.write_text(
                json.dumps(
                    {
                        "target": "staging",
                        "classification": "AMBER",
                        "deployment_verification": {"collector_services": [row]},
                    }
                )
            )
            before = {
                row["name"]: {
                    "serviceId": row["service_id"],
                    "startCommand": "python --due-work provider-free-text",
                    "cronSchedule": "27,57 * * * *",
                    "latestDeployment": {"id": "retained"},
                }
            }
            after = copy.deepcopy(before)
            after[row["name"]]["latestDeployment"] = {
                "id": "new-deployment",
                "status": "SUCCESS",
                "meta": {
                    "cliMessage": "Structured RAW health exact commit " + "a" * 40
                },
            }
            with patch.object(deploy.state, "ROOT", root), patch.object(
                deploy, "inspect", side_effect=[before, after]
            ), patch.object(
                deploy.subprocess, "check_output", return_value="a" * 40
            ), patch.object(
                deploy.state, "command_json", return_value={"commit": {"sha": "a" * 40}}
            ), patch.object(
                deploy.subprocess, "run", return_value=Mock(returncode=0)
            ):
                self.assertEqual(
                    deploy.main(
                        [
                            "--manifest",
                            str(manifest),
                            "--expected",
                            "a" * 40,
                            "--output",
                            str(root / "result.json"),
                        ]
                    ),
                    0,
                )
            receipt = (root / "result.json").read_text()
            self.assertNotIn("provider-free-text", receipt)
            self.assertIn("start_command_sha256", receipt)
            self.assertFalse(
                (root / "services/api/app/services/collector_build.py").exists()
            )
