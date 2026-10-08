import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import apply_staging_raw_dependency as delivery


class RawDependencyDeliveryTests(unittest.TestCase):
    def manifest(self, digest):
        return {
            "target": "staging",
            "classification": "AMBER",
            "deployment_verification": {
                "revision": delivery.REVISION,
                "raw_dependency_migration": {
                    "revision": delivery.REVISION,
                    "parent": delivery.PARENT,
                    "file": delivery.MIGRATION,
                    "sha256": digest,
                },
            },
        }

    def test_absent_selection_is_noop_without_external_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text("{}")
            with patch.object(delivery.state, "collect_live") as live:
                self.assertEqual(
                    delivery.main(
                        [
                            "--manifest",
                            str(path),
                            "--expected",
                            "unused",
                            "--output",
                            str(path.parent / "receipt.json"),
                        ]
                    ),
                    0,
                )
                live.assert_not_called()

    def test_only_checksum_pinned_additive_revision_is_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            migration = root / delivery.MIGRATION
            migration.parent.mkdir(parents=True)
            migration.write_text("mock reviewed migration")
            manifest = self.manifest(hashlib.sha256(migration.read_bytes()).hexdigest())
            with patch.object(delivery.state, "ROOT", root):
                self.assertEqual(
                    delivery.selection(manifest),
                    manifest["deployment_verification"]["raw_dependency_migration"],
                )
                for field, value in (
                    ("revision", "different"),
                    ("parent", "different"),
                    ("file", "other.py"),
                    ("sha256", "0" * 64),
                ):
                    with self.subTest(field=field):
                        bad = json.loads(json.dumps(manifest))
                        bad["deployment_verification"]["raw_dependency_migration"][
                            field
                        ] = value
                        with self.assertRaises(delivery.state.VerificationError):
                            delivery.selection(bad)
                for field, value in (
                    ("target", "production"),
                    ("classification", "GREEN"),
                ):
                    bad = dict(manifest, **{field: value})
                    with self.assertRaises(delivery.state.VerificationError):
                        delivery.selection(bad)

    def test_live_enablement_and_wrong_environment_refused_without_mutation(self):
        good = {
            "APP_ENV": "staging",
            "RAILWAY_ENVIRONMENT_ID": delivery.state.ENVIRONMENT,
        }
        for change in (
            {"RAW_DICTIONARY_STORAGE_ENABLED": "true"},
            {"APP_ENV": "production"},
            {"RAILWAY_ENVIRONMENT_ID": "other"},
        ):
            with self.subTest(change=change), patch.object(
                delivery.state, "command_json", return_value=dict(good, **change)
            ):
                with self.assertRaises(delivery.state.VerificationError):
                    delivery.require_writers_off("mock-existing-staging-service")

    def test_index_transition_is_independently_allowlisted_and_checksum_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            migration = root / delivery.INDEX_MIGRATION
            migration.parent.mkdir(parents=True)
            migration.write_text("mock additive indexes only")
            requested = {
                "revision": delivery.INDEX_REVISION,
                "parent": delivery.REVISION,
                "file": delivery.INDEX_MIGRATION,
                "sha256": hashlib.sha256(migration.read_bytes()).hexdigest(),
            }
            manifest = self.manifest(requested["sha256"])
            manifest["deployment_verification"] = {
                "revision": delivery.INDEX_REVISION,
                "raw_dependency_migration": requested,
            }
            with patch.object(delivery.state, "ROOT", root):
                self.assertEqual(delivery.selection(manifest), requested)
                for field, value in (
                    ("parent", delivery.PARENT),
                    ("revision", "abcdef012345"),
                    ("file", delivery.MIGRATION),
                    ("sha256", "0" * 64),
                ):
                    bad = json.loads(json.dumps(manifest))
                    bad["deployment_verification"]["raw_dependency_migration"][
                        field
                    ] = value
                    with self.subTest(field=field), self.assertRaises(
                        delivery.state.VerificationError
                    ):
                        delivery.selection(bad)


if __name__ == "__main__":
    unittest.main()
