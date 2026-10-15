#!/usr/bin/env python3
"""Classify a staging change as PRODUCT lane or DATA lane from local Git only.

Read-only: no network, credentials or mutations. Owner decision 2026-10-15
(docs/agent/AUTONOMY_POLICY.md "Delivery lanes").

PRODUCT lane: every changed path is on the product allowlist (apps/web, API code
outside the collector import graph that does not touch price, identity, Market
Value or Index, tests, docs, PRODUCT_LOG), no path is a collector runtime input
at either commit, the change does not edit the mission manifest, and any new
migration is purely additive on unprotected tables.

Anything else, and any doubt (unreadable Git, unresolvable import graph,
unparsable migration), is DATA lane, which keeps today's mission-manifest checks
unchanged. Callers must treat an exception as DATA.
"""
import argparse
import ast
import functools
import json
from pathlib import PurePosixPath
import re
import subprocess
import sys

MANIFEST = "docs/agent/STAGING_MISSION.json"
PRODUCT_LOG = "docs/agent/PRODUCT_LOG.md"
API_APP = "services/api/app/"
MIGRATIONS = "services/api/alembic/versions/"
# Price, identity, mapping/proposal, Market Value, Card Pirate Index, raw evidence,
# sources and collection pipelines. Matched against API module paths and table names.
PROTECTED_TERMS = (
    "price", "market", "index", "value", "valuation", "identity", "mapping", "proposal",
    "source", "snkrdunk", "yuyutei", "observation", "canonical", "catalog", "print",
    "raw", "freshness", "snapshot", "alias", "candidate", "discovery", "official",
    "artwork", "release", "collect_", "backup", "restore", "retention", "merge",
)
# Explicit allowlist of collector-facing API modules (relative to services/api/app/).
# Everything else under app/ (wiring such as main.py and schemas.py, models,
# card/catalogue/price/Index/source code, scripts) is DATA. A listed module is
# still DATA if its name has a protected term or a collector imports it.
PRODUCT_API = {
    "accounts/__init__.py", "accounts/config.py", "accounts/models.py",
    "accounts/router.py", "accounts/schemas.py", "accounts/service.py",
    "web_cors.py", "error_tracking.py",
    "api/collection.py", "api/wishlist.py", "api/saved_views.py", "api/collector_notes.py",
    "api/collector_activity.py", "api/file_jobs.py", "api/grading.py", "api/alerts.py",
    "api/health.py", "api/version.py",
}
# Tables a product migration may extend (collector accounts, S3) besides the
# tables it creates itself. Foreign keys may also point at users.id.
PRODUCT_TABLES = {"collection_entries", "collection_entry_events", "watchlist_entries",
                  "user_preferences"}
FK_TARGETS = PRODUCT_TABLES | {"users"}
# Authentication and security surfaces: product lane, but one independent review
# pass is mandatory and must be recorded in the PR description.
SECURITY = re.compile(
    r"auth(?!orit)|session|token|csrf|cors|secret|login|jwt|proxy|security|permission"
    r"|middleware|next\.config|accounts/"
    # Build and supply chain of the web app run with Vercel build variables.
    r"|package(-lock)?\.json$|\.npmrc$|dockerfile|^apps/web/scripts/"
)
SECURITY_REVIEW = re.compile(r"^\s*Independent security review:\s*\S+", re.I | re.M)
# Migration allowlist: the only op.* calls, and the only sa.* constructors.
CREATE_OPS = {"create_table"}
EXTEND_OPS = {"add_column", "create_index", "create_unique_constraint", "create_check_constraint"}
SA_CALLS = {"Column", "Integer", "BigInteger", "SmallInteger", "Text", "String", "Boolean",
            "DateTime", "Date", "Numeric", "JSON", "Uuid", "ForeignKey", "PrimaryKeyConstraint",
            "UniqueConstraint", "CheckConstraint", "Index", "text", "now"}
MODULE_NAMES = {"revision", "down_revision", "branch_labels", "depends_on"}


def git(*args):
    return subprocess.check_output(["git", *args], text=True)


def changes(base, head):
    """(status, paths) rows for what the PR itself changes (merge-base to head)."""
    out = git("diff", "--name-status", "-M", "-z", f"{base}...{head}")
    fields = out.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    rows, i = [], 0
    while i < len(fields):
        status = fields[i]
        width = 2 if status[:1] in ("R", "C") else 1
        paths = fields[i + 1:i + 1 + width]
        if not status or len(paths) != width or not all(paths):
            raise ValueError("Malformed name-status output")
        rows.append((status, paths))
        i += 1 + width
    return rows


def protected(text):
    text = text.lower()
    return any(term in text for term in PROTECTED_TERMS)


def path_reason(path, status):
    """None when the path may be PRODUCT lane, else why it is DATA lane."""
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts:
        return "unsafe path"
    if path == MANIFEST:
        return "declares a data-lane mission manifest"
    if path.startswith("apps/web/"):
        if p.name == "vercel.json":
            return "deployment configuration (infrastructure)"
        return None
    if path.startswith("services/api/tests/"):
        return None
    if path.startswith(API_APP):
        rel = path[len(API_APP):]
        if not rel.endswith(".py"):
            return "installed API package data"
        if protected(rel):
            return "price, identity, Market Value, Index or source code"
        if rel not in PRODUCT_API:
            return "API module outside the product allowlist"
        return None
    if path.startswith(MIGRATIONS) and path.endswith(".py"):
        return None if status == "A" else "edits or removes an existing migration"
    if path == PRODUCT_LOG or path.startswith("docs/ui/"):
        return None
    if path.startswith("docs/") and not path.startswith("docs/agent/"):
        return None
    return "outside the product-lane paths"


def collector_inputs(base, head, files):
    """Changed API paths that either collector image can execute (import graph).

    Collector, identity-package and Dockerfile paths are already DATA by path.
    An unresolvable graph raises, which callers treat as DATA lane.
    """
    import collector_runtime_inputs as cri
    hits = set()
    for collector in cri.COLLECTORS:
        inputs = _runtime_inputs(_resolve(base), collector) | _runtime_inputs(_resolve(head), collector)
        hits.update(p for p in files if p.startswith(cri.API) and cri.counts(p, inputs))
    return sorted(hits)


@functools.lru_cache(maxsize=None)
def _runtime_inputs(sha, collector):
    import collector_runtime_inputs as cri
    return cri.runtime_inputs(sha, collector)


def _tables(sources):
    names = set()
    for source in sources:
        names.update(re.findall(r"__tablename__\s*=\s*[\"']([^\"']+)[\"']", source))
        names.update(re.findall(r"create_table\(\s*[\"']([^\"']+)[\"']", source))
    return names


@functools.lru_cache(maxsize=None)
def _sources(sha, prefix):
    """{path: text} of the .py files under prefix at sha, in one cat-file call."""
    paths = [p for p in git("ls-tree", "-r", "--name-only", sha, "--", prefix).splitlines()
             if p.endswith(".py")]
    blob = subprocess.run(["git", "cat-file", "--batch"], input="".join(f"{sha}:{p}\n" for p in paths).encode(),
                          capture_output=True, check=True).stdout
    out, offset = {}, 0
    for path in paths:
        end = blob.index(b"\n", offset)
        header = blob[offset:end].split()
        if len(header) != 3 or header[1] != b"blob":
            raise ValueError("unreadable " + path)
        size, start = int(header[2]), end + 1
        out[path] = blob[start:start + size].decode("utf-8")
        offset = start + size + 1
    return out


def _resolve(rev):
    return git("rev-parse", rev).strip()


def existing_tables(base):
    """Every table any model or migration at base names."""
    sha = _resolve(base)
    return _tables([*_sources(sha, API_APP).values(), *_sources(sha, MIGRATIONS).values()])


def _revision_links(rev):
    """{revision: down_revision} for the migrations at rev."""
    links = {}
    for text in _sources(_resolve(rev), MIGRATIONS).values():
        r = re.search(r"^revision(?::\s*str)?\s*=\s*[\"']([^\"']+)[\"']", text, re.M)
        d = re.search(r"^down_revision(?::\s*[^=]+)?\s*=\s*(?:[\"']([^\"']+)[\"']|None)", text, re.M)
        if r:
            links[r.group(1)] = d.group(1) if d else None
    return links


def heads(rev):
    links = _revision_links(rev)
    return sorted(set(links) - {d for d in links.values() if d})


def _literal(node):
    return node.value if isinstance(node, ast.Constant) else None


def _sa_call(func):
    """sa.X(...) or sa.func.now()."""
    if isinstance(func, ast.Attribute) and func.attr in SA_CALLS:
        value = func.value
        if isinstance(value, ast.Name) and value.id == "sa":
            return True
        return (func.attr == "now" and isinstance(value, ast.Attribute) and value.attr == "func"
                and isinstance(value.value, ast.Name) and value.value.id == "sa")
    return False


def migration_problems(source, existing):
    """Why a new migration is not a plain additive one on product tables.

    Allowlist, not denylist: module body is imports of op/sa, literal revision
    assignments, upgrade() and downgrade(); upgrade() is only op.create_table of
    new tables and op.add_column/create_index/constraints on tables it creates or
    on PRODUCT_TABLES; every nested call is an allowlisted sa.* constructor.
    """
    tree = ast.parse(source)
    problems = []
    upgrade = None
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(_literal(node.value), str):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "alembic" and node.level == 0 \
                and [(a.name, a.asname) for a in node.names] == [("op", None)]:
            continue
        if isinstance(node, ast.Import) and [(a.name, a.asname) for a in node.names] == [("sqlalchemy", "sa")]:
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if all(isinstance(t, ast.Name) and t.id in MODULE_NAMES for t in targets) \
                    and isinstance(node.value, ast.Constant):
                continue
        if isinstance(node, ast.FunctionDef) and node.name in ("upgrade", "downgrade") \
                and not node.args.args and not node.decorator_list:
            if node.name == "upgrade":
                upgrade = node
            continue
        problems.append(f"module statement at line {node.lineno} is not allowed")
    if upgrade is None:
        return problems + ["no upgrade()"]
    created = set()
    for stmt in upgrade.body:
        call = stmt.value if isinstance(stmt, ast.Expr) else None
        func = getattr(call, "func", None)
        if not (isinstance(call, ast.Call) and isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name) and func.value.id == "op"
                and func.attr in CREATE_OPS | EXTEND_OPS):
            problems.append(f"upgrade() line {stmt.lineno}: only op.create_table/add_column/"
                            "create_index/create_*_constraint calls are allowed")
            continue
        index = 1 if func.attr in ("create_index", "create_unique_constraint", "create_check_constraint") else 0
        table = _literal(call.args[index]) if len(call.args) > index else None
        if not isinstance(table, str):
            problems.append(f"op.{func.attr} line {stmt.lineno}: table name must be a literal")
            continue
        if func.attr == "create_table":
            if table in existing or protected(table):
                problems.append(f"op.create_table {table}: table exists or is protected")
            created.add(table)
        elif table not in created and table not in PRODUCT_TABLES:
            problems.append(f"op.{func.attr} on {table}: not a product table")
        if func.attr == "add_column":
            col = call.args[1] if len(call.args) > 1 else None
            kw = {k.arg: k.value for k in getattr(col, "keywords", [])}
            positional = getattr(col, "args", [])[2:]
            if positional or not ("server_default" in kw or _literal(kw.get("nullable")) is True):
                problems.append(f"op.add_column on {table}: needs nullable=True or a server_default "
                                "(keywords only)")
        for node in ast.walk(call):
            if node is call or not isinstance(node, ast.Call):
                continue
            if not _sa_call(node.func):
                problems.append(f"line {node.lineno}: call is not an allowlisted sa.* constructor")
            elif node.func.attr == "ForeignKey":
                target = _literal(node.args[0]) if node.args else None
                if not isinstance(target, str) or target.split(".")[0] not in FK_TARGETS | created:
                    problems.append(f"line {node.lineno}: foreign key target {target!r} not allowed")
    return problems


def classify(base, head, pr_body="", *, require_security_review=True):
    rows = changes(base, head)
    files = sorted({p for _, paths in rows for p in paths})
    result = {"lane": "data", "files": files, "reasons": [], "migrations": [],
              "security_paths": [], "security_review_required": False}
    if not rows:
        result["reasons"].append("empty change set")
        return result
    reasons = []
    for status, paths in rows:
        for path in paths:
            why = path_reason(path, status[0])
            if why:
                reasons.append(f"{path}: {why}")
    inputs = collector_inputs(base, head, files)
    reasons.extend(f"{p}: collector runtime input (import graph)" for p in inputs)
    migrations = [p for p in files if p.startswith(MIGRATIONS) and p.endswith(".py")]
    if migrations:
        existing = existing_tables(base)
        for path in migrations:
            try:
                problems = migration_problems(git("show", f"{head}:{path}"), existing)
            except SyntaxError:
                problems = ["unparsable migration"]
            reasons.extend(f"{path}: {p}" for p in problems)
        # One new migration, chained onto the base head, leaving one head.
        base_heads, new_heads = heads(base), heads(head)
        new_links = {r: d for r, d in _revision_links(head).items() if r not in _revision_links(base)}
        if len(migrations) != 1 or len(base_heads) != 1 or len(new_heads) != 1 \
                or list(new_links.values()) != base_heads:
            reasons.append(f"product migrations: exactly one, on base head {base_heads}, "
                           f"leaving one head (found {new_heads})")
    security = [p for p in files if SECURITY.search(p.lower())]
    if security and require_security_review and not SECURITY_REVIEW.search(pr_body or ""):
        reasons.append("auth/security paths need an 'Independent security review: <link or summary>' "
                       "line in the PR description: " + ", ".join(security))
    result.update(reasons=reasons, migrations=migrations, security_paths=security,
                  security_review_required=bool(security))
    if not reasons:
        result["lane"] = "product"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--pr-body-file")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    body = open(args.pr_body_file, encoding="utf-8").read() if args.pr_body_file else ""
    try:
        result = classify(args.base, args.head, body)
    except Exception as exc:  # Fail closed: any doubt is DATA lane.
        result = {"lane": "data", "reasons": [f"classification undetermined ({type(exc).__name__}: {exc})"]}
    text = json.dumps(result, indent=2)
    print(text)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
