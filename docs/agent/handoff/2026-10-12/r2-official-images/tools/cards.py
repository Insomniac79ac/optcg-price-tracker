import json, urllib.request
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={"width":1440,"height":900})
    pg.goto("https://optcg-price-tracker-staging.vercel.app/cards", wait_until="networkidle")
    info=pg.eval_on_selector_all("img","els=>els.map(e=>({src:e.currentSrc||e.src,loading:e.loading,complete:e.complete,w:e.naturalWidth,top:Math.round(e.getBoundingClientRect().top)}))")
    first=[i for i in info if not(i["complete"] and i["w"]>0)]
    print("not loaded before scroll:",len(first),"lazy:",sum(i["loading"]=="lazy" for i in first),"min top:",min([i["top"] for i in first] or [0]))
    for i in range(40):
        pg.evaluate("window.scrollBy(0,400)"); pg.wait_for_timeout(250)
    pg.wait_for_timeout(3000)
    info2=pg.eval_on_selector_all("img","els=>els.map(e=>({src:e.currentSrc||e.src,ok:e.complete&&e.naturalWidth>0}))")
    bad=[i["src"] for i in info2 if not i["ok"]]
    print("after slow scroll: total",len(info2),"not loaded",len(bad))
    for u in bad[:5]:
        with urllib.request.urlopen(u,timeout=30) as r: print(r.status,r.headers.get("content-type"),len(r.read()))
    b.close()
