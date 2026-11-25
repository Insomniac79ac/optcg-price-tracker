"""Delivery guard: fail a staging PR's check while a staging delivery runs or waits.

Owner t560u ruling 2 and t649u (content-pipeline ops/decisions.md), CP security
review of 2026-11-24 (changes 1 to 8). An accident interlock for hand merges: a
PR the owner merges by hand (owner_merge_only, the hold-for-owner label, or a
change under .github/workflows/) gets a red delivery-guard check while anything
that holds the card-pirate-staging-delivery concurrency group is running or
queued, so a hand merge cannot land in the middle of a delivery (20 Nov 2026).

What it is not: a control against a PR that rewrites its own workflow file. A
pull_request run uses the PR's copy of ci.yml, so such a PR decides its own
checks; the owner checks Actions by hand before merging it. A green check on a
fork PR proves nothing: the owner does not merge fork PRs.

Read-only. Runs from the BASE checkout (ci.yml), so a PR cannot edit the guard
that judges it. Inputs come only from the environment and the GitHub REST API:
GH_TOKEN (the job token, actions: read and pull-requests: read), REPO, PR,
RUN_ID (this run, the only run excluded) and OWNER_MERGE_ONLY (policy-gate's
output). It decides only on workflow ids, run ids, job keys and statuses, never
on titles, branch names, run names, actors, bodies or head SHAs, which a PR
author controls. Every doubt fails: a non-200 answer, a timeout, a body that is
not the expected JSON, more results than one page holds, or a status it does
not know.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
TIMEOUT_SECONDS = 20
PAGE = 100

# Workflows that hold the delivery group, by id (never by display name):
# CI (.github/workflows/ci.yml) and Verify staging merge
# (.github/workflows/staging-verify.yml). scripts/tests/test_delivery_guard.py
# checks the job keys and the concurrency group in both files.
CI_WORKFLOW = ".github/workflows/ci.yml"
VERIFY_WORKFLOW = ".github/workflows/staging-verify.yml"
WORKFLOW_IDS = {CI_WORKFLOW: 314284821, VERIFY_WORKFLOW: 374637094}
DELIVERY_GROUP = "card-pirate-staging-delivery"
# Jobs in CI that join the delivery group (ci.yml job keys; GitHub reports the
# key as the job name because neither job sets `name:`).
CI_DELIVERY_JOBS = ("staging-credential-presence", "staging-automerge")

# The API takes one status per call. action_required (a fork run waiting for
# the owner's approval) is left out on purpose: it has not started, holds no
# group, and counting it would let anyone block hand merges by opening a fork PR.
OPEN_RUN_STATUSES = ("queued", "in_progress", "waiting", "pending", "requested")
KNOWN_JOB_STATUSES = frozenset(OPEN_RUN_STATUSES) | {"completed"}
HOLD_LABEL = "hold-for-owner"
WORKFLOW_DIR = ".github/workflows/"
REQUIRED_CONTEXT = "engineering-gate"


class Refused(Exception):
    """The guard cannot show that no delivery is running: the check fails."""


def http_get_json(path, token, *, opener=urllib.request.urlopen):
    request = urllib.request.Request(
        API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "card-pirate-delivery-guard",
        },
    )
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", None)
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise Refused(f"GET {path.split('?')[0]} answered HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise Refused(f"GET {path.split('?')[0]} failed: {type(exc).__name__}") from None
    if status != 200:
        raise Refused(f"GET {path.split('?')[0]} answered HTTP {status}")
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        raise Refused(f"GET {path.split('?')[0]} did not return JSON") from None


def _list(document, key, path):
    if not isinstance(document, dict) or not isinstance(document.get(key), list):
        raise Refused(f"{path}: no {key} list in the answer")
    items = document[key]
    total = document.get("total_count")
    if not isinstance(total, int) or isinstance(total, bool):
        raise Refused(f"{path}: no total_count in the answer")
    if total > PAGE or total != len(items):
        raise Refused(f"{path}: {total} results, more than one page of {PAGE} can show")
    return items


def applicable(get, repo, pr, owner_merge_only):
    """(applies, why). Decided from policy-gate's output and the LIVE PR, never
    from the event payload's labels (CI does not run on label changes)."""
    pull = get(f"/repos/{repo}/pulls/{pr}")
    if not isinstance(pull, dict):
        raise Refused("pull request: unexpected answer")
    head_repo = ((pull.get("head") or {}).get("repo") or {}).get("full_name")
    if head_repo != repo:
        raise Refused("the pull request does not come from this repository")
    if owner_merge_only == "true":
        return True, "policy-gate owner_merge_only"
    labels = pull.get("labels")
    if not isinstance(labels, list):
        raise Refused("pull request: no labels list")
    if any(isinstance(label, dict) and label.get("name") == HOLD_LABEL for label in labels):
        return True, f"live label {HOLD_LABEL}"
    changed = pull.get("changed_files")
    if not isinstance(changed, int) or isinstance(changed, bool):
        raise Refused("pull request: no changed_files count")
    pages = max(1, -(-changed // PAGE))
    if pages > 30:  # the files API lists at most 3000 files
        raise Refused(f"pull request changes {changed} files, more than the files API lists")
    seen = 0
    for page in range(1, pages + 1):
        files = get(f"/repos/{repo}/pulls/{pr}/files?per_page={PAGE}&page={page}")
        if not isinstance(files, list):
            raise Refused("pull request files: unexpected answer")
        for item in files:
            name = item.get("filename") if isinstance(item, dict) else None
            if not isinstance(name, str):
                raise Refused("pull request files: an entry without a filename")
            seen += 1
            if name.startswith(WORKFLOW_DIR):
                return True, f"changes {WORKFLOW_DIR}"
    if seen != changed:
        raise Refused(f"pull request files: read {seen} of {changed}")
    return False, "not owner_merge_only, no hold-for-owner label, no workflow change"


def check_protection(get, repo):
    """staging must still require engineering-gate for everyone, admins included
    (enforcement_level). strict (up to date before merging) is not readable with
    the job token (the protection API needs admin), so it is not checked here."""
    branch = get(f"/repos/{repo}/branches/staging")
    if not isinstance(branch, dict) or branch.get("protected") is not True:
        raise Refused("staging is not reported as protected")
    checks = ((branch.get("protection") or {}).get("required_status_checks") or {})
    contexts = checks.get("contexts")
    if not isinstance(contexts, list) or REQUIRED_CONTEXT not in contexts:
        raise Refused(f"staging no longer requires {REQUIRED_CONTEXT}")
    if checks.get("enforcement_level") != "everyone":
        raise Refused("staging's required checks no longer apply to admins (enforcement_level)")


def blockers(get, repo, run_id):
    """Every run and job that holds or waits for the delivery group, as messages."""
    found = []
    for path_name, workflow_id in sorted(WORKFLOW_IDS.items()):
        for status in OPEN_RUN_STATUSES:
            path = f"/repos/{repo}/actions/workflows/{workflow_id}/runs?status={status}&per_page={PAGE}"
            for run in _list(get(path), "workflow_runs", path.split("?")[0]):
                rid = run.get("id") if isinstance(run, dict) else None
                if not isinstance(rid, int) or isinstance(rid, bool):
                    raise Refused(f"{path_name}: a run without an id")
                if run.get("workflow_id") != workflow_id:
                    raise Refused(f"run {rid}: workflow id {run.get('workflow_id')!r}, expected {workflow_id}")
                if run.get("status") not in OPEN_RUN_STATUSES:
                    raise Refused(f"run {rid}: unknown status {run.get('status')!r}")
                if rid == run_id:
                    continue
                if workflow_id == WORKFLOW_IDS[VERIFY_WORKFLOW]:
                    found.append(f"staging-verify run {rid} is {run['status']}")
                    continue
                jobs_path = f"/repos/{repo}/actions/runs/{rid}/jobs?filter=latest&per_page={PAGE}"
                for job in _list(get(jobs_path), "jobs", jobs_path.split("?")[0]):
                    if not isinstance(job, dict):
                        raise Refused(f"run {rid}: a job that is not an object")
                    if job.get("status") not in KNOWN_JOB_STATUSES:
                        raise Refused(f"run {rid}: job with unknown status {job.get('status')!r}")
                    if job.get("name") in CI_DELIVERY_JOBS and job["status"] != "completed":
                        found.append(f"CI run {rid} job {job['name']} is {job['status']}")
    return found


def main(env=None, get=None, out=sys.stdout):
    env = os.environ if env is None else env
    try:
        repo, pr, run_raw = env["REPO"], env["PR"], env["RUN_ID"]
        token = env["GH_TOKEN"]
        run_id = int(run_raw)
        if not pr.isdigit() or repo.count("/") != 1:
            raise ValueError
    except (KeyError, ValueError, AttributeError):
        print("delivery-guard: FAIL: REPO, PR, RUN_ID and GH_TOKEN are required", file=out)
        return 1
    get = get or (lambda path: http_get_json(path, token))
    try:
        applies, why = applicable(get, repo, pr, env.get("OWNER_MERGE_ONLY", ""))
        if not applies:
            print(f"delivery-guard: not applicable ({why}); success", file=out)
            return 0
        check_protection(get, repo)
        found = blockers(get, repo, run_id)
    except Refused as exc:
        print(f"delivery-guard: FAIL (fail closed): {exc}", file=out)
        return 1
    if found:
        for line in found:
            print(f"delivery-guard: FAIL: {line}", file=out)
        print("delivery-guard: a staging delivery is running or queued; re-run this check after it finishes",
              file=out)
        return 1
    print(f"delivery-guard: applies ({why}); no staging delivery running or queued; success", file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
