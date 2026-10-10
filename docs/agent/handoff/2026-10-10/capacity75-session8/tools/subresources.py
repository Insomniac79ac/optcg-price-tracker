"""Read-only: classify static subresource references in retained RAW pages.

Decodes through the installed package reader. Makes no source request.
Usage: subresources.py <plaintext raw_snapshot_id> ...
"""
import sys, json, re
from collections import Counter
from urllib.parse import urljoin, urlsplit
sys.path[:0] = ['/workspaces/cp-s8/scripts', '/workspaces/cp-s8/services/api']
sys.path.insert(0, '/workspaces/cp-s8/docs/agent/handoff/2026-10-10/capacity75-session8/tools')
from db import connection
from bs4 import BeautifulSoup
PREFIX = 'OPCG_RAW_ZSTD_V1:'  # opcg_source_identity.raw_payload.PREFIX

def body(db, sid):
    r = db.execute("select id, source_url, raw_content from raw_snapshots where id=%s", (sid,)).fetchone()
    if r['raw_content'].startswith(PREFIX):
        raise SystemExit(f'{sid} is an encoded envelope; pass a plaintext anchor')
    return r['source_url'], r['raw_content']

def classify(url, html):
    s = BeautifulSoup(html, 'html.parser')
    out = Counter(); hosts = Counter()
    def add(kind, ref):
        if not ref or ref.startswith('data:'): return
        u = urljoin(url, ref); out[kind] += 1; hosts[(kind, urlsplit(u).hostname)] += 1
    for t in s.find_all('script', src=True): add('script', t['src'])
    for t in s.find_all('link', href=True):
        rel = ' '.join(t.get('rel', [])).lower()
        if 'stylesheet' in rel: add('stylesheet', t['href'])
        elif 'preload' in rel or 'modulepreload' in rel: add('preload:' + (t.get('as') or 'module'), t['href'])
        elif 'icon' in rel: add('icon', t['href'])
    for t in s.find_all('iframe', src=True): add('iframe', t['src'])
    for t in s.find_all('img'): add('img', t.get('src'))
    inline = len([t for t in s.find_all('script') if not t.get('src')])
    return {'url': url, 'html_bytes': len(html.encode()), 'static': dict(out), 'inline_scripts': inline,
            'by_host': {f'{k}|{h}': n for (k, h), n in sorted(hosts.items())}}

with connection() as db:
    for sid in map(int, sys.argv[1:]):
        u, h = body(db, sid)
        print(json.dumps({'raw_snapshot_id': sid, **classify(u, h)}, ensure_ascii=False))
