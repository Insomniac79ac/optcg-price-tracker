#!/usr/bin/env python3
"""Claude Code PreToolUse guard for Card Pirate (committed; docs/agent/AUTONOMY_POLICY.md).

Blocks, whatever the prompt says:
- the Railway CLI; psql/pg_dump/pg_restore to anything but localhost;
- printing the environment or secrets (env, printenv, set, export -p, declare -p/-x, .env
  files, /proc/*/environ, echo of secret-named variables, gh auth token);
- changing an owner-approval signal (the hold-for-owner label, repository variables such as
  STAGING_AUTONOMY_ENABLED, repository settings, PR approvals, admin merges);
- GitHub API calls on deployments, pending deployments (environment approvals), rulesets,
  branch protection, secrets and environments;
- direct pushes to staging and force pushes (git, gh api, GitHub MCP tools);
- Edit/Write of a DATA-lane path unless CARDPIRATE_LANE=data. The lane definition is
  scripts/product_lane.py (path_reason), the same code CI's policy-gate runs.
Exit 2 blocks the tool call and shows the reason to the agent; exit 0 allows it. A guard
error blocks (fail closed). This is defence in depth: CI, rulesets and credentials stay the
enforcement (a Bash redirect can still write a file; CI classifies the PR anyway).
"""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys

LANE_MESSAGE = "Data lane. Split it into its own PR or open an issue for the owner."
HOLD_LABEL = "hold-for-owner"
LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1", "[::1]"}
PG_TOOLS = {"psql", "pg_dump", "pg_dumpall", "pg_restore", "pgcli", "pg_basebackup"}
WRAPPERS = {"sudo", "command", "exec", "nohup", "time", "nice", "stdbuf", "builtin", "doas"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
SECRET_NAME = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|DATABASE_URL|DSN|CREDENTIAL|_KEY\b", re.I)
ENV_FILE = re.compile(r"(^|/)\.env(\.[\w.-]+)?$")
ENV_EXAMPLE = re.compile(r"(^|/)\.env\.(example|sample|template)$")
GITHUB_BLOCKED = re.compile(
    r"(^|/)(deployments|pending_deployments|rulesets|environments|secrets)(/|$|\?)"
    r"|(^|/)branches/[^/\s]+/protection(/|$|\?)|(^|/)actions/variables(/|$|\?)")
REPO_ROOT_PATH = re.compile(r"^/?repos/[^/\s]+/[^/\s?]+/?$")


class Blocked(Exception):
    pass


# ---------------------------------------------------------------- shell parsing

def strip_heredocs(command):
    """Drop here-document bodies: they are data for the command, not commands."""
    lines, out, delimiters = command.split("\n"), [], []
    for line in lines:
        if delimiters:
            if line.strip() == delimiters[0]:
                delimiters.pop(0)
            continue
        out.append(line)
        delimiters.extend(m.group(2) for m in re.finditer(r"<<-?\s*(['\"]?)([A-Za-z_][\w-]*)\1", line))
    return "\n".join(out)


def segments(command):
    """Simple commands (argv lists) in a shell command line, including $(...) and `...` bodies."""
    text = strip_heredocs(command)
    for opener in ("$(", "`", "<(", ">(", "\n"):
        text = text.replace(opener, " ; ")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|()<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    current, out = [], []
    for token in lexer:
        if token and set(token) <= set(";&|()\n"):
            if current:
                out.append(current)
            current = []
        elif token and set(token) <= set("<>"):
            current.append(token)
        else:
            current.append(token)
    if current:
        out.append(current)
    return out


def strip_prefix(argv):
    """Drop VAR=value assignments and transparent wrappers; returns (assignments, argv)."""
    assigns = {}
    argv = list(argv)
    while argv:
        head = argv[0]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", head):
            key, _, value = head.partition("=")
            assigns[key] = value
            argv.pop(0)
        elif PurePosixPath(head).name in WRAPPERS:
            argv.pop(0)
            while argv and argv[0].startswith("-"):
                argv.pop(0)
        elif PurePosixPath(head).name == "timeout":
            argv.pop(0)
            while argv and (argv[0].startswith("-") or re.fullmatch(r"[\d.]+[smhd]?", argv[0])):
                argv.pop(0)
        elif PurePosixPath(head).name == "env" and len(argv) > 1:
            # `env [opts] [VAR=v]... cmd`: the command is checked; bare `env` prints the environment.
            rest = argv[1:]
            while rest and (rest[0].startswith("-") or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", rest[0])):
                if "=" in rest[0] and not rest[0].startswith("-"):
                    key, _, value = rest[0].partition("=")
                    assigns[key] = value
                rest.pop(0)
            if not rest:
                return assigns, ["env"]
            argv = rest
        else:
            break
    return assigns, argv


# ---------------------------------------------------------------- rules

def check_pg(name, args, assigns):
    hosts = []
    if "PGHOST" in assigns:
        hosts.append(assigns["PGHOST"])
    i = 0
    while i < len(args):
        a = args[i]
        if "$" in a:
            raise Blocked(f"{name} with an unresolved variable: the host cannot be checked. Use an explicit localhost URL.")
        if a in ("-h", "--host") and i + 1 < len(args):
            hosts.append(args[i + 1])
            i += 1
        elif a.startswith("--host="):
            hosts.append(a.split("=", 1)[1])
        elif a.startswith("-h") and len(a) > 2:
            hosts.append(a[2:])
        for m in re.finditer(r"postgres(?:ql)?(?:\+\w+)?://([^/?#\s]*)", a):
            netloc = m.group(1).rsplit("@", 1)[-1]
            hosts.extend(h.rsplit(":", 1)[0] if not h.startswith("[") else h.split("]")[0] + "]"
                         for h in netloc.split(","))
        for m in re.finditer(r"(?:^|\s)host\s*=\s*'?([^\s']*)", a):
            hosts.append(m.group(1))
        i += 1
    for host in hosts:
        if host.strip() not in LOCAL_HOSTS and not host.startswith("/"):
            raise Blocked(f"{name} to a non-local host is blocked. Staging data goes through an ops runbook "
                          "(docs/agent/OPS_RUNBOOKS.md); local Postgres only.")


def check_env_print(name, args):
    if name == "printenv":
        raise Blocked("Printing the environment is blocked (it holds credentials).")
    if name == "env" and not args:
        raise Blocked("Printing the environment is blocked (it holds credentials).")
    if name == "set" and not args:
        raise Blocked("Printing shell variables is blocked (they may hold credentials).")
    if name in ("export", "declare", "typeset") and (not args or any(a in ("-p", "-x", "-px", "-xp") for a in args)
                                                     and not any("=" in a for a in args)):
        raise Blocked("Printing exported variables is blocked (they may hold credentials).")
    if name == "compgen" and ("-v" in args or "-e" in args):
        raise Blocked("Listing variables is blocked.")
    if name in ("echo", "printf", "print"):
        for a in args:
            for var in re.findall(r"\$\{?#?([A-Za-z_][A-Za-z0-9_]*)", a):
                if SECRET_NAME.search(var):
                    raise Blocked(f"Printing ${var} is blocked: never print secrets, their lengths or parts.")


def check_files(argv):
    for a in argv[1:]:
        value = a.split("=", 1)[1] if a.startswith("--") and "=" in a else a
        if ENV_FILE.search(value) and not ENV_EXAMPLE.search(value):
            raise Blocked(".env files hold credentials; reading or printing them is blocked (.env.example is fine).")
        if re.search(r"/proc/[^/\s]+/environ", value):
            raise Blocked("Reading a process environment is blocked.")


def method_of(args):
    for i, a in enumerate(args):
        if a in ("-X", "--method") and i + 1 < len(args):
            return args[i + 1].upper()
        if a.startswith("--method="):
            return a.split("=", 1)[1].upper()
        if a.startswith("-X") and len(a) > 2:
            return a[2:].upper()
    has_fields = any(a in ("-f", "-F", "--field", "--raw-field", "--input") or a.startswith(("--field=", "--raw-field="))
                     for a in args)
    return "POST" if has_fields else "GET"


def check_github_paths(args, method, tool="gh api"):
    for a in args:
        path = a.split("api.github.com", 1)[-1]
        if GITHUB_BLOCKED.search(path):
            raise Blocked(f"{tool} on deployments, environment approvals, rulesets, branch protection, secrets, "
                          "variables or environments is blocked. Ask the owner.")
        if HOLD_LABEL in a and method != "POST":
            raise Blocked(f"The {HOLD_LABEL} label is the owner's merge hold; agents may add it, never remove or change it.")
        if re.search(r"refs/heads/staging\b|heads/staging$", path):
            raise Blocked("Writing the staging branch directly is blocked; staging changes land through PRs.")
    joined = " ".join(args)
    if method != "GET":
        if any(REPO_ROOT_PATH.match(a.split("api.github.com", 1)[-1]) for a in args):
            raise Blocked("Changing repository settings is blocked (auto-merge, default branch and the like are owner settings).")
        if re.search(r"/issues/\d+/labels/?(\s|$)", joined + " ") and method in ("PUT", "DELETE"):
            raise Blocked("Replacing or clearing PR labels is blocked (the owner's hold label lives there).")
        if "/reviews" in joined and re.search(r"\bAPPROVE\b", joined):
            raise Blocked("Approving a PR is the owner's signal; agents never approve.")
        if re.search(r"(^|\s)(branch|base)=staging(\s|$)", joined) and re.search(r"/(contents|merges)(/|\s|$)", joined + " "):
            raise Blocked("Writing to the staging branch directly is blocked; staging changes land through PRs.")


def check_gh(args):
    if not args:
        return
    sub, rest = args[0], args[1:]
    if sub == "api":
        check_github_paths(rest, method_of(rest))
    elif sub in ("secret", "ruleset"):
        raise Blocked(f"gh {sub} is blocked: secrets and rulesets are owner-only.")
    elif sub == "variable" and rest and rest[0] in ("set", "delete"):
        raise Blocked("Changing repository variables is blocked (STAGING_AUTONOMY_ENABLED is an owner signal).")
    elif sub == "repo" and rest and rest[0] in ("edit", "delete", "rename", "archive"):
        raise Blocked("Changing repository settings is blocked.")
    elif sub == "auth" and rest and (rest[0] == "token" or "--show-token" in rest or "-t" in rest):
        raise Blocked("Printing the GitHub token is blocked.")
    elif sub == "pr" and rest:
        if rest[0] == "review" and any(a in ("--approve", "-a") for a in rest):
            raise Blocked("Approving a PR is the owner's signal; agents never approve.")
        if rest[0] == "merge" and "--admin" in rest:
            raise Blocked("Admin merges bypass branch protection and are blocked.")
        if rest[0] == "edit" and removes_hold(rest):
            raise Blocked(f"The {HOLD_LABEL} label is the owner's merge hold; agents may add it, never remove it.")
    elif sub == "issue" and rest and rest[0] == "edit" and removes_hold(rest):
        raise Blocked(f"The {HOLD_LABEL} label is the owner's merge hold; agents may add it, never remove it.")
    elif sub == "label" and any(HOLD_LABEL in a for a in rest):
        raise Blocked(f"The {HOLD_LABEL} label is the owner's merge hold; agents never change it.")


def removes_hold(args):
    for i, a in enumerate(args):
        value = a.split("=", 1)[1] if a.startswith("--remove-label=") else (
            args[i + 1] if a == "--remove-label" and i + 1 < len(args) else "")
        if HOLD_LABEL in value.split(","):
            return True
    return False


def current_branch(cwd):
    try:
        out = subprocess.run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=cwd or None,
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def is_staging_ref(ref, cwd):
    ref = ref.lstrip("+")
    if ref in ("HEAD", "@"):
        ref = current_branch(cwd)
    return ref in ("staging", "refs/heads/staging")


def check_git(args, cwd):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] in ("-C", "-c", "--git-dir", "--work-tree") and i + 1 < len(args):
            if args[i] == "-C":
                cwd = os.path.join(cwd or ".", args[i + 1])
            i += 2
        else:
            i += 1
    if i >= len(args) or args[i] != "push":
        return
    rest = args[i + 1:]
    flags = [a for a in rest if a.startswith("-")]
    positional = [a for a in rest if not a.startswith("-")]
    for f in flags:
        if f in ("-f", "--force", "--mirror") or f.startswith(("--force-with-lease", "--force-if-includes")) \
                or (re.fullmatch(r"-[a-zA-Z]+", f) and "f" in f[1:]):
            raise Blocked("Force pushes are blocked. Push a new commit or a new branch instead.")
    if any(f in ("--all", "--branches") for f in flags):
        raise Blocked("git push --all is blocked (it would push staging).")
    refspecs = positional[1:]
    for spec in refspecs:
        if spec.startswith("+"):
            raise Blocked("Force pushes are blocked. Push a new commit or a new branch instead.")
        dst = spec.split(":", 1)[1] if ":" in spec else spec
        if is_staging_ref(dst, cwd):
            raise Blocked("Direct pushes to staging are blocked; open a PR (the owner or CI merges).")
    if not refspecs and current_branch(cwd) == "staging":
        raise Blocked("Direct pushes to staging are blocked; open a PR (the owner or CI merges).")


def check_command(argv, cwd, depth=0):
    assigns, argv = strip_prefix(argv)
    if not argv:
        return
    name = PurePosixPath(argv[0]).name
    args = argv[1:]
    runner = args[:1] if name in ("npx", "bunx", "pnpx") else (
        args[1:2] if name in ("npm", "pnpm", "yarn", "bun") and args[:1] in (["exec"], ["dlx"], ["x"]) else [])
    if name == "railway" or any(a == "railway" or a.startswith("@railway/cli") for a in runner):
        raise Blocked("The Railway CLI is blocked in agent sessions. Use an ops runbook "
                      "(docs/agent/OPS_RUNBOOKS.md): GitHub Actions holds the staging credentials.")
    if name in PG_TOOLS:
        check_pg(name, args, assigns)
    check_env_print(name, args)
    check_files(argv)
    if name == "gh":
        check_gh(args)
    elif name == "git":
        check_git(args, cwd)
    elif name in ("curl", "wget", "http", "https"):
        if any("api.github.com" in a for a in args):
            check_github_paths([a for a in args if "api.github.com" in a],
                               "POST" if any(a in ("-X", "--request", "-d", "--data", "--data-raw") for a in args) else "GET",
                               tool=name)
    elif name in SHELLS and "-c" in args and depth < 3:
        body = args[args.index("-c") + 1] if args.index("-c") + 1 < len(args) else ""
        check_bash(body, cwd, depth + 1)
    elif name == "eval" and depth < 3:
        check_bash(" ".join(args), cwd, depth + 1)
    elif name == "xargs" and depth < 3:
        rest = [a for a in args if not a.startswith("-")]
        if rest:
            check_command(rest, cwd, depth + 1)


FALLBACK = re.compile(r"\brailway\b|\bprintenv\b|--force|\bpush\b.*\bstaging\b|\.env\b|pending_deployments|rulesets"
                      r"|/protection\b|/secrets\b|/environments\b|\bpsql\b|\bpg_dump\b")


def check_bash(command, cwd, depth=0):
    try:
        parsed = segments(command)
    except ValueError:
        if FALLBACK.search(command):
            raise Blocked("Command could not be parsed and touches a guarded area; simplify it.") from None
        return
    for argv in parsed:
        check_command(argv, cwd, depth)


# ---------------------------------------------------------------- file tools

def repo_root(cwd):
    root = os.environ.get("CLAUDE_PROJECT_DIR") or cwd or os.getcwd()
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root, capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            return Path(out.stdout.strip()).resolve()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return Path(root).resolve()


def lane_reason(rel, status, root):
    """scripts/product_lane.path_reason at the checkout: the single lane definition."""
    sys.path.insert(0, str(root / "scripts"))
    try:
        import product_lane
    finally:
        sys.path.pop(0)
    return product_lane.path_reason(rel, status)


def check_file_tool(tool, tool_input, cwd):
    raw = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path")
    if not raw:
        return
    if tool == "Read":
        if ENV_FILE.search(raw) and not ENV_EXAMPLE.search(raw):
            raise Blocked(".env files hold credentials; reading them is blocked (.env.example is fine).")
        return
    root = repo_root(cwd)
    path = Path(raw if os.path.isabs(raw) else os.path.join(cwd or str(root), raw)).resolve()
    if not path.is_relative_to(root):
        return
    rel = path.relative_to(root).as_posix()
    if os.environ.get("CARDPIRATE_LANE") == "data":
        return
    reason = lane_reason(rel, "M" if path.exists() else "A", root)
    if reason:
        raise Blocked(f"{LANE_MESSAGE} ({rel}: {reason}; scripts/product_lane.py)")


MCP_WRITES = {"mcp__github__push_files", "mcp__github__create_or_update_file", "mcp__github__delete_file"}


def check_mcp(tool, tool_input):
    if tool in MCP_WRITES and str(tool_input.get("branch", "")).removeprefix("refs/heads/") == "staging":
        raise Blocked("Writing the staging branch directly is blocked; staging changes land through PRs.")
    if tool == "mcp__github__pull_request_review_write" and str(tool_input.get("event", "")).upper() == "APPROVE":
        raise Blocked("Approving a PR is the owner's signal; agents never approve.")
    if tool == "mcp__github__merge_pull_request" and tool_input.get("admin"):
        raise Blocked("Admin merges bypass branch protection and are blocked.")
    if tool == "mcp__github__issue_write" and tool_input.get("method") == "update" \
            and isinstance(tool_input.get("labels"), list) and HOLD_LABEL not in tool_input["labels"]:
        # A label list replaces the whole set and can drop the owner's hold.
        raise Blocked(f"Replacing a PR label set can drop the {HOLD_LABEL} hold; use gh pr edit --add-label.")


def decide(event):
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    if tool == "Bash":
        check_bash(tool_input.get("command", ""), cwd)
    elif tool in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Read"):
        check_file_tool(tool, tool_input, cwd)
    elif tool.startswith("mcp__github__"):
        check_mcp(tool, tool_input)


def main():
    try:
        event = json.load(sys.stdin)
        decide(event)
    except Blocked as reason:
        print(f"Blocked by .claude/hooks/guard.py: {reason}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001 - fail closed
        print(f"Blocked by .claude/hooks/guard.py: guard error ({type(error).__name__}); the call was not checked.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
