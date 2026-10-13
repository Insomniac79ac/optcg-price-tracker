"""S2 before/after capture (read-only GETs). Usage: capture.py <label> <outdir> [base_url]

Full-page and footer screenshots at desktop 1440 and mobile 390, plus status,
title, robots meta, X-Robots-Tag, the draft banner and footer links per page.
"""
import datetime, json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

label, out = sys.argv[1], Path(sys.argv[2])
base = (sys.argv[3] if len(sys.argv) > 3 else "https://optcg-price-tracker-staging.vercel.app").rstrip("/")
out.mkdir(parents=True, exist_ok=True)
PAGES = ["/", "/cards", "/analytics", "/about", "/methodology", "/privacy", "/terms"]
res = {"label": label, "base": base, "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "pages": {}}
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for p in PAGES:
        for name, vp in (("desktop", {"width": 1440, "height": 900}), ("mobile", {"width": 390, "height": 844})):
            pg = b.new_page(viewport=vp); errs = []
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            r = pg.goto(base + p, wait_until="networkidle", timeout=90000)
            pg.wait_for_timeout(1200)
            stem = f"{label}{p.replace('/', '_') if p != '/' else '_root'}-{name}"
            pg.screenshot(path=str(out / f"{stem}.png"), full_page=True)
            footer = pg.query_selector("footer")
            if footer:
                footer.screenshot(path=str(out / f"{stem}-footer.png"))
            res["pages"][f"{p} [{name}]"] = {
                "status": r.status,
                "x_robots_tag": r.headers.get("x-robots-tag"),
                "title": pg.title(),
                "robots_meta": pg.eval_on_selector_all("meta[name=robots]", "els=>els.map(e=>e.content)"),
                "canonical": pg.eval_on_selector_all("link[rel=canonical]", "els=>els.map(e=>e.href)"),
                "draft_banner": pg.eval_on_selector_all("[data-draft-banner]", "els=>els.map(e=>e.innerText.trim())"),
                "footer_links": pg.eval_on_selector_all("footer a", "els=>els.map(e=>[e.innerText.trim(), e.getAttribute('href')])"),
                "h1": pg.eval_on_selector_all("h1", "els=>els.map(e=>e.innerText.trim())"),
                "horizontal_overflow": pg.evaluate("document.documentElement.scrollWidth > window.innerWidth"),
                "broken_images": pg.eval_on_selector_all("img", "els=>els.filter(e=>e.complete&&e.naturalWidth===0).length"),
                "console_errors": errs[:5],
                "shot": f"{stem}.png",
            }
            pg.close()
    b.close()
(out / f"{label}.json").write_text(json.dumps(res, indent=1) + "\n")
print(json.dumps({k: [v["status"], v["robots_meta"], len(v["footer_links"])] for k, v in res["pages"].items()}, indent=0))
