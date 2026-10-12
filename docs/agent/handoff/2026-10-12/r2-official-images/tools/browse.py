import sys, json, collections, datetime, urllib.parse
from playwright.sync_api import sync_playwright
BASE="https://optcg-price-tracker-staging.vercel.app"
def origin(u):
    h=urllib.parse.urlparse(u)
    if h.hostname and h.hostname.endswith("r2.dev"): return "r2:"+h.hostname[:12]
    if "/api/card-image" in u: return "proxy:/api/card-image"
    if "/_next/image" in u: return "next-image->"+origin(urllib.parse.urljoin(BASE,urllib.parse.parse_qs(h.query).get("url",[""])[0]))
    return "other:"+(h.hostname or "?")+h.path[:40]
out={"observed_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"pages":{}}
with sync_playwright() as p:
    b=p.chromium.launch()
    for path in sys.argv[1:]:
        for vp,name in (({"width":1440,"height":900},"desktop"),({"width":390,"height":844},"mobile")):
            pg=b.new_page(viewport=vp); fails=[]
            pg.on("response", lambda r: fails.append([r.url,r.status]) if r.request.resource_type=="image" and r.status>=400 else None)
            r=pg.goto(BASE+path, wait_until="networkidle", timeout=60000)
            for _ in range(6): pg.mouse.wheel(0,1500); pg.wait_for_timeout(400)
            pg.wait_for_load_state("networkidle")
            imgs=pg.eval_on_selector_all("img","els=>els.map(e=>({src:e.currentSrc||e.src,ok:e.complete&&e.naturalWidth>0}))")
            imgs=[i for i in imgs if i["src"] and not i["src"].startswith("data:")]
            by=collections.defaultdict(lambda:{"n":0,"broken":0})
            for i in imgs:
                o=origin(i["src"]); by[o]["n"]+=1; by[o]["broken"]+= (not i["ok"])
            if name=="desktop": pg.screenshot(path=f"{sys.argv[0].rsplit('/',1)[0]}/shot{path.replace('/','_') or '_root'}.png")
            out["pages"][f"{path} [{name}]"]={"status":r.status,"images":len(imgs),"by_origin":dict(by),"broken":[i["src"] for i in imgs if not i["ok"]][:5],"http_image_errors":fails[:5]}
            pg.close()
    b.close()
print(json.dumps(out,indent=1))
