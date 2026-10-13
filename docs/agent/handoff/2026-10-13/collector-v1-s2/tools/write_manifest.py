"""Write docs/agent/STAGING_MISSION.json for the S2 PR, hashing the exact diff
the way scripts/staging_policy.py does. usage: write_manifest.py <base>"""
import json, subprocess, sys
sys.path.insert(0, "scripts")
import staging_policy
base = sys.argv[1]
files, digest = staging_policy.change_evidence(base, "HEAD")
def pick(pred):
    return sorted(f for f in files if pred(f))
web_pages = pick(lambda f: f.startswith(("apps/web/src/app/about/", "apps/web/src/app/methodology/", "apps/web/src/app/privacy/", "apps/web/src/app/terms/", "apps/web/src/components/info/")) or f in ("apps/web/src/components/Footer.tsx", "apps/web/src/lib/publicRoutes.ts"))
web_tests = pick(lambda f: f.startswith("apps/web/") and (".test." in f) )
api_tests = pick(lambda f: f.startswith("services/api/tests/"))
docs = pick(lambda f: f.startswith("docs/"))
api = pick(lambda f: f.startswith(("services/api/app/", "services/api/requirements-observability")) or f == "deploy/railway/api.Dockerfile")
web_obs = sorted(set(pick(lambda f: f.startswith("apps/web/"))) - set(web_pages) - set(web_tests))
impacts = [
    {"files": web_pages, "effects": ["application"],
     "reason": "New public pages /about and /methodology (indexable, in sitemap) and draft /privacy and /terms (noindex, visible 'Draft – under review' banner, operator 'Card Pirate', placeholders [CONTACT EMAIL] and [GOVERNING LAW]; owner decisions Q3/Q8). Footer links on every page. Methodology restates docs/market_value.md, market_index.md, INVARIANTS.md and collector_accounts.md: no pricing, Market Index or Market Value change. Static pages, no API reads. Draft legal text is not adopted; approval and removing noindex remain the owner's launch gate."},
    {"files": web_obs, "effects": ["application"],
     "reason": "Vercel Web Analytics (cookieless) mounted only when NEXT_PUBLIC_VERCEL_WEB_ANALYTICS=1; custom events limited to the nine in plan §F2 with properties allowlisted to page_type and release_code; path-only page views, admin/API paths never sent. Sentry (@sentry/nextjs 10.75.0) client/server/error boundary, no-op and CSP unchanged unless NEXT_PUBLIC_SENTRY_DSN is set; sendDefaultPii false, no tracing, replay or session pings; beforeSend scrubs Authorization, cookies, bodies, query strings and user; environment staging, release = build SHA. Admin-session-only /api/admin/observability/sentry-test raises a deliberate test error. Free tiers only (owner Q3). Neither is configured on staging at merge, so behaviour there is unchanged."},
    {"files": api, "effects": ["application", "infrastructure"],
     "reason": "API Sentry per plan §A rule 5: sentry-sdk==2.70.0 in services/api/requirements-observability.txt, installed only by deploy/railway/api.Dockerfile (two added lines). app.error_tracking is imported only by app.main, imports sentry_sdk lazily and is a no-op without SENTRY_DSN (unset on staging at merge). send_default_pii False, no locals, bodies, tracing or sessions; before_send scrubs credentials, cookies, queries and user. Admin-token GET /admin/observability/sentry-test raises on purpose (hidden from OpenAPI, writes nothing). No settings.py, app/models/** or requirements.txt change; collector import graph: 0 changed runtime inputs for snkrdunk and yuyutei."},
    {"files": web_tests + api_tests, "effects": ["tests"],
     "reason": "Page render and metadata (noindex and banner on drafts, canonical, sitemap membership), footer links, analytics allowlist/no-PII and page-view scrubbing, Sentry beforeSend scrubbing, no-op without DSN, CSP origin, admin test route auth, API scrubbing/no-op/options, requirements isolation, collector import-graph."},
]
if docs:
    impacts.append({"files": docs, "effects": ["documentation"], "reason": "ATLAS tranche contract for the info pages."})
covered = [f for i in impacts for f in i["files"]]
assert sorted(covered) == sorted(files) and len(covered) == len(set(covered)), (sorted(set(files) - set(covered)), covered)
mission = {
    "schema_version": 1,
    "mission": "Collector v1 S2: About, Methodology and draft Privacy/Terms pages with footer links; Vercel Web Analytics and Sentry (web and API) installed off-by-default, no collector release",
    "target": "staging",
    "classification": "AMBER",
    "red_decisions": {k: False for k in sorted(staging_policy.RED)},
    "impacts": impacts,
    "deployment_verification": {
        "api_sha": "merge",
        "revision": "3b7d9c1a5e20",
        "checks": ["scripts/verify_snkr_published_discovery_component.py", "scripts/verify_yuyu_raw_reader_component.py"],
        "snkr_component": "a504e476d98ab49ad7773a0c8c6b71e9d927b125",
        "yuyu_reader_component": "a504e476d98ab49ad7773a0c8c6b71e9d927b125",
        "yuyu_capacity_cadence": True,
    },
    "safeguards": {
        "impact": {
            "resources": [
                {"name": "Vercel project optcg-price-tracker-staging (web build)", "project_id": "prj_DCbF7bhFkkAdfMQLZWvOQbxEDDhr"},
                {"name": "Staging API (image gains sentry-sdk; inert without SENTRY_DSN)", "service_id": "5290becf-6956-4c5c-ab16-01d865587e07"},
            ],
            "routes": ["New: /about, /methodology, /privacy, /terms (static), /api/admin/observability/sentry-test (admin session), API GET /admin/observability/sentry-test (admin token). Footer on every page gains four links. No existing route changes."],
            "dependencies": ["@vercel/analytics 2.0.1", "@sentry/nextjs 10.75.0", "sentry-sdk 2.70.0 (API image only)"],
            "deployment_impact": "Web builds on merge through the Vercel Git integration. API, worker, beat and market-index-snapshot build through their normal GitHub triggers. No collector watch path or collector-imported module changes, so no collector build or rollout; collector_services is empty. No migration; revision stays 3b7d9c1a5e20.",
            "database_writes": 0,
            "source_requests": 0,
            "estimated_runtime_minutes": 10,
        },
        "recovery": {
            "artifact": subprocess.check_output(["git", "rev-parse", base], text=True).strip(),
            "procedure": "Native revert of this PR (web and API redeploy through their normal triggers). If DSN or analytics variables were added later, removing NEXT_PUBLIC_SENTRY_DSN / NEXT_PUBLIC_VERCEL_WEB_ANALYTICS (Vercel, then redeploy) and SENTRY_DSN (Railway API) switches both off without a revert.",
            "trigger": "verifier failure; any public page error or hydration error; any change in Market Value, Market Index or card/print responses; any collector deployment record after merge",
            "backup": "Not applicable: no database or persistent-state change.",
            "validation": [
                "apps/web/src/app/infoPages.test.tsx", "apps/web/src/lib/analytics.test.ts", "apps/web/src/lib/sentry.test.ts",
                "services/api/tests/test_error_tracking.py", "services/api/tests/test_error_tracking_import_graph.py",
            ],
        },
        "verification": {
            "required_checks": ["engineering-gate"],
            "post_change": ["scripts/verify_staging_delivery.py", "scripts/generate_staging_state.py"],
            "observation_window": "Delivery receipt with frontend and API at the merge, revision 3b7d9c1a5e20 and 0 collector deployments (Railway records); /about, /methodology 200 indexable, /privacy and /terms 200 noindex with banner; footer links on every page.",
        },
    },
    "diff_sha256": digest,
}
open(staging_policy.MANIFEST, "w").write(json.dumps(mission, indent=1, ensure_ascii=False) + "\n")
print(json.dumps(staging_policy.evaluate(mission, files, digest)))
