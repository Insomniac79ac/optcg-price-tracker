"""The committed Claude Code settings and PreToolUse hook block what they should.

Runs .claude/hooks/guard.py exactly as Claude Code does (JSON on stdin, exit 2 = blocked) and
checks .claude/settings.json wires it to every tool it guards. The lane check must agree with
scripts/product_lane.path_reason, the definition CI's policy-gate uses.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / ".claude/hooks/guard.py"
sys.path.insert(0, str(ROOT / "scripts"))
import product_lane  # noqa: E402

LANE_MESSAGE = "Data lane. Split it into its own PR or open an issue for the owner."


def hook(tool, tool_input, cwd=ROOT, lane=None):
    env = {k: v for k, v in os.environ.items() if k != "CARDPIRATE_LANE"}
    env["CLAUDE_PROJECT_DIR"] = str(ROOT)
    if lane:
        env["CARDPIRATE_LANE"] = lane
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(cwd)}
    out = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event), capture_output=True, text=True,
                         env=env, timeout=60)
    return out.returncode, out.stderr


def bash(command, **kwargs):
    return hook("Bash", {"command": command}, **kwargs)


BLOCKED = {
    "railway": ["railway status", "railway variables --json", "npx @railway/cli up", "cd x && railway run python a.py",
                "echo ok; railway logs", "ls $(railway whoami)", "bash -c 'railway up'", "sudo railway up",
                "echo hi\nrailway up"],
    "remote postgres": ["psql -h db.example.com -U u", "psql --host=10.0.0.4 x", "pg_dump -hremote.example.com db",
                        "psql postgresql://u:p@sakura.proxy.rlwy.net:12345/railway",
                        "pg_dump 'host=example.org dbname=x'", "PGHOST=example.org psql", "psql \"$DATABASE_URL\"",
                        "pg_restore -h 1.2.3.4 -d x dump.sql"],
    "environment": ["env", "printenv", "printenv RAILWAY_TOKEN", "set", "export -p", "declare -x", "FOO=1 env",
                    "env | grep TOKEN", "cat .env", "less services/api/.env", "head -n 3 apps/web/.env.local",
                    "cat /proc/1/environ", "echo $GH_TOKEN", "printf '%s' \"${STAGING_RAILWAY_TOKEN}\"",
                    "echo ${#API_JWT_SECRET}", "gh auth token", "gh auth status --show-token"],
    "owner signals": ["gh pr edit 140 --remove-label hold-for-owner",
                      "gh api -X DELETE repos/o/r/issues/140/labels/hold-for-owner",
                      "gh api -X PUT repos/o/r/issues/140/labels -f 'labels[]=x'",
                      "gh variable set STAGING_AUTONOMY_ENABLED --body false", "gh variable delete X",
                      "gh api -X PATCH repos/o/r -F allow_auto_merge=false", "gh repo edit --enable-auto-merge=false",
                      "gh pr review 140 --approve", "gh api repos/o/r/pulls/140/reviews -f event=APPROVE",
                      "gh pr merge 140 --admin --merge", "gh label delete hold-for-owner"],
    "github admin apis": ["gh api repos/o/r/deployments", "gh api repos/o/r/actions/runs/9/pending_deployments",
                          "gh api -X POST repos/o/r/actions/runs/9/pending_deployments -f state=approved",
                          "gh api repos/o/r/rulesets", "gh api repos/o/r/branches/staging/protection",
                          "gh api repos/o/r/actions/secrets", "gh api repos/o/r/environments/staging-ops",
                          "gh api repos/o/r/actions/variables", "gh secret list", "gh ruleset list",
                          "curl -H 'Authorization: x' https://api.github.com/repos/o/r/environments"],
    "staging pushes": ["git push origin staging", "git push origin HEAD:staging", "git push origin feat:refs/heads/staging",
                       "git push -f origin feat", "git push --force origin feat", "git push --force-with-lease origin feat",
                       "git push origin +feat", "git push --mirror origin", "git push --all origin",
                       "gh api -X PATCH repos/o/r/git/refs/heads/staging -f sha=abc",
                       "gh api -X PUT repos/o/r/contents/README.md -f branch=staging -f message=x -f content=eA=="],
}

ALLOWED = ["git status", "git push -u origin claude/feature", "git push origin feature:feature", "psql -h localhost -d x",
           "psql postgresql://opcg:opcg@127.0.0.1:5544/opcg_test -c 'select 1'", "pg_dump -h /var/run/postgresql x",
           "psql -d opcg_test", "cat .env.example", "env FOO=1 python -m pytest -q", "set -euo pipefail; ls",
           "echo $HOME", "gh api repos/o/r/pulls/140", "gh api repos/o/r/branches/staging",
           "gh api -X POST repos/o/r/actions/workflows/ops-readonly.yml/dispatches -f ref=staging -f 'inputs[runbook]=staging-state'",
           "gh api repos/o/r/check-runs/1/annotations", "gh pr edit 140 --add-label hold-for-owner",
           "gh api -X POST repos/o/r/pulls/140/ccr/ready_for_review", "python scripts/ops/run.py staging-state --preflight",
           "cat <<'EOF' > notes.md\nNever run railway up or printenv here.\nEOF",
           "grep -rn railway docs/agent/OPS_RUNBOOKS.md", "npm test"]


class BashGuard(unittest.TestCase):
    def test_blocked(self):
        for group, commands in BLOCKED.items():
            for command in commands:
                with self.subTest(group=group, command=command):
                    code, err = bash(command)
                    self.assertEqual(code, 2, err)
                    self.assertIn("Blocked by .claude/hooks/guard.py", err)

    def test_allowed(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                code, err = bash(command)
                self.assertEqual(code, 0, err)

    def test_push_without_refspec_on_staging_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", "-b", "staging", tmp], check=True)
            self.assertEqual(bash("git push", cwd=tmp)[0], 2)
            self.assertEqual(bash("git push origin HEAD", cwd=tmp)[0], 2)
            subprocess.run(["git", "-C", tmp, "checkout", "-q", "-b", "feature"], check=True)
            self.assertEqual(bash("git push", cwd=tmp)[0], 0)


class LaneGuard(unittest.TestCase):
    DATA = [".github/workflows/ci.yml", ".claude/settings.json", "scripts/ops/run.py", "docs/agent/AUTONOMY_POLICY.md",
            "services/api/app/main.py", "services/snkrdunk_collector/snkrdunk_collector/cli.py",
            "docs/agent/STAGING_MISSION.json", "CLAUDE.md", "apps/web/vercel.json"]
    PRODUCT = ["apps/web/src/app/page.tsx", "services/api/tests/test_x.py", "docs/operations.md",
               "docs/agent/PRODUCT_LOG.md", "services/api/app/accounts/router.py"]

    def test_lane_matches_product_lane(self):
        for rel in self.DATA + self.PRODUCT:
            with self.subTest(path=rel):
                expected_block = product_lane.path_reason(rel, "M") is not None
                self.assertEqual(expected_block, rel in self.DATA)
                for tool, payload in (("Edit", {"file_path": str(ROOT / rel), "old_string": "a", "new_string": "b"}),
                                      ("Write", {"file_path": rel, "content": "x"})):
                    code, err = hook(tool, payload)
                    self.assertEqual(code, 2 if expected_block else 0, err)
                    if expected_block:
                        self.assertIn(LANE_MESSAGE, err)

    def test_data_lane_session_may_edit(self):
        for rel in self.DATA:
            self.assertEqual(hook("Edit", {"file_path": str(ROOT / rel)}, lane="data")[0], 0)
        self.assertEqual(hook("Edit", {"file_path": str(ROOT / self.DATA[0])}, lane="product")[0], 2)

    def test_outside_repository_is_not_a_lane(self):
        self.assertEqual(hook("Write", {"file_path": "/tmp/scratch-notes.md", "content": "x"})[0], 0)

    def test_read_env_file(self):
        self.assertEqual(hook("Read", {"file_path": str(ROOT / "services/api/.env")})[0], 2)
        self.assertEqual(hook("Read", {"file_path": str(ROOT / ".env.example")})[0], 0)
        self.assertEqual(hook("Read", {"file_path": str(ROOT / "README.md")})[0], 0)


class McpGuard(unittest.TestCase):
    def test_github_tools(self):
        self.assertEqual(hook("mcp__github__push_files", {"branch": "staging", "files": []})[0], 2)
        self.assertEqual(hook("mcp__github__create_or_update_file", {"branch": "refs/heads/staging"})[0], 2)
        self.assertEqual(hook("mcp__github__push_files", {"branch": "claude/x", "files": []})[0], 0)
        self.assertEqual(hook("mcp__github__pull_request_review_write", {"method": "create", "event": "APPROVE"})[0], 2)
        self.assertEqual(hook("mcp__github__merge_pull_request", {"pullNumber": 1, "admin": True})[0], 2)
        self.assertEqual(hook("mcp__github__issue_write", {"method": "update", "labels": ["bug"]})[0], 2)
        self.assertEqual(hook("mcp__github__issue_write", {"method": "update", "assignees": ["x"]})[0], 0)


class Settings(unittest.TestCase):
    def test_hook_is_wired_for_every_guarded_tool(self):
        settings = json.loads((ROOT / ".claude/settings.json").read_text())
        (entry,) = settings["hooks"]["PreToolUse"]
        matcher = entry["matcher"].split("|")
        for tool in ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Read", "mcp__github__.*"):
            self.assertIn(tool, matcher)
        (command,) = entry["hooks"]
        self.assertIn(".claude/hooks/guard.py", command["command"])

    def test_static_deny_list(self):
        deny = set(json.loads((ROOT / ".claude/settings.json").read_text())["permissions"]["deny"])
        for rule in ("Bash(railway:*)", "Bash(printenv:*)", "Bash(env)", "Bash(gh secret:*)",
                     "Bash(git push --force:*)", "Bash(git push origin staging)", "Read(./**/.env)"):
            self.assertIn(rule, deny)

    def test_guard_fails_closed(self):
        out = subprocess.run([sys.executable, str(GUARD)], input="not json", capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 2)


if __name__ == "__main__":
    unittest.main()
