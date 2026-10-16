#!/usr/bin/env python3
"""Signed-out Playwright smoke of the staging website after a delivery. Read-only, no sign-in.

Checks, against the pinned staging alias only:
- public pages render (HTTP 200, an <h1>): /, /cards, one /prints page, /sign-in;
- /account, /collection and /watchlist, signed out, land on /sign-in with the original path
  as callbackUrl (the proxy guard), never on the protected page;
- card images load: every <img> on /cards and the /prints page that the browser loaded has a
  non-zero natural size, at least one card image loaded on each, and no image response failed;
- no page error or hydration error in the browser.
Writes a JSON receipt; exit 1 on any failure. scripts/verify_staging_delivery.py's own
browser check (/, /prints/5661, /analytics) is unchanged.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlsplit

WEB = "https://optcg-price-tracker-staging.vercel.app"
PUBLIC = ("/", "/cards", "/prints/5661", "/sign-in")
SIGNED_OUT = ("/account", "/collection", "/watchlist")
IMAGE_PAGES = ("/cards", "/prints/5661")


def redirect_ok(final_url, path, base=WEB):
    """Did a signed-out visit to ``path`` land on /sign-in?callbackUrl=<path> on the same site?"""
    url, origin = urlsplit(final_url), urlsplit(base)
    return ((url.scheme, url.netloc) == (origin.scheme, origin.netloc) and url.path == "/sign-in"
            and parse_qs(url.query).get("callbackUrl") == [path])


def image_problems(images, failed_responses):
    """Problems from [{src, complete, width}] of a page's loaded images and failed image URLs."""
    problems = [f"broken image {i['src'][:120]}" for i in images if i["complete"] and i["width"] == 0]
    if not any(i["complete"] and i["width"] > 0 for i in images):
        problems.append("no card image loaded")
    problems.extend(f"image response {status} {url[:120]}" for url, status in failed_responses)
    return problems


# Images in the first viewport only: lazy images further down are not requested yet.
IMAGES_JS = """() => Array.from(document.images).filter(i => {
  const r = i.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && r.top < innerHeight && r.bottom > 0;
}).map(i => ({src: i.currentSrc || i.src, complete: i.complete, width: i.naturalWidth}))"""


def smoke(base=WEB):
    from playwright.sync_api import sync_playwright

    result = {"base": base, "pages": {}, "problems": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        errors, failed = [], []
        page.on("pageerror", lambda error: errors.append(str(error)[:200]))
        page.on("console", lambda m: errors.append(m.text[:200])
                if m.type == "error" and re.search("hydration|react error", m.text, re.I) else None)
        page.on("response", lambda r: failed.append((r.url, r.status))
                if r.request.resource_type == "image" and r.status >= 400 else None)
        for path in PUBLIC:
            failed.clear()
            response = page.goto(base + path, wait_until="networkidle", timeout=60000)
            row = {"status": response.status if response else None, "h1": page.locator("h1").count() > 0,
                   "final_path": urlsplit(page.url).path}
            if row["status"] != 200 or not row["h1"] or row["final_path"] != path:
                result["problems"].append(f"{path}: status {row['status']}, h1 {row['h1']}, landed on {row['final_path']}")
            if path in IMAGE_PAGES:
                page.wait_for_timeout(1500)
                images = page.evaluate(IMAGES_JS)
                row["images_loaded"] = sum(1 for i in images if i["complete"] and i["width"] > 0)
                result["problems"].extend(f"{path}: {p}" for p in image_problems(images, list(failed)))
            result["pages"][path] = row
        for path in SIGNED_OUT:
            response = page.goto(base + path, wait_until="networkidle", timeout=60000)
            row = {"status": response.status if response else None, "final_url_path": urlsplit(page.url).path,
                   "redirected_to_sign_in": redirect_ok(page.url, path, base)}
            if not row["redirected_to_sign_in"] or row["status"] != 200:
                result["problems"].append(f"{path}: signed-out visit did not land on /sign-in?callbackUrl={path}")
            result["pages"][path] = row
        browser.close()
    result["problems"].extend(f"browser error: {e}" for e in errors)
    result["ok"] = not result["problems"]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = smoke()
    except Exception as error:  # noqa: BLE001 - browser/driver text can be long; keep the type
        result = {"base": WEB, "ok": False, "problems": [f"smoke failed to run ({type(error).__name__})"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
