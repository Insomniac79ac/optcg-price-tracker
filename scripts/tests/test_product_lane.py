import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import product_lane  # noqa: E402
import staging_delivery_scope as scope  # noqa: E402


def git(*args, env=None):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True,
                                   env={**os.environ, **(env or {})}).strip()


def synthetic_commit(changes):
    """A commit on top of HEAD with {path: text or None}; touches no ref or worktree."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index"),
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
        git("read-tree", "HEAD", env=env)
        for path, text in changes.items():
            if text is None:
                git("rm", "--cached", "-q", path, env=env)
                continue
            blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=ROOT, input=text,
                                  text=True, capture_output=True, check=True).stdout.strip()
            git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
        tree = git("write-tree", env=env)
        return git("commit-tree", tree, "-p", "HEAD", "-m", "fixture", env=env)


ADDITIVE = '''revision = "aaaaaaaaaaaa"
down_revision = "{down}"
from alembic import op
import sqlalchemy as sa
def upgrade():
    op.create_table("collector_badges", sa.Column("id", sa.Integer(), primary_key=True))
    op.create_index("ix_collector_badges_id", "collector_badges", ["id"])
    op.add_column("collector_badges", sa.Column("label", sa.Text(), nullable=True))
def downgrade():
    op.drop_table("collector_badges")
'''


def head_revision():
    import staging_db_read_check as guard
    (head,) = guard.expected_revisions_from_repo(str(ROOT))
    return head


class ProductLaneDirections(unittest.TestCase):
    """Real Git objects and the real collector import graph, both directions."""

    def lane(self, changes, body=""):
        return product_lane.classify("HEAD", synthetic_commit(changes), body)

    def test_web_page_test_and_docs_are_product(self):
        r = self.lane({"apps/web/src/app/fixture/page.tsx": "export default 1\n",
                       "services/api/tests/test_fixture_lane.py": "def test_x():\n    pass\n",
                       "docs/fixture.md": "x\n", "docs/agent/PRODUCT_LOG.md": "x\n"})
        self.assertEqual(r["lane"], "product", r["reasons"])
        self.assertEqual(r["migrations"], [])

    def test_allowlisted_api_module_outside_import_graph_is_product(self):
        path = "services/api/app/api/saved_views.py"
        r = self.lane({path: (ROOT / path).read_text() + "\nFIXTURE = 1\n"})
        self.assertEqual(r["lane"], "product", r["reasons"])

    def test_api_wiring_cards_and_unlisted_modules_are_data(self):
        for path in ("services/api/app/main.py", "services/api/app/schemas.py",
                     "services/api/app/api/cards.py", "services/api/app/services/card_matching.py",
                     "services/api/app/seed.py", "services/api/app/accounts/fixture_lane.py"):
            with self.subTest(path=path):
                r = self.lane({path: "X = 1\n"})
                self.assertEqual(r["lane"], "data")

    def test_collector_import_graph_input_is_data(self):
        # Passes every path rule; only the import graph knows a collector runs it.
        path = "services/api/app/services/operational_health.py"
        text = (ROOT / path).read_text() + "\nFIXTURE = 1\n"
        r = self.lane({path: text})
        self.assertEqual(r["lane"], "data")
        self.assertIn(f"{path}: collector runtime input (import graph)", r["reasons"])

    def test_price_identity_mv_index_code_is_data(self):
        for path in ("services/api/app/market_value_writer.py",
                     "services/api/app/card_pirate_index_writer.py",
                     "services/api/app/accounts/value_history.py",
                     "services/api/app/api/source_mappings.py"):
            with self.subTest(path=path):
                r = self.lane({path: "X = 1\n"})
                self.assertEqual(r["lane"], "data")
                self.assertTrue(any("price, identity" in x for x in r["reasons"]), r["reasons"])

    def test_collectors_infrastructure_workflows_scripts_manifest_are_data(self):
        for path in ("services/snkrdunk_collector/README.md", "packages/opcg_source_identity/README.md",
                     "deploy/railway/api.Dockerfile", ".github/workflows/fixture.yml",
                     "scripts/fixture.py", "apps/web/vercel.json", "services/api/requirements.txt",
                     "docs/agent/STAGING_MISSION.json", "docs/agent/AUTONOMY_POLICY.md",
                     "docs/agent/missions/claude-x.json", "docs/agent/STAGING_FLEET.json"):
            with self.subTest(path=path):
                self.assertEqual(self.lane({path: "{}\n"})["lane"], "data")

    def test_one_data_path_makes_the_whole_change_data(self):
        r = self.lane({"apps/web/src/app/fixture/page.tsx": "x\n", "scripts/fixture.py": "x\n"})
        self.assertEqual(r["lane"], "data")

    def test_additive_migration_is_product_and_flagged_for_backup(self):
        path = "services/api/alembic/versions/aaaaaaaaaaaa_fixture.py"
        r = self.lane({path: ADDITIVE.format(down=head_revision())})
        self.assertEqual(r["lane"], "product", r["reasons"])
        self.assertEqual(r["migrations"], [path])

    def test_destructive_protected_or_disguised_migrations_are_data(self):
        path = "services/api/alembic/versions/aaaaaaaaaaaa_fixture.py"
        base = ADDITIVE.format(down=head_revision())
        for bad in ('op.drop_column("users", "email")', 'op.execute("delete from users")',
                    'op.alter_column("users", "email", nullable=True)',
                    'op.add_column("price_observations", sa.Column("x", sa.Text(), nullable=True))',
                    'op.create_index("ix", "market_value_points", ["id"])',
                    'op.add_column("cards", sa.Column("x", sa.Text(), nullable=True))',
                    'op.create_unique_constraint("uq", "users", ["email"])',
                    'op.add_column("collector_badges", sa.Column("y", sa.Text(), False))',
                    'getattr(op, "execute")("delete from cards")',
                    'op.get_bind().execute(sa.text("delete from cards"))',
                    'helper()',
                    'op.create_table("badge_links", sa.Column("p", sa.Integer(), '
                    'sa.ForeignKey("price_observations.id")))',
                    'op.create_table("cards", sa.Column("id", sa.Integer()))'):
            with self.subTest(op=bad):
                text = base.replace("def downgrade", f"    {bad}\ndef downgrade")
                self.assertEqual(self.lane({path: text})["lane"], "data")
        for module in ('from alembic import op as o\n', 'def helper():\n    op.execute("x")\n',
                       'op.execute("delete from cards")\n'):
            with self.subTest(module=module):
                self.assertEqual(self.lane({path: base + module})["lane"], "data")

    def test_migration_must_chain_onto_the_base_head(self):
        path = "services/api/alembic/versions/aaaaaaaaaaaa_fixture.py"
        r = self.lane({path: ADDITIVE.format(down="000000000000")})
        self.assertEqual(r["lane"], "data")
        self.assertTrue(any("exactly one" in x for x in r["reasons"]), r["reasons"])

    def test_web_build_supply_chain_needs_the_review_line(self):
        path = "apps/web/package.json"
        changes = {path: (ROOT / path).read_text() + "\n"}
        self.assertEqual(self.lane(changes)["lane"], "data")
        self.assertEqual(self.lane(changes, body="Independent security review: deps diff checked")["lane"],
                         "product")

    def test_editing_an_existing_migration_is_data(self):
        versions = ROOT / "services/api/alembic/versions"
        path = str(sorted(versions.glob("*.py"))[0].relative_to(ROOT))
        r = self.lane({path: (ROOT / path).read_text() + "\n# edit\n"})
        self.assertEqual(r["lane"], "data")

    def test_auth_paths_need_an_independent_review_line(self):
        changes = {"apps/web/src/lib/authFixture.ts": "export const x = 1\n"}
        self.assertEqual(self.lane(changes)["lane"], "data")
        r = self.lane(changes, body="Summary\nIndependent security review: fresh agent pass, no findings\n")
        self.assertEqual(r["lane"], "product", r["reasons"])
        self.assertTrue(r["security_review_required"])

    def test_authoritative_is_not_an_auth_path(self):
        r = self.lane({"services/api/tests/test_print_authoritative_fixture.py": "X = 1\n"})
        self.assertEqual(r["lane"], "product", r["reasons"])


class FailClosed(unittest.TestCase):
    def test_unresolvable_import_graph_is_data_in_policy_and_scope(self):
        import staging_policy
        args = mock.Mock(base="HEAD", head="HEAD", pr_body_file=None)
        with mock.patch.object(product_lane, "classify", side_effect=RuntimeError("boom")):
            self.assertEqual(staging_policy.product_lane_result(args)["lane"], "data")
            self.assertNotIn("decision", scope.product_decision("HEAD", "HEAD"))

    def test_policy_main_product_needs_no_manifest_and_data_keeps_mission_checks(self):
        product = synthetic_commit({"apps/web/src/app/fixture/page.tsx": "x\n"})
        data = synthetic_commit({"scripts/fixture.py": "x\n"})
        base = git("rev-parse", "HEAD")
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "absent.json")
            ok = subprocess.run([sys.executable, str(SCRIPTS / "staging_policy.py"), "--base", base,
                                 "--head", product, "--manifest", missing], cwd=ROOT,
                                capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            self.assertIn('"PRODUCT"', ok.stdout)
            refused = subprocess.run([sys.executable, str(SCRIPTS / "staging_policy.py"), "--base", base,
                                      "--head", data, "--manifest", missing], cwd=ROOT,
                                     capture_output=True, text=True)
            self.assertEqual(refused.returncode, 1)
            self.assertNotIn('"PRODUCT"', refused.stdout)

    def test_delivery_scope_product_skips_rollout_and_expects_repo_head(self):
        product = synthetic_commit({"apps/web/src/app/fixture/page.tsx": "x\n"})
        d = scope.product_decision(git("rev-parse", "HEAD"), product)
        self.assertEqual(d["decision"], "product")
        self.assertEqual((d["api_sha"], d["revision"]), ("merge", head_revision()))
        data = synthetic_commit({"services/yuyutei_collector/README.md": "x\n"})
        self.assertNotIn("decision", scope.product_decision(git("rev-parse", "HEAD"), data))


if __name__ == "__main__":
    unittest.main()
