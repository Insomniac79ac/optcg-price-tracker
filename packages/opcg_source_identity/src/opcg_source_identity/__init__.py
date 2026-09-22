"""Pure listing identity; raw URLs remain evidence, CardPrint remains pricing identity.

These are the authoritative, deliberately narrow historical URL parsers.
Do not infer identity for unsupported hosts, legacy card-code URLs or titles.
"""

import re

_SNKRDUNK = re.compile(
    r"^https://snkrdunk\.com/(?:apparels|en/trading-cards)/(\d+)(?:[/?#].*)?$"
)
_YUYUTEI = re.compile(
    r"^https://yuyu-tei\.jp/sell/opc/card/([a-z0-9][a-z0-9-]*)/(\d+)(?:[/?#].*)?$"
)


def snkrdunk_listing_id(url: str | None) -> str | None:
    match = _SNKRDUNK.match(url.strip()) if url else None
    return match.group(1) if match else None


def yuyutei_listing_identity(url: str | None) -> tuple[str, str] | None:
    match = _YUYUTEI.match(url.strip()) if url else None
    return (match.group(1).lower(), match.group(2)) if match else None


def canonical_source_listing_identity(source_name: str, source_url: str | None) -> str | None:
    name = source_name.strip().lower()
    if name == "snkrdunk":
        return snkrdunk_listing_id(source_url)
    if name == "yuyutei":
        identity = yuyutei_listing_identity(source_url)
        return ":".join(identity) if identity else None
    return None
