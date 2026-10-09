#!/usr/bin/env python3
"""Exact services/api runtime inputs of an installed collector image.

Read-only: inspects local Git objects only. No network, credentials or mutations.

Both collector images `pip install services/api`, which installs only the `app`
package (pyproject `packages.find include = ["app", "app.*"]`) and its package
data. A collector process can therefore only execute `app` modules reachable by
import from its own package. This module derives that set from the actual
import graph at a given commit, so continuity can ignore API modules that no
collector imports.

Fail closed: any unreadable commit, unparsable reachable module, unresolvable
`app` import or dynamic import makes `changed_runtime_inputs` treat every
change under the collector's full path set as a runtime change, exactly as the
previous whole-directory check did. Non-Python files under the installed
package, and packaging/requirements files, always count.
"""

import ast
import subprocess
from pathlib import PurePosixPath

import generate_staging_state as state

API = "services/api/"
APP = API + "app/"
# Installed-package metadata and dependency declarations always count.
API_ALWAYS = frozenset(
    API + name
    for name in ("pyproject.toml", "setup.py", "setup.cfg", "MANIFEST.in", "requirements.txt")
)
COLLECTORS = {
    "snkrdunk": {
        "root": "services/snkrdunk_collector/",
        "package": "snkrdunk_collector",
        "dockerfile": "deploy/railway/snkrdunk-collector.Dockerfile",
    },
    "yuyutei": {
        "root": "services/yuyutei_collector/",
        "package": "yuyutei_collector",
        "dockerfile": "deploy/railway/yuyutei-collector.Dockerfile",
    },
}
IDENTITY = "packages/opcg_source_identity/"
IDENTITY_SRC = IDENTITY + "src/"
# Untracked modules written by deploy_staging_collectors.build_markers at upload
# time. They carry only the deployed revision; Git has no source to compare.
GENERATED = frozenset({
    "app.services.collector_build",
    "snkrdunk_collector._delivery_revision",
    "yuyutei_collector._delivery_revision",
})
DYNAMIC = {"import_module", "__import__", "find_spec", "load_module", "spec_from_file_location"}


class Unresolvable(state.VerificationError):
    """The import set cannot be computed; callers must use the full path set."""


def full_paths(collector):
    """The previous whole-directory continuity inputs for one collector."""
    spec = COLLECTORS[collector]
    return (spec["root"].rstrip("/"), API.rstrip("/"), IDENTITY.rstrip("/"), spec["dockerfile"])


def _git(run, *args, input=None):
    try:
        if input is None:
            return run(["git", *args], cwd=state.ROOT, text=True)
        return run(["git", *args], cwd=state.ROOT, input=input)
    except (subprocess.CalledProcessError, OSError) as exc:
        raise Unresolvable(f"git {args[0]} failed: {exc}") from exc


def _tree(sha, collector, run):
    spec = COLLECTORS[collector]
    listed = _git(run, "ls-tree", "-r", "--name-only", sha, "--",
                  spec["root"], APP, IDENTITY_SRC).splitlines()
    files = [p for p in listed if p.endswith(".py")]
    if not any(p.startswith(spec["root"] + spec["package"] + "/") for p in files):
        raise Unresolvable("collector package missing at " + sha)
    blob = _git(run, "cat-file", "--batch",
                input="".join(f"{sha}:{p}\n" for p in files).encode())
    sources, offset = {}, 0
    for path in files:
        header_end = blob.index(b"\n", offset)
        header = blob[offset:header_end].split()
        if len(header) != 3 or header[1] != b"blob":
            raise Unresolvable("unreadable source " + path)
        size, start = int(header[2]), header_end + 1
        try:
            sources[path] = blob[start:start + size].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Unresolvable("undecodable source " + path) from exc
        offset = start + size + 1
    return sources


def _module_map(sources, collector):
    """Map dotted module names of the three installed roots to repo paths."""
    spec = COLLECTORS[collector]
    roots = {API: "", spec["root"]: "", IDENTITY_SRC: ""}
    modules = {}
    for path in sources:
        base = next(r for r in roots if path.startswith(r))
        parts = list(PurePosixPath(path[len(base):]).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        if parts:
            modules[".".join(parts)] = path
    return modules


def _owned(name, collector):
    top = name.split(".")[0]
    return top in {"app", "opcg_source_identity", COLLECTORS[collector]["package"]}


def _imports(path, source, modules):
    """Dotted names imported by one module, including function-local imports."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        raise Unresolvable("unparsable module " + path) from exc
    package = modules_package(path, modules)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".") if package else []
                if node.level - 1 > len(parts):
                    raise Unresolvable("relative import escapes package in " + path)
                parts = parts[: len(parts) - (node.level - 1)]
                base = ".".join(parts + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            names.append(base)
            # `from pkg import name` may name a submodule; include it when it is one.
            names.extend(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
        elif isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if called in DYNAMIC:
                raise Unresolvable(f"dynamic import in {path}:{node.lineno}")
    return names


def modules_package(path, modules):
    name = next((m for m, p in modules.items() if p == path), "")
    return name if path.endswith("/__init__.py") else name.rpartition(".")[0]


def runtime_inputs(sha, collector, *, run=subprocess.check_output):
    """Repo paths of every `app` module reachable from the collector at `sha`."""
    spec = COLLECTORS[collector]
    sources = _tree(sha, collector, run)
    modules = _module_map(sources, collector)
    pending = [p for p in sources if p.startswith(spec["root"])
               and "/tests/" not in "/" + p[len(spec["root"]):]]
    seen = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        for name in _imports(path, sources[path], modules):
            if not name or not _owned(name, collector) or name in GENERATED or name.rpartition(".")[0] in GENERATED:
                continue
            parts = name.split(".")
            found = False
            # Importing a.b.c executes a/__init__, a/b/__init__ and a/b/c.
            for i in range(1, len(parts) + 1):
                target = modules.get(".".join(parts[:i]))
                if target:
                    found = True
                    pending.append(target)
            if not found:
                raise Unresolvable(f"unresolved import {name} in {path}")
            if parts[0] == "app" and ".".join(parts) not in modules:
                # Only an attribute of an existing parent module is acceptable.
                parent = modules.get(".".join(parts[:-1]))
                if parent is None:
                    raise Unresolvable(f"unresolved import {name} in {path}")
    return frozenset(p for p in seen if p.startswith(APP))


def counts(path, inputs):
    """Whether a changed path can affect the installed collector runtime."""
    if not path.startswith(API):
        return True
    if path in API_ALWAYS:
        return True
    if path.startswith(APP):
        return not path.endswith(".py") or path in inputs
    # alembic/, tests/, scripts/, data/ and API service files are not installed.
    return False


def changed_runtime_inputs(component, head, collector, *, run=subprocess.check_output):
    """Changed paths between component and head that a collector can execute.

    Returns (changed, basis). On any Unresolvable condition every change under
    the collector's full path set is returned, as before this narrowing.
    """
    changed = run(
        ["git", "diff", "--name-only", component, head, "--", *full_paths(collector)],
        cwd=state.ROOT,
        text=True,
    ).split()
    if not changed:
        return [], "unchanged"
    try:
        # Union: a module imported at either commit is a runtime input.
        inputs = runtime_inputs(component, collector, run=run) | runtime_inputs(
            head, collector, run=run
        )
    except Unresolvable as exc:
        return changed, "full-path fallback: " + str(exc)
    return [p for p in changed if counts(p, inputs)], "import-graph"
