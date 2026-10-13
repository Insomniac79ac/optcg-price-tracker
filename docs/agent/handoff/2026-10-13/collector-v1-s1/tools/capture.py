"""Before/after capture on staging (read-only GETs). Usage: capture.py <label> <outdir>"""
import sys, json, hashlib, datetime, urllib.request, urllib.error
from pathlib import Path
from playwright.sync_api import sync_playwright
WEB = "https://optcg-price-tracker-staging.vercel.app"
API = "https://optcg-price-tracker-staging.up.railway.app"
label, out = sys.argv[1], Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
PAGES = ["/", "/analytics", "/cards", "/prints/5661", "/market/movers"]
DELETED = ["/analytics/buy-decisions", "/analytics/sell-decisions", "/analytics/portfolio-risk", "/analytics/grading",
           "/analytics/digest", "/grading", "/market/signals", "/market/signal-events", "/market/opportunities",
           "/market/report", "/market/report/latest", "/dashboard", "/activity", "/search", "/search?q=luffy",
           "/admin/market-workflow-runs"]
APIS = ["/analytics/market-value?window=7d", "/analytics/market-value?window=30d", "/analytics/market-value/releases",
        "/analytics/market-value/movers", "/market/movers", "/releases"]
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
opener = urllib.request.build_opener(NoRedirect)
def head(url):
    try:
        r = opener.open(urllib.request.Request(url, headers={"User-Agent": "cardpirate-s1-check/1"}), timeout=30)
        return r.status, r.headers.get("location")
    except urllib.error.HTTPError as e: return e.code, e.headers.get("location")
res = {"label": label, "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "deleted_urls": {}, "api": {}, "pages": {}}
for p in DELETED: res["deleted_urls"][p] = dict(zip(("status", "location"), head(WEB + p)))
for p in APIS:
    try:
        b = urllib.request.urlopen(API + p, timeout=30).read()
        d = json.loads(b)
        for k in ("generated_at", "observed_at", "served_at", "retrieved_at"):
            if isinstance(d, dict): d.pop(k, None)
        res["api"][p] = {"status": 200, "sha256_normalized": hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest(), "bytes": len(b)}
    except urllib.error.HTTPError as e: res["api"][p] = {"status": e.code}
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for p in PAGES:
        for name, vp in (("desktop", {"width": 1440, "height": 900}), ("mobile", {"width": 390, "height": 844})):
            pg = b.new_page(viewport=vp); errs = []
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            r = pg.goto(WEB + p, wait_until="networkidle", timeout=60000)
            pg.wait_for_timeout(1500)
            f = out / f"{label}{p.replace('/', '_') or '_root'}-{name}.png"
            pg.screenshot(path=str(f), full_page=True)
            imgs = pg.eval_on_selector_all("img", "els=>els.filter(e=>e.complete&&e.naturalWidth===0).length")
            res["pages"][f"{p} [{name}]"] = {"status": r.status, "title": pg.title(), "broken_images": imgs, "console_errors": errs[:5], "shot": f.name}
            pg.close()
    b.close()
print(json.dumps(res, indent=1))
