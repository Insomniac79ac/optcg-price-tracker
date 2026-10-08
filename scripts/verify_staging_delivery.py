#!/usr/bin/env python3
"""Read-only, destination-pinned post-merge verification; no deploy or job triggers."""
import argparse
import fnmatch
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.request

import generate_staging_state as state

WEB = "https://optcg-price-tracker-staging.vercel.app"
API = "https://optcg-price-tracker-staging.up.railway.app"


def require(condition, message):
    if not condition:
        raise state.VerificationError(message)


def run_component_checks(checks, api_sha=None):
    paths = []
    for check in checks:
        path = (state.ROOT / check).resolve()
        require(
            path.is_relative_to(state.ROOT) and path.suffix == ".py",
            "Check must be a repository Python file",
        )
        paths.append(path)

    def run(path):
        # These two read-only checks explicitly wait up to one complete 30-min
        # staggered cron cycle. Give their own 1800s deadline a bounded cleanup
        # allowance. Other repository checks retain their existing 300s bound.
        natural = path.relative_to(state.ROOT).as_posix() in {
            "scripts/verify_snkr_published_discovery_component.py",
            "scripts/verify_yuyu_raw_reader_component.py",
        }
        env = dict(os.environ)
        if api_sha:
            # Checks reading api_sha=merge use the API source resolved here.
            env["STAGING_RESOLVED_API_SHA"] = api_sha
        subprocess.run(
            ["python", str(path)], check=True, timeout=1860 if natural else 300, env=env
        )

    # These checks only read provider/retained evidence, so adoption windows
    # overlap without invoking sources or changing any source concurrency.
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, paths))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise state.VerificationError(
            "Unexpected HTTP redirect; destination not verified"
        )


# A slow read-only GET may be retried after a socket timeout only. Callers
# apply the identical assertion to the retried response; every other failure
# (HTTP status, redirect, content, invariant) still fails immediately.
TIMEOUT_RETRIES = 2
TIMEOUT_BACKOFF_SECONDS = (2, 5)
timeout_retries = []


def is_timeout(error):
    if isinstance(error, TimeoutError):
        return True
    return (isinstance(error, urllib.error.URLError)
            and not isinstance(error, urllib.error.HTTPError)
            and isinstance(error.reason, TimeoutError))


def get(url):
    require(url.startswith((WEB + "/", API + "/")), "Non-staging URL refused")
    for attempt in range(TIMEOUT_RETRIES + 1):
        try:
            return fetch(url)
        except Exception as error:
            if not is_timeout(error) or attempt == TIMEOUT_RETRIES:
                raise
            timeout_retries.append({"url": url, "attempt": attempt + 1})
            time.sleep(TIMEOUT_BACKOFF_SECONDS[attempt])


def fetch(url):
    opener = urllib.request.build_opener(NoRedirect)
    try:
        response = opener.open(url, timeout=30)
    except urllib.error.HTTPError as error:
        if error.code != 429:
            raise
        delay = int(error.headers.get("Retry-After", "0"))
        require(0 < delay <= 300, "API rate limit has no bounded retry window")
        # One retry at the server's own reset boundary, never an evasion/bypass.
        while delay > 0:
            interval = min(delay, 30)
            time.sleep(interval)
            delay -= interval
        response = opener.open(url, timeout=30)
    with response:
        data = json.load(response)
        if url.startswith(API):
            # Stay below the public read budget; never fan out against the API.
            delay = 1.1
            remaining = response.headers.get("X-RateLimit-Remaining")
            reset = response.headers.get("X-RateLimit-Reset")
            if remaining is not None and reset is not None and int(remaining) < 10:
                delay = max(delay, float(reset) - time.time() + 1)
            while delay > 0:
                interval = min(delay, 30)
                time.sleep(interval)
                delay -= interval
        return data


def validate_state(evidence, expected, api_sha, revision):
    evidence = state.sanitize(evidence)
    require(evidence["railway"]["project_id"] == state.PROJECT
            and evidence["railway"]["environment_id"] == state.ENVIRONMENT,
            "Wrong Railway destination")
    require(evidence["mode"] == "live", "Fixture evidence is not a live verification")
    require(evidence["repository"]["sha"] == expected, "Staging moved during verification")
    frontend = evidence["frontend"]
    require(isinstance(frontend, dict) and frontend["sha"] == expected
            and frontend["status"] == "READY", "Frontend deployment is not the expected commit")
    api = next(s for s in evidence["railway"]["services"] if s["name"] == "optcg-price-tracker")
    require(api["git_sha"] == api_sha and api["status"] == "SUCCESS", "Unexpected API deployment")
    db = evidence["database"]
    require([r["version_num"] for r in db["revision"]] == [revision], "Migration revision differs")
    require(4000 <= db["coverage"][0]["canonical_variants"] <= 5000, "Catalogue count outside reviewed range")
    require(db["duplicate_active_exact_print_source_groups"] == 0, "Duplicate active exact-print/source mappings")
    require(all(r["intentional_gap_rows"] == 0 for r in db["market_value"]), "Immutable Market Value gap filled")


def sale_audit():
    """Fresh staging credentials in memory; PostgreSQL enforces read-only access."""
    import psycopg
    from psycopg.rows import dict_row
    proxies = state.railway(f'query {{ tcpProxies(environmentId:"{state.ENVIRONMENT}", serviceId:"{state.POSTGRES}") {{ domain proxyPort applicationPort }} }}')["tcpProxies"]
    require(len(proxies) == 1 and proxies[0]["applicationPort"] == 5432, "Ambiguous staging DB proxy")
    variables = state.command_json(["railway", "variable", "list", "-p", state.PROJECT,
                                    "-e", state.ENVIRONMENT, "-s", state.POSTGRES, "--json"])
    try:
        with psycopg.connect(host=proxies[0]["domain"], port=proxies[0]["proxyPort"],
                            user=variables["PGUSER"], password=variables["PGPASSWORD"],
                            dbname=variables["PGDATABASE"], connect_timeout=15,
                            options="-c default_transaction_read_only=on -c statement_timeout=30000") as connection:
            connection.read_only = True
            connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            checks = state.guard.evaluate(state.guard.collect_facts(connection),
                                          state.guard.expected_revisions_from_repo(str(state.ROOT)))
            require(all(c.ok for c in checks), "Staging database fingerprint failed")
            connection.row_factory = dict_row
            sales = connection.execute("""select p.card_print_id, array_agg(p.id) ids
                from price_observations p join sources s on s.id=p.source_id
                join card_prints cp on cp.id=p.card_print_id
                where s.name='yuyutei' and p.promotion_state='sale' and cp.is_active
                group by p.card_print_id""").fetchall()
            invalid = connection.execute("""select count(*) n from market_index_snapshots m,
                jsonb_array_elements(m.provenance::jsonb->'source_values') v
                where m.source_semantics_version>=3 and v->>'source'='yuyutei'
                and (v->>'constraint'='sale_price' or v->>'ineligible_reason'='sale_price')
                and (v->>'eligible'='true' or v->>'contributes_to_index'='true'
                     or (v->>'value_jpy') is not null)""").fetchone()["n"]
            receipts = connection.execute("""select count(*) n from market_index_snapshot_completions
                where snapshot_date in ('2026-09-27','2026-09-28')""").fetchone()["n"]
            connection.rollback()
        require(invalid == 0, "Sale evidence eligible for Market Index / Market Value")
        require(receipts == 0, "Unexpected receipts for intentional historical gaps")
        require(bool(sales), "Sale audit has no representative evidence")
        print(f"Checking public sale exclusion for {len(sales)} active prints", flush=True)
        def verify_sale(row):
            printing = row["card_print_id"]
            history = get(f"{API}/prints/{printing}/prices")
            require(not set(row["ids"]) & {p["id"] for p in history["observations"]},
                    "Sale observation exposed in public history")
            index = get(f"{API}/prints/{printing}/market-index")
            for value in index["source_values"]:
                if value.get("source") == "yuyutei" and value.get("constraint") == "sale_price":
                    require(value.get("value_jpy") is None and value.get("eligible") is False
                            and value.get("contributes_to_index") is False, "Sale price exposed publicly")
        for row in sales:
            verify_sale(row)
        return {"public_sale_histories_checked": len(sales), "sale_index_inputs": invalid,
                "gap_receipts": receipts}
    finally:
        variables.clear()


def browser_check():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        errors = []
        page = browser.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text)
                if message.type == "error" and re.search("hydration|react error", message.text, re.I) else None)
        results = []
        for route in ("/", "/prints/5661", "/analytics"):
            response = page.goto(WEB + route, wait_until="networkidle", timeout=60000)
            require(response is not None and response.status == 200, f"Route failed: {route}")
            require(page.locator("h1").count() > 0, f"Missing rendered page: {route}")
            results.append(route)
        require(not errors, "Browser runtime/hydration errors")
        browser.close()
        return results


API_SERVICE = "5290becf-6956-4c5c-ab16-01d865587e07"
SKIPPED = "SKIPPED"


def watched(path, patterns):
    """Railway watch-pattern match. Over-matching only demands a build (fail closed)."""
    for pattern in patterns:
        pattern = pattern.lstrip("/")
        if pattern.endswith("/**") and path.startswith(pattern[:-2]):
            return True
        if fnmatch.fnmatchcase(path, pattern):
            return True
    return False


def decide_api(merge, changed, patterns, merge_status, active_sha, unchanged):
    """Expected API source for a merge whose manifest says api_sha=merge.

    changed: files in merge^1..merge, or None if undeterminable.
    merge_status: Railway status of the API deployment for the merge commit,
    or None if Railway has not recorded one yet.
    unchanged(sha): True when every watched path is identical in sha and merge.
    Returns ("build", merge), ("skip", previous_sha) or ("pending", None).
    """
    determinable = (changed is not None and patterns
                    and not any(p.startswith("!") for p in patterns))
    must_build = not determinable or any(watched(f, patterns) for f in changed)
    if must_build:
        require(merge_status != SKIPPED, "Expected API build missing: Railway skipped the merge")
        return "build", merge
    if merge_status is None:
        return "pending", None
    require(merge_status == SKIPPED and active_sha != merge,
            "Unexpected API build for a change outside its watch paths")
    require(bool(re.fullmatch("[0-9a-f]{40}", active_sha or "")) and unchanged(active_sha),
            "Skipped API source is not the verified previous build")
    return "skip", active_sha


def api_merge_status(merge, railway=None):
    railway = railway or state.railway
    rows = railway(
        f'query {{ deployments(first:20, input:{{projectId:"{state.PROJECT}", '
        f'environmentId:"{state.ENVIRONMENT}", serviceId:"{API_SERVICE}"}}) '
        f'{{ edges {{ node {{ status createdAt meta }} }} }} }}'
    )["deployments"]["edges"]
    for row in rows:  # newest first
        meta = row["node"].get("meta") or {}
        meta = json.loads(meta) if isinstance(meta, str) else meta
        if meta.get("commitHash") == merge:
            return row["node"]["status"]
    return None


def api_watch_patterns(railway=None):
    railway = railway or state.railway
    row = railway(
        f'query {{ serviceInstance(environmentId:"{state.ENVIRONMENT}", '
        f'serviceId:"{API_SERVICE}") {{ watchPatterns }} }}'
    )["serviceInstance"]
    return list(row.get("watchPatterns") or [])


def changed_files(merge):
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "--no-renames", merge + "^1", merge],
            cwd=state.ROOT, text=True)
    except (subprocess.CalledProcessError, OSError):
        return None
    files = [line for line in out.splitlines() if line]
    return files or None


def tree_unchanged(merge, patterns):
    def check(sha):
        paths = [p.lstrip("/").removesuffix("/**") for p in patterns]
        result = subprocess.run(["git", "diff", "--quiet", sha, merge, "--", *paths],
                                cwd=state.ROOT)
        return result.returncode == 0
    return check


def resolve_api_sha(merge, deadline, *, collect=None, status=api_merge_status,
                    patterns=api_watch_patterns, changed=changed_files, unchanged=tree_unchanged,
                    clock=time.monotonic, sleep=time.sleep):
    """Resolve manifest api_sha=merge, accepting a legitimately skipped API build."""
    collect = collect or state.collect_live
    watch = patterns()
    files = changed(merge)
    while True:
        evidence = state.sanitize(collect())
        api = next(s for s in evidence["railway"]["services"] if s["name"] == "optcg-price-tracker")
        mode, sha = decide_api(merge, files, watch, status(merge), api["git_sha"],
                               unchanged(merge, watch))
        if mode != "pending":
            return {"mode": mode, "sha": sha, "watch_patterns": watch,
                    "watched_changes": sorted(f for f in files or [] if watched(f, watch))}
        require(clock() < deadline, "Railway recorded no API deployment decision for the merge")
        sleep(min(15, max(0, deadline - clock())))


def wait_for_delivery(expected, api_sha, deadline, *, collect=None, clock=time.monotonic,
                      sleep=time.sleep):
    """Native API and frontend builds finish independently of collector upload."""
    collect = collect or state.collect_live
    while True:
        evidence = state.sanitize(collect())
        require(evidence["mode"] == "live", "Fixture evidence is not a live verification")
        require(evidence["railway"]["project_id"] == state.PROJECT
                and evidence["railway"]["environment_id"] == state.ENVIRONMENT,
                "Wrong Railway destination")
        require(evidence["repository"]["sha"] == expected, "Staging moved during verification")
        frontend = evidence["frontend"]
        api = next(s for s in evidence["railway"]["services"] if s["name"] == "optcg-price-tracker")
        if (isinstance(frontend, dict) and frontend.get("sha") == expected
                and frontend.get("status") == "READY"
                and api["git_sha"] == api_sha and api["status"] == "SUCCESS"):
            return evidence
        require(clock() < deadline, "Expected native staging deployments did not become ready")
        sleep(min(15, max(0, deadline-clock())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--api-sha", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wait-seconds", type=int, default=900)
    parser.add_argument("--scope", type=Path, help="Delivery scope decision evidence to embed")
    parser.add_argument("--check", action="append", default=[], help="Repository Python verification script; runs without shell interpolation")
    args = parser.parse_args()
    require(re.fullmatch("[0-9a-f]{40}", args.expected)
            and (args.api_sha == "merge" or re.fullmatch("[0-9a-f]{40}", args.api_sha)),
            "Full expected source SHAs required")
    scope = json.loads(args.scope.read_text()) if args.scope else None
    deadline = time.monotonic() + args.wait_seconds
    api_expectation = {"mode": "declared", "sha": args.api_sha}
    if args.api_sha == "merge":
        # A build Railway legitimately skipped keeps its verified previous source;
        # a missing expected build or an unexpected build still fails.
        api_expectation = resolve_api_sha(args.expected, deadline)
        args.api_sha = api_expectation["sha"]
    evidence = wait_for_delivery(args.expected, args.api_sha, deadline)
    version = get(WEB + "/api/version")
    require(version["web"].get("source_commit") == args.expected,
            "Frontend runtime SHA disagrees with platform")
    health, api_version = get(API + "/health"), get(API + "/version")
    require(health.get("app_env") == "staging" and health.get("status") == "ok"
            and health.get("database_connected") and health.get("redis_connected"), "Staging API health failed")
    require(api_version.get("app_env") == "staging", "API destination is not staging")
    require(api_version.get("git_commit") in (args.api_sha, "unknown"), "API runtime SHA disagrees with platform")
    get(WEB + "/api/auth/session")
    evidence = state.collect_live()
    validate_state(evidence, args.expected, args.api_sha, args.revision)
    # Warm the route cache before the paced invariant audit. A single cold
    # render previously missed a homepage shell mismatch after ISR regeneration.
    browser_check()
    sale = sale_audit()
    routes = browser_check()
    run_component_checks(args.check, args.api_sha)
    # Re-read after browser/data checks, so a competing deployment cannot be called success.
    evidence = state.collect_live()
    validate_state(evidence, args.expected, args.api_sha, args.revision)
    # The preceding provider reads also allow background regeneration from
    # the warm browser pass to settle before the final browser assertion.
    browser_check()
    require(get(WEB + "/api/version")["web"].get("source_commit") == args.expected, "Frontend changed during verification")
    snapshot = state.write_snapshot(evidence, state.CANONICAL_OUTPUT)
    result = {"verified_at": state.timestamp(), "expected_commit": args.expected,
              "frontend": evidence["frontend"], "api": api_version,
              "api_identity_basis": "Railway deployment metadata; runtime SHA may be unknown",
              "migration_revision": args.revision, "routes": routes, "sale_invariant": sale,
              "state_evidence_sha256": snapshot["evidence"]["sha256"],
              "get_timeout_retries": {"count": len(timeout_retries), "requests": timeout_retries},
              "delivery_scope": scope,
              "api_expectation": api_expectation,
              "production_accessed": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except state.VerificationError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        # Provider/driver diagnostics may contain credentials or private URLs.
        raise SystemExit(f"Staging verification failed ({type(error).__name__}); no success receipt written") from None
