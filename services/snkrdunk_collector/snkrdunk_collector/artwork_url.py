"""Classify artwork locators without promoting missing pixels to a match."""

import re
from urllib.parse import urljoin, urlsplit

from opcg_source_identity import snkrdunk_listing_id

_PLACEHOLDER = re.compile(r"(?:^|/)(?:no[-_]?image|placeholder)(?:[._-]|$)", re.I)


def artwork_url(value: str | None, product_url: str) -> tuple[str | None, str | None]:
    if not value or not value.strip():
        return None, "missing_image_url"
    value = value.strip()
    try:
        parsed = urlsplit(value)
        if _PLACEHOLDER.search(parsed.path):
            return None, "placeholder_image_url"
        if not parsed.scheme and not parsed.netloc:
            # Only root-relative assets have unambiguous product-origin semantics.
            origin = urlsplit(product_url)
            if (
                not value.startswith("/")
                or value.startswith("//")
                or not snkrdunk_listing_id(product_url)
            ):
                return None, "invalid_image_url"
            value = urljoin(f"{origin.scheme}://{origin.netloc}/", value)
            parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or "\\" in value
        ):
            return None, "invalid_image_url"
        return value, None
    except ValueError:
        return None, "invalid_image_url"
