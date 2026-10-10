"""Read-only, offline: replay a retained RAW page in local Chromium with EVERY
network request aborted, and record what the browser tries to request.

No source request is made: the main document is fulfilled from the retained
RAW body; every other request is recorded and route.abort()ed before dispatch.
Each recorded request is then classified with the production metering rules
(app.services.freshness_integration.unnecessary_browser_resource /
browser_request_role / request_host_class) to show which would be metered.

Limits: only requests the retained (post-render) DOM and its INLINE scripts
initiate are visible. Requests that external scripts would make (XHR/fetch,
script-injected scripts) and CSS url()/@import children cannot be observed,
because those scripts/styles are aborted here.

Usage: replay_requests.py <raw_snapshot_id> ...   (plaintext anchors)
Output includes metered_urls so cross-page overlap (cacheable repeats) can be computed.
"""
import sys, json
from collections import Counter
from urllib.parse import urlsplit

sys.path[:0] = ['/workspaces/cp-s8/packages/opcg_source_identity/src', '/workspaces/cp-s8/scripts', '/workspaces/cp-s8/services/api']
sys.path.insert(0, '/workspaces/cp-s8/docs/agent/handoff/2026-10-10/capacity75-session8/tools')
from db import connection
from app.services.freshness_integration import (
    unnecessary_browser_resource, browser_request_role, request_host_class)
from playwright.sync_api import sync_playwright

PREFIX = 'OPCG_RAW_ZSTD_V1:'


def load(sid):
    with connection() as db:
        r = db.execute("select source_url, raw_content from raw_snapshots where id=%s", (sid,)).fetchone()
    if r['raw_content'].startswith(PREFIX):
        raise SystemExit(f'{sid} is encoded; pass a plaintext anchor')
    return r['source_url'], r['raw_content']


def replay(p, url, html):
    seen = []
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(service_workers='block')
    served = {'doc': False}

    def handler(route):
        req = route.request
        main = req.is_navigation_request() and req.frame == req.frame.page.main_frame
        if main and not served['doc'] and req.url == url:
            served['doc'] = True
            route.fulfill(status=200, content_type='text/html; charset=utf-8', body=html)
            return
        seen.append({
            'url': req.url[:160], 'host': urlsplit(req.url).hostname,
            'resource_type': req.resource_type, 'main_navigation': bool(main),
            'dropped_unmetered': bool(unnecessary_browser_resource(req)),
            'role': browser_request_role(req, main)[0],
            'host_class': request_host_class(req.url),
        })
        route.abort('blockedbyclient')  # nothing leaves this machine

    ctx.route('**/*', handler)
    ctx.route_web_socket('**/*', lambda ws: ws.close())
    page = ctx.new_page()
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(1500)
    except Exception as exc:  # noqa: BLE001
        seen.append({'error': str(exc)[:200]})
    ctx.close(); browser.close()
    return seen


def summarise(rows):
    rows = [r for r in rows if 'error' not in r]
    metered = [r for r in rows if not r['dropped_unmetered']]
    return {
        'attempted_total': len(rows),
        'dropped_unmetered_total': len(rows) - len(metered),
        'metered_total': len(metered),
        'metered_by_type': dict(Counter(r['resource_type'] for r in metered)),
        'metered_by_host': dict(Counter(f"{r['resource_type']}|{r['host']}" for r in metered)),
        'dropped_by_type': dict(Counter(r['resource_type'] for r in rows if r['dropped_unmetered'])),
        'dropped_by_host': dict(Counter(r['host'] for r in rows if r['dropped_unmetered'])),
        'metered_urls': sorted({r['url'] for r in metered}),
    }


if __name__ == '__main__':
    with sync_playwright() as p:
        for sid in map(int, sys.argv[1:]):
            url, html = load(sid)
            rows = replay(p, url, html)
            print(json.dumps({'raw_snapshot_id': sid, 'url': url, **summarise(rows),
                              'errors': [r for r in rows if 'error' in r]}, ensure_ascii=False))
