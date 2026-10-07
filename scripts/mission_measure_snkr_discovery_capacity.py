import json, time, resource
from snkrdunk_collector.published_discovery import (
    locations,
    neighbours,
    listing_identity,
)

start = time.monotonic()
shards = {}
anchors = []
max_bytes = 0
for shard in range(12):
    count = 33334 if shard < 4 else 33333
    urls = [
        f"https://snkrdunk.com/en/trading-cards/{1000000+shard*100000+i}"
        for i in range(count)
    ]
    body = (
        "<urlset>" + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>"
    ).encode()
    max_bytes = max(max_bytes, len(body))
    shard_url = f"https://snkrdunk.com/en/sitemap/sitemap-en-product-trading-card-single-{shard}.xml"
    shards[shard_url] = locations(body, index=False)
    anchors.append(listing_identity(urls[count // 2]))
parsed = time.monotonic()
result = neighbours(shards, anchors, set(), radius_start=1, radius_end=48, limit=20)
print(
    json.dumps(
        {
            "mock_only": True,
            "source_requests": 0,
            "database_writes": 0,
            "shards": len(shards),
            "locations": sum(map(len, shards.values())),
            "max_document_bytes": max_bytes,
            "products": len(result),
            "parse_seconds": parsed - start,
            "plan_seconds": time.monotonic() - parsed,
            "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "transport_limit": "SDK buffers before parser bounds; not a hard download cap",
        }
    )
)
