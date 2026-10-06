"""Recover the page's single primary gallery URL from retained server props.

Image aborts can invoke the site's onError replacement before DOM capture.
Parse JSON data only, never execute scripts or use recommendation/variant
images. The collector still fetches and verifies the actual artwork normally.
"""

import json
import re
from urllib.parse import urlsplit


def primary_gallery_url(soup):
    chunks = []
    for script in soup.find_all("script"):
        body = script.string or ""
        match = re.fullmatch(r"\s*self\.__next_f\.push\((\[.*\])\)\s*;?\s*", body, re.S)
        if not match:
            continue
        try:
            value = json.loads(match.group(1))
        except (ValueError, TypeError):
            return None
        if (
            isinstance(value, list)
            and len(value) == 2
            and value[0] == 1
            and isinstance(value[1], str)
        ):
            chunks.append(value[1])
    payload = "".join(chunks)
    if not payload or len(payload.encode()) > 4 * 1024 * 1024:
        return None
    records = payload.splitlines()
    if len(records) > 5000:
        return None
    modules, elements, keys = set(), [], set()
    for line in records:
        key, separator, encoded = line.partition(":")
        if not separator or not re.fullmatch(r"[0-9a-f]+", key):
            continue
        module = encoded.startswith("I")
        try:
            value = json.loads(encoded[1:] if module else encoded)
        except (ValueError, TypeError):
            continue  # unrelated Flight text/reference records aren't JSON
        if key in keys:
            return None
        keys.add(key)
        if (
            module
            and isinstance(value, list)
            and value
            and value[-1] == "ApparelGalleryContainer"
        ):
            modules.add("$L" + key)
        elif (
            isinstance(value, list)
            and len(value) == 4
            and value[0] == "$"
            and isinstance(value[1], str)
            and isinstance(value[3], dict)
        ):
            elements.append(value)
    galleries = [v[3] for v in elements if v[1] in modules]
    if len(galleries) != 1:
        return None
    gallery = galleries[0]
    images, variants = gallery.get("mainImages"), gallery.get("variantSources")
    if (
        not isinstance(images, list)
        or len(images) != 1
        or not isinstance(images[0], dict)
        or not isinstance(variants, list)
        or not 1 <= len(variants) <= 50
    ):
        return None
    url = images[0].get("src")
    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.netloc != "cdn.snkrdunk.com"
        or parsed.fragment
        or parsed.query
        or not re.fullmatch(
            r"/upload_bg_removed/[A-Za-z0-9_-]+\.(?:webp|png|jpg)", parsed.path
        )
    ):
        return None
    matches = [v for v in variants if isinstance(v, dict) and v.get("imageUrl") == url]
    if (
        len(matches) != 1
        or type(matches[0].get("productId")) is not int
        or matches[0]["productId"] <= 0
    ):
        return None
    return url
