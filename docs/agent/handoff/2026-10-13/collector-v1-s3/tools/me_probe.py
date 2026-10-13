"""Read-only: unauthenticated GETs to every /me GET route on the staging API.
With COLLECTOR_ACCOUNTS_ENABLED off each must answer 404 (before authentication).
usage: me_probe.py > out.json"""
import datetime, json, urllib.error, urllib.request
API = "https://optcg-price-tracker-staging.up.railway.app"
PATHS = ["/me/collection", "/me/collection/value?window=7d", "/me/collection/value?window=30d",
         "/me/watchlist", "/me/preferences", "/me/export",
         "/me/export/collection.csv", "/me/export/watchlist.csv"]
def get(path):
    req = urllib.request.Request(API + path, headers={"User-Agent": "cardpirate-s3-probe"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(200).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(200).decode("utf-8", "replace")
out = {"observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "api": API,
       "health": get("/health"), "me": {p: get(p) for p in PATHS}}
out["all_me_404"] = all(v[0] == 404 for v in out["me"].values())
print(json.dumps(out, indent=1))
