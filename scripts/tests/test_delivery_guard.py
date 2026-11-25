"""scripts/delivery_guard.py over recorded-shape GitHub answers (no network).

CP security review 2026-11-24 change 5 cases: 101 runs, unknown status, a renamed
job (contract test on the workflow files), a verify run in progress, own run,
HTTP 403 and an empty body; plus applicability from the live PR.
"""
import io
import json
from pathlib import Path
import sys
import unittest
import urllib.error

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import delivery_guard as g  # noqa: E402

REPO = "Insomniac79ac/optcg-price-tracker"
CI, VERIFY = g.WORKFLOW_IDS[g.CI_WORKFLOW], g.WORKFLOW_IDS[g.VERIFY_WORKFLOW]
OWN = 900


def runs_path(workflow_id, status):
    return f"/repos/{REPO}/actions/workflows/{workflow_id}/runs?status={status}&per_page=100"


def jobs_path(run_id):
    return f"/repos/{REPO}/actions/runs/{run_id}/jobs?filter=latest&per_page=100"


def run(rid, workflow_id=CI, status="in_progress", **kw):
    return dict({"id": rid, "workflow_id": workflow_id, "status": status,
                 # attacker-controlled fields the guard must ignore
                 "display_title": "staging-automerge", "head_branch": "x", "name": "CI"}, **kw)


def job(name, status="completed"):
    return {"name": name, "status": status}


class Fake:
    """GitHub as a dict of path -> answer; an Exception value is raised. Unknown paths fail
    the test, so every call the guard makes is declared."""

    def __init__(self, pull=None, files=(), runs=None, jobs=None, branch=None):
        self.answers = {
            f"/repos/{REPO}/pulls/7": pull if pull is not None else {
                "head": {"repo": {"full_name": REPO}}, "labels": [], "changed_files": len(files)},
            f"/repos/{REPO}/pulls/7/files?per_page=100&page=1": [{"filename": f} for f in files],
            f"/repos/{REPO}/branches/staging": branch if branch is not None else {
                "protected": True, "protection": {"required_status_checks": {
                    "enforcement_level": "everyone", "contexts": ["engineering-gate"]}}},
        }
        runs = runs or {}
        for wid in (CI, VERIFY):
            for status in g.OPEN_RUN_STATUSES:
                items = runs.get((wid, status), [])
                self.answers[runs_path(wid, status)] = (
                    items if isinstance(items, (dict, Exception)) else {"total_count": len(items), "workflow_runs": items})
        for rid, items in (jobs or {}).items():
            self.answers[jobs_path(rid)] = (
                items if isinstance(items, (dict, Exception)) else {"total_count": len(items), "jobs": items})
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        if path not in self.answers:
            raise AssertionError(f"undeclared GET {path}")
        value = self.answers[path]
        if isinstance(value, Exception):
            raise value
        return value


def guard(fake, owner_merge_only="true", **env):
    out = io.StringIO()
    environment = dict({"REPO": REPO, "PR": "7", "RUN_ID": str(OWN), "GH_TOKEN": "t",
                        "OWNER_MERGE_ONLY": owner_merge_only}, **env)
    code = g.main(environment, get=fake, out=out)
    return code, out.getvalue()


class Applicability(unittest.TestCase):
    def test_an_ordinary_pr_is_not_applicable_and_succeeds(self):
        fake = Fake(files=["apps/web/a.ts"])
        code, text = guard(fake, owner_merge_only="false")
        self.assertEqual(code, 0)
        self.assertIn("not applicable", text)
        self.assertFalse(any("/actions/" in c for c in fake.calls))

    def test_a_live_hold_label_applies(self):
        pull = {"head": {"repo": {"full_name": REPO}}, "labels": [{"name": "hold-for-owner"}], "changed_files": 1}
        code, text = guard(Fake(pull=pull), owner_merge_only="false")
        self.assertEqual(code, 0)
        self.assertIn("live label hold-for-owner", text)

    def test_a_workflow_change_applies(self):
        code, text = guard(Fake(files=["docs/a.md", ".github/workflows/ci.yml"]), owner_merge_only="false")
        self.assertEqual(code, 0)
        self.assertIn("changes .github/workflows/", text)

    def test_a_fork_pr_fails(self):
        pull = {"head": {"repo": {"full_name": "someone/optcg-price-tracker"}}, "labels": [], "changed_files": 0}
        code, text = guard(Fake(pull=pull))
        self.assertEqual(code, 1)
        self.assertIn("does not come from this repository", text)

    def test_files_read_short_of_changed_files_fails(self):
        pull = {"head": {"repo": {"full_name": REPO}}, "labels": [], "changed_files": 2}
        code, text = guard(Fake(pull=pull, files=["a"]), owner_merge_only="false")
        self.assertEqual(code, 1)

    def test_missing_environment_fails(self):
        out = io.StringIO()
        self.assertEqual(g.main({"REPO": REPO}, get=Fake(), out=out), 1)


class Blockers(unittest.TestCase):
    def test_nothing_running_succeeds(self):
        code, text = guard(Fake())
        self.assertEqual(code, 0, text)
        self.assertIn("no staging delivery running or queued", text)

    def test_an_automerge_job_in_progress_fails_with_the_run_id(self):
        fake = Fake(runs={(CI, "in_progress"): [run(41)]},
                    jobs={41: [job("staging-automerge", "in_progress"), job("backend-tests")]})
        code, text = guard(fake)
        self.assertEqual(code, 1)
        self.assertIn("CI run 41 job staging-automerge is in_progress", text)

    def test_a_queued_credential_presence_job_fails(self):
        fake = Fake(runs={(CI, "queued"): [run(42, status="queued")]},
                    jobs={42: [job("staging-credential-presence", "queued")]})
        self.assertEqual(guard(fake)[0], 1)

    def test_a_ci_run_whose_delivery_jobs_are_done_or_skipped_passes(self):
        fake = Fake(runs={(CI, "in_progress"): [run(43)]},
                    jobs={43: [job("staging-automerge"), job("staging-credential-presence"),
                               job("frontend-build", "in_progress")]})
        self.assertEqual(guard(fake)[0], 0)

    def test_a_verify_run_in_progress_fails(self):
        fake = Fake(runs={(VERIFY, "in_progress"): [run(44, workflow_id=VERIFY)]})
        code, text = guard(fake)
        self.assertEqual(code, 1)
        self.assertIn("staging-verify run 44 is in_progress", text)

    def test_own_run_is_the_only_run_excluded(self):
        fake = Fake(runs={(CI, "in_progress"): [run(OWN)]})
        self.assertEqual(guard(fake)[0], 0)
        self.assertNotIn(jobs_path(OWN), fake.calls)

    def test_titles_and_branches_never_decide(self):
        fake = Fake(runs={(CI, "in_progress"): [run(45, display_title="docs only", head_branch="grok/x")]},
                    jobs={45: [job("staging-automerge", "waiting")]})
        self.assertEqual(guard(fake)[0], 1)


class FailClosed(unittest.TestCase):
    def test_more_than_one_page_of_runs_fails(self):
        many = {"total_count": 101, "workflow_runs": [run(i) for i in range(100)]}
        code, text = guard(Fake(runs={(CI, "queued"): many}))
        self.assertEqual(code, 1)
        self.assertIn("more than one page", text)

    def test_more_than_one_page_of_jobs_fails(self):
        fake = Fake(runs={(CI, "in_progress"): [run(46)]},
                    jobs={46: {"total_count": 101, "jobs": [job("a")] * 100}})
        self.assertEqual(guard(fake)[0], 1)

    def test_an_unknown_run_status_fails(self):
        self.assertEqual(guard(Fake(runs={(CI, "in_progress"): [run(47, status="paused")]}))[0], 1)

    def test_a_run_of_another_workflow_fails(self):
        self.assertEqual(guard(Fake(runs={(CI, "in_progress"): [run(48, workflow_id=1)]}))[0], 1)

    def test_an_unknown_job_status_fails(self):
        fake = Fake(runs={(CI, "in_progress"): [run(49)]}, jobs={49: [job("lint", "sleeping")]})
        self.assertEqual(guard(fake)[0], 1)

    def test_an_answer_without_the_list_fails(self):
        self.assertEqual(guard(Fake(runs={(VERIFY, "waiting"): {"total_count": 0}}))[0], 1)

    def test_an_http_error_fails(self):
        error = g.Refused("GET /repos/x answered HTTP 403")
        self.assertEqual(guard(Fake(runs={(CI, "pending"): error}))[0], 1)

    def test_protection_off_or_not_enforced_for_admins_fails(self):
        self.assertEqual(guard(Fake(branch={"protected": False}))[0], 1)
        self.assertEqual(guard(Fake(branch={"protected": True, "protection": {"required_status_checks": {
            "enforcement_level": "non_admins", "contexts": ["engineering-gate"]}}}))[0], 1)
        self.assertEqual(guard(Fake(branch={"protected": True, "protection": {"required_status_checks": {
            "enforcement_level": "everyone", "contexts": []}}}))[0], 1)


class Http(unittest.TestCase):
    class Response:
        def __init__(self, status, body):
            self.status, self.body = status, body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return self.body

    def test_403_empty_body_non_json_and_timeout_refuse(self):
        def raises(exc):
            def opener(request, timeout):
                raise exc
            return opener
        cases = [
            raises(urllib.error.HTTPError("u", 403, "Forbidden", {}, None)),
            raises(TimeoutError()),
            lambda request, timeout: self.Response(200, b""),
            lambda request, timeout: self.Response(200, b"<html>"),
            lambda request, timeout: self.Response(202, b"{}"),
        ]
        for opener in cases:
            with self.assertRaises(g.Refused):
                g.http_get_json("/repos/x", "t", opener=opener)

    def test_a_200_json_answer_is_returned_and_the_token_is_a_header(self):
        seen = {}

        def opener(request, timeout):
            seen["auth"], seen["timeout"] = request.get_header("Authorization"), timeout
            return self.Response(200, json.dumps({"a": 1}).encode())

        self.assertEqual(g.http_get_json("/repos/x", "secret", opener=opener), {"a": 1})
        self.assertEqual(seen, {"auth": "Bearer secret", "timeout": g.TIMEOUT_SECONDS})


class Contract(unittest.TestCase):
    """If a job key or the delivery group changes, the guard would pass quietly: fail CI instead."""

    def load(self, rel):
        return yaml.safe_load((ROOT / rel).read_text())

    def test_ci_delivery_jobs_keep_their_keys_and_group_and_set_no_name(self):
        jobs = self.load(g.CI_WORKFLOW)["jobs"]
        holders = {key for key, spec in jobs.items()
                   if (spec.get("concurrency") or {}).get("group") == g.DELIVERY_GROUP}
        self.assertEqual(holders, set(g.CI_DELIVERY_JOBS))
        for key in g.CI_DELIVERY_JOBS:
            self.assertNotIn("name", jobs[key], f"{key} must keep its key as its job name")

    def test_verify_workflow_holds_the_group_at_workflow_level(self):
        self.assertEqual(self.load(g.VERIFY_WORKFLOW)["concurrency"]["group"], g.DELIVERY_GROUP)

    def test_no_other_registered_workflow_holds_the_group_at_workflow_level(self):
        for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
            rel = str(path.relative_to(ROOT))
            doc = yaml.safe_load(path.read_text()) or {}
            group = (doc.get("concurrency") or {}).get("group") if isinstance(doc.get("concurrency"), dict) else None
            if group == g.DELIVERY_GROUP:
                self.assertIn(rel, (g.VERIFY_WORKFLOW, ".github/workflows/staging-delivery.yml"), rel)


if __name__ == "__main__":
    unittest.main()
