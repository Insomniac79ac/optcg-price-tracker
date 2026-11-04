"""Owner-confirmed SNKRDUNK photos the artwork check refused (owner 2026-11-04, plan B).

The collector refuses a capture when the listing photo fails its average-hash test against the
mapped print's official image (artwork.compare_artwork). On 2026-11-02 that refused 49 of 208 newly
approved mappings; for mapping 4456 the hashes were average 24 (limit 12), dhash 9, phash 14, and
the owner, looking at the photo and the print, identified it (and 4423, 4356) as the right card.
The owner decided a person's identification beats the matcher for these ("a manual identification
to match would be more accurate", 2026-11-03).

A confirmation is honoured only for exactly what the owner looked at: this mapping, still on this
print, still for this listing, showing this exact photo URL (the collector's own main-image reading
of the page, as snkr-refused-photos reports it). A changed photo, a remapped listing or a different
print is checked by the matcher again. It replaces nothing else: card code, release, rarity,
language and treatment checks all still apply, and a missing or unreadable photo still refuses.
The confirmations live in the committed file next to this module, reviewed by PR.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

CONFIRMATIONS_FILE = Path(__file__).with_name("owner_artwork_confirmations.json")
MAX_CONFIRMATIONS = 500
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def confirmations(path: Path = CONFIRMATIONS_FILE) -> dict[tuple[int, int, str], dict]:
    """{(mapping_id, card_print_id, listing): entry} from the committed file (fail closed)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("confirmations"), list):
        raise ValueError("unrecognized owner artwork confirmations file")
    entries = data["confirmations"]
    if len(entries) > MAX_CONFIRMATIONS:
        raise ValueError("owner artwork confirmations exceed bound")
    out: dict[tuple[int, int, str], dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("every confirmation must be an object")
        ids_ok = all(isinstance(entry.get(k), int) and not isinstance(entry.get(k), bool) and entry[k] > 0
                     for k in ("mapping_id", "card_print_id"))
        text_ok = all(isinstance(entry.get(k), str) and entry[k] for k in ("listing", "photo_url", "confirmed_on"))
        if not (ids_ok and text_ok and entry.get("confirmed_by") == "owner" and entry.get("verdict") == "same"
                and _DATE.fullmatch(entry["confirmed_on"]) and entry["photo_url"].startswith("https://")):
            raise ValueError("every confirmation needs mapping_id, card_print_id, listing, an https photo_url, "
                             "confirmed_by owner, verdict same and a confirmed_on date")
        key = (entry["mapping_id"], entry["card_print_id"], entry["listing"])
        if key in out:
            raise ValueError("one confirmation per mapping, print and listing")
        out[key] = entry
    return out


def confirm(comparison: dict, *, mapping_id: int, card_print_id: int | None, listing: str | None,
            photo_url: str | None, entries: dict | None = None) -> dict:
    """The comparison, turned into an owner-confirmed match when (and only when) the matcher compared
    two fetched images, refused, and the owner confirmed exactly this mapping, print, listing and
    photo. Any other comparison is returned unchanged."""
    # hash_distances exists only when both images were fetched and decoded and the matcher compared
    # them; an unreadable or missing photo is never confirmable.
    if comparison.get("match") or "hash_distances" not in comparison or comparison.get("error"):
        return comparison
    if card_print_id is None or not listing or not photo_url:
        return comparison
    entry = (confirmations() if entries is None else entries).get((mapping_id, card_print_id, listing))
    if entry is None or entry["photo_url"] != photo_url:
        return comparison
    return {**comparison, "match": True,
            "owner_confirmed": {"confirmed_on": entry["confirmed_on"], "photo_url": photo_url}}
