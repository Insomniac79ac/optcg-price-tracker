import json, sys
from playwright.sync_api import sync_playwright
base = "https://optcg-price-tracker-staging.vercel.app"
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
    ctx = b.new_context(user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
    for path in ["/", "/about", "/methodology", "/privacy", "/terms", "/cards"]:
        pg = ctx.new_page(); reqs = []
        pg.on("request", lambda r: reqs.append((r.method, r.url.replace(base, ""), r.post_data or "")))
        resp = {}
        pg.on("response", lambda r: resp.__setitem__(r.url.replace(base, ""), r.status))
        pg.goto(base + path + "?utm_probe=s2&email=x@example.com", wait_until="networkidle"); pg.wait_for_timeout(5000)
        va = [(m, u, resp.get(u), pd[:300]) for m, u, pd in reqs if "393b56be60fdc62b" in u]
        out[path] = {"webdriver": pg.evaluate("() => navigator.webdriver"), "va_requests": va}
        pg.close()
    b.close()
print(json.dumps(out, indent=1))
