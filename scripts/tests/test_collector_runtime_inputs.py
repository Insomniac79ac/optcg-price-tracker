"""Collector continuity narrows services/api to the real import graph, never weaker."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collector_runtime_inputs as inputs
import verify_snkr_published_discovery_component as snkr
import verify_yuyu_raw_reader_component as yuyu

REPO = Path(__file__).resolve().parents[2]

FIXTURE = {
    "services/api/pyproject.toml": "[project]\nname = 'fixture'\n",
    "services/api/requirements.txt": "sqlalchemy\n",
    "services/api/Dockerfile": "FROM scratch\n",
    "services/api/app/__init__.py": "",
    "services/api/app/services/__init__.py": "",
    "services/api/app/services/used.py": (
        "def run():\n    from app.services.helper import value\n    return value\n"
    ),
    "services/api/app/services/helper.py": "value = 1\n",
    "services/api/app/services/unused.py": "value = 2\n",
    "services/api/app/services/evidence/data.json": "{}\n",
    "services/api/app/api/__init__.py": "",
    "services/api/app/api/routes.py": "from app.services import unused\n",
    "services/api/alembic/versions/rev.py": "revision = 'a'\n",
    "services/api/tests/test_api.py": "import app.api.routes\n",
    "packages/opcg_source_identity/src/opcg_source_identity/__init__.py": "",
    "services/snkrdunk_collector/snkrdunk_collector/__init__.py": "",
    "services/snkrdunk_collector/snkrdunk_collector/due.py": (
        "from app.services.used import run\n"
        "try:\n    from app.services.collector_build import REVISION\n"
        "except ImportError:\n    REVISION = None\n"
    ),
    "services/snkrdunk_collector/tests/test_due.py": "import app.api.routes\n",
    "services/yuyutei_collector/yuyutei_collector/__init__.py": "",
    "services/yuyutei_collector/yuyutei_collector/due.py": "from app.services import used\n",
    "deploy/railway/snkrdunk-collector.Dockerfile": "FROM scratch\n",
    "deploy/railway/yuyutei-collector.Dockerfile": "FROM scratch\n",
    "docs/readme.md": "docs\n",
}


class FixtureRepo:
    def __init__(self, root):
        self.root = root
        self.git("init", "-q")
        self.git("config", "user.name", "Disposable test fixture")
        self.git("config", "user.email", "fixture@example.test")
        # `git commit` otherwise spawns a detached `git maintenance run --auto`
        # that can still be writing .git/objects when TemporaryDirectory.cleanup
        # runs, failing rmtree with "Directory not empty".
        self.git("config", "maintenance.auto", "false")
        self.git("config", "gc.auto", "0")
        self.commit(FIXTURE)
        self.base = self.head()

    def git(self, *args):
        return subprocess.check_output(
            ["git", *args], cwd=self.root, text=True, stderr=subprocess.PIPE
        ).strip()

    def head(self):
        return self.git("rev-parse", "HEAD")

    def commit(self, files):
        for path, body in files.items():
            target = self.root / path
            if body is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture change")
        return self.head()


class CollectorRuntimeInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = FixtureRepo(Path(self.tmp.name))
        patcher = patch.object(inputs.state, "ROOT", self.repo.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def changed(self, files, collector="snkrdunk"):
        head = self.repo.commit(files)
        return inputs.changed_runtime_inputs(self.repo.base, head, collector)

    def assert_fails(self, files, collector="snkrdunk"):
        head = self.repo.commit(files)
        with self.assertRaises(inputs.state.VerificationError):
            snkr.collector_continuity(self.repo.base, head, collector)

    def assert_passes(self, files, collector="snkrdunk"):
        head = self.repo.commit(files)
        return snkr.collector_continuity(self.repo.base, head, collector)

    def test_import_graph_follows_function_local_and_transitive_imports(self):
        found = inputs.runtime_inputs(self.repo.base, "snkrdunk")
        self.assertEqual(
            found,
            {
                "services/api/app/__init__.py",
                "services/api/app/services/__init__.py",
                "services/api/app/services/used.py",
                "services/api/app/services/helper.py",
            },
        )
        # Collector tests are not executed by the installed image.
        self.assertNotIn("services/api/app/api/routes.py", found)

    def test_change_to_imported_module_fails_continuity(self):
        self.assert_fails({"services/api/app/services/used.py": "def run():\n    return 3\n"})

    def test_change_to_transitively_imported_module_fails_continuity(self):
        self.assert_fails({"services/api/app/services/helper.py": "value = 9\n"})

    def test_change_to_package_init_on_import_path_fails_continuity(self):
        self.assert_fails({"services/api/app/__init__.py": "flag = True\n"})

    def test_change_to_non_imported_api_module_passes(self):
        basis = self.assert_passes(
            {
                "services/api/app/services/unused.py": "value = 3\n",
                "services/api/app/api/routes.py": "routes = []\n",
                "services/api/alembic/versions/rev.py": "revision = 'b'\n",
                "services/api/tests/test_api.py": "x = 1\n",
                "services/api/Dockerfile": "FROM busybox\n",
            }
        )
        self.assertEqual(basis, "import-graph")

    def test_new_api_module_outside_graph_passes(self):
        self.assert_passes({"services/api/app/api/new_route.py": "x = 1\n"})

    def test_new_import_added_to_collector_expands_the_set(self):
        head = self.repo.commit(
            {
                "services/snkrdunk_collector/snkrdunk_collector/due.py": (
                    FIXTURE["services/snkrdunk_collector/snkrdunk_collector/due.py"]
                    + "from app.services import unused\n"
                )
            }
        )
        self.assertIn(
            "services/api/app/services/unused.py",
            inputs.runtime_inputs(head, "snkrdunk"),
        )
        self.assertNotIn(
            "services/api/app/services/unused.py",
            inputs.runtime_inputs(self.repo.base, "snkrdunk"),
        )
        with self.assertRaises(inputs.state.VerificationError):
            snkr.collector_continuity(self.repo.base, head, "snkrdunk")

    def test_new_import_inside_imported_api_module_counts_changed_target(self):
        # The collector package itself is unchanged; only the API graph grows.
        changed, basis = self.changed(
            {
                "services/api/app/services/helper.py": "from app.services.unused import value\n",
                "services/api/app/services/unused.py": "value = 4\n",
            }
        )
        self.assertEqual(basis, "import-graph")
        self.assertEqual(
            sorted(changed),
            ["services/api/app/services/helper.py", "services/api/app/services/unused.py"],
        )

    def test_removed_import_still_counts_module_installed_at_component(self):
        changed, _ = self.changed(
            {
                "services/api/app/services/used.py": "def run():\n    return 1\n",
                "services/api/app/services/helper.py": "value = 5\n",
            }
        )
        self.assertIn("services/api/app/services/helper.py", changed)

    def test_package_data_and_packaging_files_always_count(self):
        for path in (
            "services/api/app/services/evidence/data.json",
            "services/api/pyproject.toml",
            "services/api/requirements.txt",
        ):
            with self.subTest(path=path):
                self.assert_fails({path: "changed\n"})

    def test_collector_identity_package_and_dockerfile_always_count(self):
        for path in (
            "services/snkrdunk_collector/tests/test_due.py",
            "packages/opcg_source_identity/src/opcg_source_identity/__init__.py",
            "deploy/railway/snkrdunk-collector.Dockerfile",
        ):
            with self.subTest(path=path):
                self.assert_fails({path: "# changed\n"})

    def test_documentation_only_change_is_unchanged(self):
        self.assertEqual(self.assert_passes({"docs/readme.md": "more\n"}), "unchanged")

    def test_each_collector_uses_its_own_graph(self):
        # Yuyu imports used/helper too, but never routes.
        self.assert_passes({"services/api/app/api/routes.py": "y = 1\n"}, "yuyutei")
        self.assert_fails({"services/api/app/services/helper.py": "value = 8\n"}, "yuyutei")
        self.assert_fails(
            {"deploy/railway/yuyutei-collector.Dockerfile": "FROM busybox\n"}, "yuyutei"
        )

    def test_dynamic_import_falls_back_to_full_path_set(self):
        changed, basis = self.changed(
            {
                "services/api/app/services/used.py": (
                    "import importlib\n"
                    "def run(name):\n    return importlib.import_module(name)\n"
                ),
                "services/api/app/api/routes.py": "z = 1\n",
            }
        )
        self.assertTrue(basis.startswith("full-path fallback"))
        self.assertIn("services/api/app/api/routes.py", changed)

    def test_unparsable_reachable_module_falls_back_to_full_path_set(self):
        changed, basis = self.changed(
            {
                "services/api/app/services/helper.py": "def broken(:\n",
                "services/api/alembic/versions/rev.py": "revision = 'c'\n",
            }
        )
        self.assertTrue(basis.startswith("full-path fallback"))
        self.assertIn("services/api/alembic/versions/rev.py", changed)

    def test_unresolved_app_import_falls_back_to_full_path_set(self):
        changed, basis = self.changed(
            {
                "services/api/app/services/used.py": "from app.missing.module import x\n",
                "services/api/app/api/routes.py": "w = 1\n",
            }
        )
        self.assertTrue(basis.startswith("full-path fallback"))
        self.assertIn("services/api/app/api/routes.py", changed)

    def test_unknown_component_commit_still_fails(self):
        head = self.repo.commit({"services/api/app/api/routes.py": "v = 1\n"})
        with self.assertRaises(subprocess.CalledProcessError):
            snkr.collector_continuity("0" * 40, head, "snkrdunk")

    def test_full_path_set_matches_previous_snkr_inputs(self):
        self.assertEqual(
            snkr.SNKR_PATHS,
            (
                "services/snkrdunk_collector",
                "services/api",
                "packages/opcg_source_identity",
                "deploy/railway/snkrdunk-collector.Dockerfile",
            ),
        )

    def test_yuyu_verifier_refuses_changed_runtime_input(self):
        head = self.repo.commit({"services/api/app/services/helper.py": "value = 7\n"})
        manifest = self.repo.root / "docs/agent/STAGING_MISSION.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps({"deployment_verification": {"yuyu_reader_component": self.repo.base}})
        )
        with patch.object(yuyu.state, "ROOT", self.repo.root), patch.object(
            yuyu.subprocess, "check_output", side_effect=self.yuyu_git(head)
        ), patch.object(yuyu.state, "collect_live", side_effect=AssertionError("no live read")):
            with self.assertRaisesRegex(
                yuyu.state.VerificationError, "Installed Yuyu reader runtime inputs changed"
            ):
                yuyu.main()

    def yuyu_git(self, head):
        real = subprocess.check_output

        def run(command, *args, **kwargs):
            if command[:2] == ["git", "rev-parse"]:
                return head + "\n"
            return real(command, *args, **kwargs)

        return run


class RepositoryGraphTests(unittest.TestCase):
    """The checked-in collectors resolve without fallback and exclude API routes."""

    def test_real_collectors_resolve_and_exclude_http_routes(self):
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
        with patch.object(inputs.state, "ROOT", REPO):
            for collector in ("snkrdunk", "yuyutei"):
                with self.subTest(collector=collector):
                    found = inputs.runtime_inputs(head, collector)
                    for path in (
                        "services/api/app/services/freshness_integration.py",
                        "services/api/app/services/freshness_queue.py",
                        "services/api/app/services/raw_dictionary_storage.py",
                        "services/api/app/models/__init__.py",
                    ):
                        self.assertIn(path, found)
                    self.assertNotIn("services/api/app/main.py", found)
                    self.assertNotIn("services/api/app/api/market.py", found)


# Collector v1 S1 (legacy deletion): every services/api path the PR deletes or
# edits. PLAN §A rule 6: none may be a collector runtime input, so S1 is not a
# collector release. Deleted modules must also leave the graph resolvable.
COLLECTOR_V1_S1_API_PATHS = (
    "services/api/app/api/admin_actions.py",
    "services/api/app/api/admin_card_merge.py",
    "services/api/app/api/admin_cards.py",
    "services/api/app/api/admin_data_retention.py",
    "services/api/app/api/admin_observability.py",
    "services/api/app/api/admin_release_status.py",
    "services/api/app/api/analytics.py",
    "services/api/app/api/collector_activity.py",
    "services/api/app/api/dashboard.py",
    "services/api/app/api/grading.py",
    "services/api/app/api/market.py",
    "services/api/app/api/market_workflow_runs.py",
    "services/api/app/api/search.py",
    "services/api/app/core/rate_limit.py",
    "services/api/app/generate_analytics_digest.py",
    "services/api/app/generate_market_report.py",
    "services/api/app/main.py",
    "services/api/app/schemas.py",
    "services/api/app/seed_saved_views.py",
    "services/api/app/send_market_report_digest.py",
    "services/api/app/services/activity_timeline.py",
    "services/api/app/services/analytics_digest.py",
    "services/api/app/services/buy_decision_support.py",
    "services/api/app/services/collection_csv.py",
    "services/api/app/services/dashboard.py",
    "services/api/app/services/grading_analytics.py",
    "services/api/app/services/job_locks.py",
    "services/api/app/services/market_report.py",
    "services/api/app/services/market_signal_events.py",
    "services/api/app/services/market_signals.py",
    "services/api/app/services/market_workflow_trigger.py",
    "services/api/app/services/observability.py",
    "services/api/app/services/opportunity_scoring.py",
    "services/api/app/services/portfolio_risk.py",
    "services/api/app/services/public_price_payload.py",
    "services/api/app/services/refresh_trigger.py",
    "services/api/app/services/release_status.py",
    "services/api/app/services/search.py",
    "services/api/app/services/search_ownership.py",
    "services/api/app/services/sell_decision_support.py",
    "services/api/app/services/system_check.py",
    "services/api/app/services/telegram_client.py",
    "services/api/app/services/telegram_market_digest.py",
    "services/api/app/services/wishlist_csv.py",
    "services/api/app/snapshot_market_signals.py",
    "services/api/app/snapshot_portfolio_valuation.py",
    "services/api/tests/test_activity_wiring.py",
    "services/api/tests/test_admin_actions.py",
    "services/api/tests/test_admin_auth.py",
    "services/api/tests/test_analytics_digest.py",
    "services/api/tests/test_backup.py",
    "services/api/tests/test_buy_decision_support.py",
    "services/api/tests/test_cache.py",
    "services/api/tests/test_collector.py",
    "services/api/tests/test_collector_activity.py",
    "services/api/tests/test_dashboard.py",
    "services/api/tests/test_grading.py",
    "services/api/tests/test_grading_analytics.py",
    "services/api/tests/test_legacy_routes_removed.py",
    "services/api/tests/test_market_analytics.py",
    "services/api/tests/test_market_report.py",
    "services/api/tests/test_market_signal_events.py",
    "services/api/tests/test_market_signals.py",
    "services/api/tests/test_mutating_route_auth.py",
    "services/api/tests/test_observability.py",
    "services/api/tests/test_opportunity_scoring.py",
    "services/api/tests/test_pagination_endpoints.py",
    "services/api/tests/test_portfolio_risk.py",
    "services/api/tests/test_private_read_route_auth.py",
    "services/api/tests/test_rate_limit.py",
    "services/api/tests/test_release_status.py",
    "services/api/tests/test_search.py",
    "services/api/tests/test_search_health.py",
    "services/api/tests/test_search_tenant_isolation.py",
    "services/api/tests/test_sell_decision_support.py",
    "services/api/tests/test_system_check.py",
    "services/api/tests/test_telegram_market_digest.py",
    "services/api/tests/test_yuyutei_sale_price_semantics.py",
)


class CollectorV1S1ImportGraphTests(unittest.TestCase):
    def test_s1_paths_are_outside_both_collector_runtime_inputs(self):
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
        with patch.object(inputs.state, "ROOT", REPO):
            for collector in ("snkrdunk", "yuyutei"):
                with self.subTest(collector=collector):
                    found = inputs.runtime_inputs(head, collector)
                    touched = [p for p in COLLECTOR_V1_S1_API_PATHS if inputs.counts(p, found)]
                    self.assertEqual(touched, [])
                    for protected in ("services/api/app/models/__init__.py", "services/api/app/settings.py"):
                        self.assertNotIn(protected, COLLECTOR_V1_S1_API_PATHS)


# New-sources plan §2.7 (docs/agent/plans/new-sources/PLAN.md): every new-source file stays outside
# the Yuyu-Tei and SNKRDUNK runtime inputs, so no new-source PR redeploys either collector.
NEW_SOURCE_ROOTS = (
    "services/api/app/source_products/",
    "services/api/alembic/versions/7a52e9b48e8a_add_new_source_records.py",
    "services/api/tests/test_new_source_records_migration_postgres.py",
)


class NewSourcesGuardTests(unittest.TestCase):
    def _head(self):
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()

    def test_new_source_paths_are_outside_both_collector_runtime_inputs(self):
        head = self._head()
        listed = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", head, "--", *NEW_SOURCE_ROOTS], cwd=REPO, text=True
        ).split()
        self.assertTrue(listed)
        with patch.object(inputs.state, "ROOT", REPO):
            for collector in ("snkrdunk", "yuyutei"):
                with self.subTest(collector=collector):
                    found = inputs.runtime_inputs(head, collector)
                    scope = inputs.full_paths(collector)
                    touched = [p for p in listed
                               if any(p == s or p.startswith(s + "/") for s in scope) and inputs.counts(p, found)]
                    self.assertEqual(touched, [])

    def test_a_new_source_diff_changes_no_collector_runtime_input(self):
        """When the base is available (local runs, NEW_SOURCES_GUARD_BASE), a diff that touches a
        new-source path must change no Yuyu-Tei or SNKRDUNK runtime input."""
        import os

        base = os.environ.get("NEW_SOURCES_GUARD_BASE") or "origin/staging"
        try:
            base_sha = subprocess.check_output(
                ["git", "merge-base", base, "HEAD"], cwd=REPO, text=True, stderr=subprocess.DEVNULL
            ).strip()
        except subprocess.CalledProcessError:
            self.skipTest(f"{base} is not available in this checkout")
        head = self._head()
        changed = subprocess.check_output(
            ["git", "diff", "--name-only", base_sha, head, "--", *NEW_SOURCE_ROOTS], cwd=REPO, text=True
        ).split()
        if not changed:
            self.skipTest("this diff touches no new-source path")
        with patch.object(inputs.state, "ROOT", REPO):
            for collector in ("snkrdunk", "yuyutei"):
                with self.subTest(collector=collector):
                    runtime, basis = inputs.changed_runtime_inputs(base_sha, head, collector)
                    self.assertEqual(runtime, [], basis)


if __name__ == "__main__":
    unittest.main()
