"""Offline regression coverage for fail-closed state collection and publication."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_staging_state as generator
import yaml


def fixture():
    recorded = json.loads(
        (ROOT / "docs/agent/evidence/2026-10-04-staging.json").read_text()
    )
    return {
        "environment": "staging",
        "mode": "fixture",
        "collected_at": "2026-10-04T08:42:38+00:00",
        "database": recorded["database"],
        "repository": {
            "name": generator.REPOSITORY,
            "branch": "staging",
            "sha": "a" * 40,
        },
        "railway": {
            "project_id": generator.PROJECT,
            "environment_id": generator.ENVIRONMENT,
            "services": [
                {
                    "name": "snkrdunk-collector",
                    "service_id": "test-id",
                    "due_work_configured": True,
                    "schedule_utc": "27,57 * * * *",
                    "deployment_id": "test-deployment",
                    "status": "SUCCESS",
                    "git_sha": "a" * 40,
                    "reported_sha": "unknown",
                }
            ],
        },
        "frontend": {
            "project_id": generator.VERCEL,
            "deployment_id": "dpl_test",
            "status": "READY",
            "sha": "b" * 40,
        },
        "errors": [],
    }


class StateTests(unittest.TestCase):
    def test_snapshot_keeps_eligibility_distinct_from_health(self):
        state = generator.build_state(generator.sanitize(fixture()))
        self.assertEqual(state["coverage"]["canonical_variants"], 4316)
        self.assertEqual(state["coverage"]["one_or_more_sources_pct"], 52.2243)
        self.assertEqual(state["snkrdunk"]["quarantined_identity"], 22)
        self.assertEqual(state["freshness"]["deadline_compliance_status"], "not_met")
        self.assertEqual(
            state["freshness"]["by_source"]["snkrdunk"]["price_older_than_24h"], 1
        )
        self.assertEqual(
            state["coverage"]["duplicate_active_exact_print_source_groups"], 0
        )
        self.assertEqual(state["features"]["psa10"]["live_activation"], "unknown")
        self.assertFalse(any(state["hard_invariants"].values()))

    def test_clean_instant_does_not_claim_sustained_compliance(self):
        evidence = fixture()
        for row in evidence["database"]["freshness"]:
            row["never_successfully_checked"] = row["check_older_than_24h"] = 0
        state = generator.build_state(generator.sanitize(evidence))
        self.assertEqual(state["freshness"]["deadline_compliance_status"], "unknown")

    def test_discovery_and_validation_are_not_confused(self):
        state = generator.build_state(generator.sanitize(fixture()))
        self.assertEqual(state["yuyu"]["discovery"]["attempts_24h"], 66)
        self.assertEqual(state["features"]["discovery"]["snkrdunk"], "unknown")

    def test_changed_counts_are_derived_not_copied_from_baseline(self):
        evidence = fixture()
        counts = evidence["database"]["coverage"][0]
        counts.update(canonical_variants=4320, zero_sources=2066)
        state = generator.build_state(generator.sanitize(evidence))
        self.assertEqual(
            state["coverage"]["one_or_more_sources_pct"], round(2254 / 4320 * 100, 4)
        )

    def test_work_counts_sum_across_policy_versions(self):
        evidence = fixture()
        evidence["database"]["work"] = [
            {
                "name": "yuyutei",
                "kind": "refresh",
                "state": "pending",
                "policy_version": version,
                "count": count,
            }
            for version, count in [("v1", 5), ("v2", 8)]
        ]
        state = generator.build_state(generator.sanitize(evidence))
        self.assertEqual(state["yuyu"]["due_work"]["pending"], 13)

    def test_wrong_live_environment_refused_before_credentials(self):
        response = {
            "id": generator.PROJECT,
            "environments": {
                "edges": [
                    {
                        "node": {
                            "id": generator.ENVIRONMENT,
                            "name": "production",
                            "projectId": generator.PROJECT,
                        }
                    }
                ]
            },
        }
        with patch.object(
            generator, "command_json", return_value=response
        ) as command, patch.object(generator, "database_snapshot") as database:
            with self.assertRaises(generator.VerificationError):
                generator.collect_live()
            database.assert_not_called()
            command.assert_called_once()

    def test_atomic_publication_failure_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot.yaml"
            output.write_text("old snapshot")
            real_replace = generator.os.replace

            def fail_snapshot(source, destination):
                if destination == output:
                    raise OSError("disk failure")
                return real_replace(source, destination)

            with patch.object(generator.os, "replace", side_effect=fail_snapshot):
                with self.assertRaises(OSError):
                    generator.write_snapshot(fixture(), output)
            self.assertEqual(output.read_text(), "old snapshot")
            self.assertEqual(list(output.parent.glob(".agent-state-*")), [])

    def test_bad_arithmetic_refuses_publication(self):
        evidence = fixture()
        evidence["database"]["coverage"][0]["zero_sources"] += 1
        with self.assertRaises(generator.VerificationError):
            generator.build_state(generator.sanitize(evidence))

    def test_production_and_unverified_database_refused(self):
        for mutate in [
            lambda e: e.update(environment="production"),
            lambda e: e["database"]["fingerprint"][0].update(ok=False),
            lambda e: e["database"]["as_of"][0].update(read_only="off"),
        ]:
            evidence = fixture()
            mutate(evidence)
            with self.assertRaises(generator.VerificationError):
                generator.sanitize(evidence)

    def test_cli_production_refused_before_any_io(self):
        with patch.object(
            generator, "collect_live"
        ) as collect, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                generator.main(["--live", "--environment", "production"])
            collect.assert_not_called()

    def test_failed_verification_preserves_last_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "state.yaml"
            output.write_text("old snapshot")
            with patch.object(
                generator,
                "collect_live",
                side_effect=generator.VerificationError("bad fingerprint"),
            ), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(generator.main(["--live", "--output", str(output)]), 1)
            self.assertEqual(output.read_text(), "old snapshot")
            self.assertFalse((output.parent / "evidence").exists())

    def test_fixture_cannot_replace_canonical_state(self):
        with self.assertRaisesRegex(generator.VerificationError, "Fixture replay"):
            generator.write_snapshot(fixture(), generator.CANONICAL_OUTPUT)

    def test_secret_fields_are_never_persisted(self):
        evidence = fixture()
        evidence["token"] = "SECRET-MARKER"
        evidence["database"]["budgets"][0]["pause_reason"] = "SECRET-MARKER"
        evidence["railway"]["services"][0]["command"] = "SECRET-MARKER"
        evidence["frontend"]["env"] = {"password": "SECRET-MARKER"}
        self.assertNotIn("SECRET-MARKER", json.dumps(generator.sanitize(evidence)))

    def test_replay_retains_identity_quarantine_and_evidence_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot.yaml"
            state = generator.write_snapshot(fixture(), output)
            artifact = output.parent / state["evidence"]["artifact"]
            clean = json.loads(artifact.read_text())
            self.assertEqual(generator.sanitize(clean), clean)
            replay = generator.write_snapshot(clean, output)
            self.assertEqual(replay, state)
            self.assertEqual(yaml.safe_load(output.read_text()), state)
            self.assertEqual(state["snkrdunk"]["quarantined_identity"], 22)

    def test_unavailable_frontend_is_unknown_and_reported(self):
        evidence = fixture()
        evidence["frontend"] = "unknown"
        evidence["errors"] = ["frontend_metadata_unavailable"]
        state = generator.build_state(generator.sanitize(evidence))
        self.assertEqual(state["staging"]["frontend"], "unknown")
        self.assertIn(
            "frontend_metadata_unavailable", [b["id"] for b in state["blockers"]]
        )

    def test_integrity_conflicts_are_visible_not_repaired(self):
        evidence = fixture()
        evidence["database"]["market_value"][0]["intentional_gap_rows"] = 1
        evidence["database"]["duplicate_detail"].append({"card_print_id": 42})
        state = generator.build_state(generator.sanitize(evidence))
        blockers = [b["id"] for b in state["blockers"]]
        self.assertIn("intentional-history-gap-populated", blockers)
        self.assertIn("duplicate-active-exact-mapping", blockers)
        self.assertIn("deployment-provenance-divergence", blockers)

    def test_query_file_contains_only_expected_reads(self):
        queries = generator.load_queries()
        self.assertEqual(len(queries), 16)
        self.assertIn("coverage", queries)
        for query in queries.values():
            self.assertTrue(query.strip().lower().startswith(("select ", "with ")))
            self.assertNotIn(";", query)


if __name__ == "__main__":
    unittest.main()
