"""Read-only signed-out admin checks on staging (no credentials). Usage: admin_signed_out.py"""
import json, datetime, urllib.request, urllib.error
WEB = "https://optcg-price-tracker-staging.vercel.app"
API = "https://optcg-price-tracker-staging.up.railway.app"
PAGES = ["actions", "alerts", "backup", "cache", "card-audit", "card-duplicates", "cards", "catalog-coverage", "catalog-ops",
         "collection-attempts", "data-retention", "file-jobs", "import-validation", "job-locks", "logs", "performance",
         "price-source-health", "refresh-runs", "release-status", "snkrdunk-candidates", "source-mapping-proposals",
         "source-mapping-quality", "system-check", "market-workflow-runs"]
API_KEPT = ["/admin/release-status", "/admin/observability/summary", "/admin/data-retention/policy"]
API_DELETED = ["/admin/market-workflow-runs", "/market/signals", "/market/opportunities", "/market/report/latest",
               "/dashboard/overview", "/search?q=luffy", "/analytics/digest/latest", "/analytics/buy-decisions"]
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
op = urllib.request.build_opener(NoRedirect)
def get(url):
    try:
        r = op.open(urllib.request.Request(url, headers={"User-Agent": "cardpirate-s1-check/1"}), timeout=30); return r.status, r.headers.get("location")
    except urllib.error.HTTPError as e: return e.code, e.headers.get("location")
out = {"observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "signed_in": False,
       "web_admin_pages": {p: get(f"{WEB}/admin/{p}") for p in PAGES}, "web_admin_login": get(f"{WEB}/admin/login"),
       "api_admin_kept_no_token": {p: get(API + p)[0] for p in API_KEPT}, "api_deleted_no_token": {p: get(API + p)[0] for p in API_DELETED},
       "web_api_deleted": {p: get(WEB + "/api" + p) for p in ["/admin/market-workflow-runs", "/market/signals", "/search?q=luffy", "/dashboard/overview"]}}
print(json.dumps(out, indent=1))
