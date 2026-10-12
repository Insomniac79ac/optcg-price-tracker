import sys, json, re, html, urllib.request, urllib.parse, collections, datetime
BASE="https://optcg-price-tracker-staging.vercel.app"
def get(u, method="GET"):
    req=urllib.request.Request(u, method=method, headers={"User-Agent":"cardpirate-staging-check/1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.headers.get("content-type",""), (r.read() if method=="GET" else b""), r.url
    except urllib.error.HTTPError as e: return e.code, "", b"", u
    except Exception as e: return 0, str(e), b"", u
def origin(u):
    h=urllib.parse.urlparse(u)
    if h.hostname and h.hostname.endswith("r2.dev"): return "r2:"+h.hostname[:12]
    if "/api/card-image" in u: return "proxy:/api/card-image"
    if "/_next/image" in u:
        inner=urllib.parse.parse_qs(h.query).get("url",[""])[0]; return "next-image->"+origin(urllib.parse.urljoin(BASE,inner))
    return "other:"+(h.hostname or "relative")
out={"observed_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"pages":{}}
for p in sys.argv[1:]:
    st,ct,body,final=get(BASE+p); t=body.decode("utf-8","replace")
    srcs=[html.unescape(s) for s in re.findall(r'<img[^>]+src="([^"]+)"',t)]
    srcs=[urllib.parse.urljoin(BASE,s) for s in srcs if not s.startswith("data:")]
    og=[html.unescape(s) for s in re.findall(r'property="og:image" content="([^"]+)"',t)]
    by=collections.defaultdict(lambda:{"n":0,"broken":0}); broken=[]
    for s in srcs:
        o=origin(s); by[o]["n"]+=1
        ist,ict,b,_=get(s)
        if ist!=200 or not ict.startswith("image/") or len(b)<100: by[o]["broken"]+=1; broken.append([s,ist,ict])
    ogr=[]
    for o in og:
        ost,oct_,ob,_=get(o); ogr.append({"url":o,"status":ost,"type":oct_,"bytes":len(ob)})
    out["pages"][p]={"status":st,"images":len(srcs),"by_origin":dict(by),"broken":broken,"sample":srcs[:3],"og_image":ogr}
print(json.dumps(out,indent=1))
