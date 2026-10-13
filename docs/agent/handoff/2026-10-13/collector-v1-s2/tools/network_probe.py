"""Which analytics/Sentry requests a page makes. Usage: network_probe.py <base_url> <label>"""
import json, sys
from playwright.sync_api import sync_playwright
base, label = sys.argv[1].rstrip("/"), sys.argv[2]
out = {"label": label, "base": base, "pages": {}}
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for path in ["/", "/about", "/privacy"]:
        pg = b.new_page(); reqs = []; errors = []
        pg.on("request", lambda r: reqs.append(r.url))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(base + path, wait_until="load", timeout=90000); pg.wait_for_timeout(4000)
        out["pages"][path] = {
            "vercel_insights": [u.replace(base, "") for u in reqs if "/_vercel/insights" in u],
            "sentry_ingest": [u.split("?")[0] for u in reqs if "sentry.io" in u],
            "sentry_initialised": pg.evaluate("() => Boolean(window.__SENTRY__ && Object.keys(window.__SENTRY__).length)"),
            "console_errors": errors[:5],
        }
        pg.close()
    b.close()
print(json.dumps(out, indent=1))
