"""Raw evidence snapshot of the Japanese official Card List, and its analysis.

This is the *evidence* layer. It records what Bandai published, and computes
descriptive statistics over it. It resolves nothing into Atlas identity, and
writes no canonical row - no CanonicalCard, ReleaseProduct, CardPrint,
SourceCardMapping or pricing data is created, read for writing, or touched.

Why a snapshot at all
---------------------
Task 4B-1's planner reads the catalogue live, one card at a time. That is fine
for planning eight card codes and hopeless for the whole database: it would
re-fetch thousands of assets on every test run, and it makes "what did Bandai
say last week?" unanswerable. So the raw layer is written to disk once, in a
form that supports deterministic tests, later diffing when Bandai updates, and
re-parsing without re-fetching.

The layout
----------
    manifest.json                     one run: counts, per-series status, errors
    series.jsonl                      one record per catalogue grouping
    entries.jsonl                     one record per card *occurrence*
    assets.jsonl                      one record per distinct source URL
    pages/<series_id>.html.gz         the page source itself
    images/sha256/<ab>/<digest>.<ext> image bytes, content-addressed
    analysis/*.json                   suffix, occurrence, variance, coverage

Two deliberate choices:

* **Pages are kept.** They are small gzipped and they are the ultimate proof
  that the parser invented nothing - every entry also carries the SHA-256 of
  its own `<dl>` fragment, and the page can simply be re-parsed.
* **Images are addressed by content, never by URL.** Bandai appends a cache
  buster (`?260821`) that changes without the artwork changing, so the query
  string is recorded separately and is never identity. Identical bytes served
  at several addresses are stored once, with every source URL kept.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import urlsplit

from app.services.official_cardlist import OfficialCardEntry, OfficialSeries

SNAPSHOT_VERSION = 1
SOURCE_CATALOGUE = "bandai_jp"

MANIFEST = "manifest.json"
SERIES_FILE = "series.jsonl"
ENTRIES_FILE = "entries.jsonl"
ASSETS_FILE = "assets.jsonl"
PAGES_DIR = "pages"
IMAGES_DIR = "images"
ANALYSIS_DIR = "analysis"

# The fields whose variation across printings this tranche is asked to measure.
# Keyed by Bandai's own block names plus the two header spans.
ANALYSED_FIELDS = (
    "rarity", "category", "color", "cost", "power", "counter",
    "attribute", "feature", "text", "trigger", "block", "card_name",
)

CONTENT_TYPE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


# --- raw records --------------------------------------------------------------


def entry_record(
    entry: OfficialCardEntry,
    *,
    series_id: str,
    series_url: str,
    product_title: str | None,
    product_code: str | None,
    fetched_at: str,
) -> dict[str, Any]:
    """One card occurrence, verbatim. No value is normalised or dropped."""
    return {
        "fetched_at": fetched_at,
        "source_catalogue": SOURCE_CATALOGUE,
        "source_series_id": series_id,
        "source_url": series_url,
        "product_title": product_title,
        "product_code": product_code,
        "entry_id": entry.entry_id,
        "card_code": entry.card_code,
        "card_name": entry.card_name,
        "rarity": entry.rarity,
        "category": entry.category,
        "image_url": entry.image_url,
        "product_names": list(entry.product_names),
        # Every published block, keyed by Bandai's div class, each keeping its
        # own heading so 'ライフ' is never silently read as 'コスト'.
        "fields": [asdict(f) for f in entry.fields],
        "fragment_sha256": entry.fragment_sha256,
    }


def series_record(series: OfficialSeries, *, fetched_at: str, entry_count: int) -> dict[str, Any]:
    return {
        "fetched_at": fetched_at,
        "source_catalogue": SOURCE_CATALOGUE,
        "source_series_id": series.series_id,
        "source_url": series.source_url,
        "display_name": series.display_name,
        "official_code": series.official_code,
        "entry_count": entry_count,
    }


def asset_url_parts(url: str) -> dict[str, str | None]:
    """URL, path, basename and query string, kept apart.

    The query string is Bandai's cache buster. Recording it separately is what
    stops it ever being mistaken for identity.
    """
    parts = urlsplit(url)
    basename = parts.path.rsplit("/", 1)[-1]
    return {
        "url": url,
        "url_path": parts.path,
        "basename": basename,
        "query_string": parts.query or None,
    }


# --- snapshot io ----------------------------------------------------------------


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


class Snapshot:
    """A snapshot directory. Knows its layout; performs no fetching."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # -- paths
    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST

    @property
    def pages_dir(self) -> Path:
        return self.root / PAGES_DIR

    @property
    def images_dir(self) -> Path:
        return self.root / IMAGES_DIR

    @property
    def analysis_dir(self) -> Path:
        return self.root / ANALYSIS_DIR

    def page_path(self, series_id: str) -> Path:
        return self.pages_dir / f"{series_id}.html.gz"

    def image_path(self, digest: str, extension: str = ".png") -> Path:
        return self.images_dir / "sha256" / digest[:2] / f"{digest}{extension}"

    # -- pages
    def write_page(self, series_id: str, html: str) -> Path:
        path = self.page_path(series_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write(html)
        return path

    def read_page(self, series_id: str) -> str | None:
        path = self.page_path(series_id)
        if not path.exists():
            return None
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return handle.read()

    def has_page(self, series_id: str) -> bool:
        return self.page_path(series_id).exists()

    # -- images
    def has_image(self, digest: str, extension: str = ".png") -> bool:
        return self.image_path(digest, extension).exists()

    def write_image(self, payload: bytes, extension: str = ".png") -> tuple[str, Path]:
        digest = hashlib.sha256(payload).hexdigest()
        path = self.image_path(digest, extension)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        return digest, path

    # -- records
    def load(self, name: str) -> list[dict[str, Any]]:
        return list(read_jsonl(self.root / name))

    def save(self, name: str, rows: Iterable[dict[str, Any]]) -> int:
        return write_jsonl(self.root / name, rows)

    def load_manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return {}
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def save_manifest(self, manifest: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )

    def save_analysis(self, name: str, document: Any) -> Path:
        self.analysis_dir.mkdir(parents=True, exist_ok=True)
        path = self.analysis_dir / name
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )
        return path

    def disk_usage(self) -> dict[str, int]:
        def total(path: Path) -> int:
            if not path.exists():
                return 0
            return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

        return {
            "pages_bytes": total(self.pages_dir),
            "images_bytes": total(self.images_dir),
            "records_bytes": sum(
                (self.root / n).stat().st_size
                for n in (MANIFEST, SERIES_FILE, ENTRIES_FILE, ASSETS_FILE)
                if (self.root / n).exists()
            ),
            "total_bytes": total(self.root),
        }


# --- suffix inventory ------------------------------------------------------------

BASE_FAMILY = "base"
UNPARSEABLE = "unparseable"

SUFFIX_RE = re.compile(r"^_(?P<letter>[a-zA-Z]+)(?P<index>\d+)$")


def raw_suffix(basename: str | None, card_code: str | None) -> str | None:
    """The part of an asset basename that follows the card code.

    `''` for a bare `CODE.png`. None when the basename does not name this
    card at all - which is unreadable evidence, not a suffix.
    """
    if not basename or not card_code:
        return None
    stem = basename.rsplit(".", 1)[0] if "." in basename else basename
    code = card_code.strip()
    if not code:
        return None
    if stem.upper() == code.upper():
        return ""
    if len(stem) > len(code) and stem[: len(code)].upper() == code.upper():
        return stem[len(code) :]
    return None


def suffix_family(suffix: str | None) -> str:
    """`base`, a letter family such as `p`/`r`, or `unparseable`.

    Deliberately derived from the observed characters rather than a fixed
    allow-list of p and r: this tranche's job is to *discover* the vocabulary,
    so an unexpected family is reported under its own name instead of being
    swept into 'other'.
    """
    if suffix is None:
        return UNPARSEABLE
    if suffix == "":
        return BASE_FAMILY
    match = SUFFIX_RE.match(suffix)
    if not match:
        return UNPARSEABLE
    return match.group("letter").lower()


def suffix_index(suffix: str | None) -> int | None:
    if not suffix:
        return None
    match = SUFFIX_RE.match(suffix)
    return int(match.group("index")) if match else None


def suffix_inventory(entries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Counts for every basename pattern observed, verbatim."""
    families: Counter[str] = Counter()
    exact: Counter[str] = Counter()
    unparseable_examples: list[dict[str, str | None]] = []
    per_family_index: dict[str, Counter] = defaultdict(Counter)

    for row in entries:
        basename = (asset_url_parts(row["image_url"])["basename"] if row.get("image_url") else None)
        suffix = raw_suffix(basename, row.get("card_code"))
        family = suffix_family(suffix)
        families[family] += 1
        exact[suffix if suffix is not None else "<unparseable>"] += 1
        index = suffix_index(suffix)
        if index is not None:
            per_family_index[family][index] += 1
        if family == UNPARSEABLE and len(unparseable_examples) < 50:
            unparseable_examples.append(
                {"entry_id": row.get("entry_id"), "card_code": row.get("card_code"),
                 "basename": basename}
            )

    return {
        "families": dict(families.most_common()),
        "exact_suffixes": dict(exact.most_common()),
        "indices_per_family": {k: dict(sorted(v.items())) for k, v in per_family_index.items()},
        "unparseable_examples": unparseable_examples,
    }


# --- occurrence matrix and variance -------------------------------------------------


def _field_value(row: dict[str, Any], name: str) -> str | None:
    """One analysed value for an occurrence, raw.

    Header spans (rarity/category/card_name) come from the row; everything
    else is a published block, and a missing block returns None - which is
    different from a block whose value is '-'.
    """
    if name in ("rarity", "category", "card_name"):
        value = row.get(name)
        return value if value not in ("", None) else None
    for block in row.get("fields", []):
        if block.get("name") == name:
            # The attribute block's value is an icon; its alt text is the word.
            if name == "attribute":
                return block.get("image_alt") or block.get("value") or None
            return block.get("value") if block.get("value") != "" else None
    return None


def normalize_for_comparison(value: str | None) -> str | None:
    """Compatibility-normalised text, for telling formatting from substance.

    NFKC folds Bandai's full-width digits and brackets onto their ASCII
    equivalents, and whitespace is collapsed. Used ONLY to classify a
    difference; the raw values are always preserved and reported alongside.
    """
    if value is None:
        return None
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


@dataclass
class FieldVariance:
    field_name: str
    classification: str  # "invariant" | "varies" | "missing_or_inconsistent"
    raw_values: list[str]
    normalized_values: list[str]
    formatting_only: bool
    present_count: int
    occurrence_count: int


CLASS_INVARIANT = "invariant"
CLASS_VARIES = "varies"
CLASS_MISSING = "missing_or_inconsistent"


def classify_field(values: list[str | None]) -> FieldVariance:
    present = [v for v in values if v is not None]
    raw_distinct = sorted(set(present))
    norm_distinct = sorted({normalize_for_comparison(v) or "" for v in present})

    if not present:
        classification = CLASS_MISSING
    elif len(present) != len(values):
        # Published for some printings and absent for others: the source is
        # inconsistent about this field, which is its own finding and must not
        # be reported as either invariant or varying.
        classification = CLASS_MISSING
    elif len(raw_distinct) == 1:
        classification = CLASS_INVARIANT
    else:
        classification = CLASS_VARIES

    return FieldVariance(
        field_name="",
        classification=classification,
        raw_values=raw_distinct,
        normalized_values=norm_distinct,
        formatting_only=len(raw_distinct) > 1 and len(norm_distinct) == 1,
        present_count=len(present),
        occurrence_count=len(values),
    )


def occurrence_matrix(
    entries: Iterable[dict[str, Any]], assets_by_url: dict[str, dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Every official occurrence grouped by card code, with per-field variance."""
    assets_by_url = assets_by_url or {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in entries:
        grouped[row.get("card_code") or ""].append(row)

    matrix: list[dict[str, Any]] = []
    for card_code, rows in sorted(grouped.items()):
        occurrences = []
        for row in rows:
            parts = asset_url_parts(row["image_url"]) if row.get("image_url") else {}
            basename = parts.get("basename")
            asset = assets_by_url.get(row.get("image_url") or "", {})
            occurrences.append(
                {
                    "entry_id": row.get("entry_id"),
                    "source_series_id": row.get("source_series_id"),
                    "product_title": row.get("product_title"),
                    "product_code": row.get("product_code"),
                    "product_names": row.get("product_names"),
                    "image_basename": basename,
                    "image_sha256": asset.get("sha256"),
                    "raw_suffix": raw_suffix(basename, card_code),
                    "suffix_family": suffix_family(raw_suffix(basename, card_code)),
                    **{name: _field_value(row, name) for name in ANALYSED_FIELDS},
                }
            )
        variance: dict[str, Any] = {}
        for name in ANALYSED_FIELDS:
            result = classify_field([o[name] for o in occurrences])
            result.field_name = name
            variance[name] = asdict(result)

        digests = {o["image_sha256"] for o in occurrences if o["image_sha256"]}
        products = {o["product_code"] or (o["product_names"] or [None])[0] for o in occurrences}
        matrix.append(
            {
                "card_code": card_code,
                "occurrence_count": len(occurrences),
                "distinct_images": len(digests),
                "distinct_products": len([p for p in products if p]),
                "occurrences": occurrences,
                "variance": variance,
            }
        )
    return matrix


def variance_report(matrix: list[dict[str, Any]]) -> dict[str, Any]:
    """Quantified answers to the print-variance questions, with examples."""
    multi = [m for m in matrix if m["occurrence_count"] > 1]
    per_field: dict[str, Any] = {}
    for name in ANALYSED_FIELDS:
        varying = [m for m in matrix if m["variance"][name]["classification"] == CLASS_VARIES]
        formatting = [m for m in varying if m["variance"][name]["formatting_only"]]
        material = [m for m in varying if not m["variance"][name]["formatting_only"]]
        inconsistent = [
            m for m in matrix if m["variance"][name]["classification"] == CLASS_MISSING
        ]
        per_field[name] = {
            "card_codes_varying": len(varying),
            "formatting_only": len(formatting),
            "materially_different": len(material),
            "missing_or_inconsistent": len(inconsistent),
            "examples": [
                {
                    "card_code": m["card_code"],
                    "raw_values": m["variance"][name]["raw_values"][:6],
                    "formatting_only": m["variance"][name]["formatting_only"],
                }
                for m in (material or formatting)[:5]
            ],
        }

    return {
        "card_codes_total": len(matrix),
        "card_codes_with_multiple_occurrences": len(multi),
        "card_codes_with_multiple_images": len([m for m in matrix if m["distinct_images"] > 1]),
        "card_codes_spanning_multiple_products": len(
            [m for m in matrix if m["distinct_products"] > 1]
        ),
        "fields": per_field,
    }


def suffix_family_analysis(matrix: list[dict[str, Any]]) -> dict[str, Any]:
    """The pN/rN questions, answered from the whole dataset."""
    index_counts: dict[str, Counter] = defaultdict(Counter)
    both_families: list[str] = []
    repeats_across_products: list[dict[str, Any]] = []
    r_family_rows: list[dict[str, Any]] = []

    for card in matrix:
        families = defaultdict(list)
        for occurrence in card["occurrences"]:
            family = occurrence["suffix_family"]
            index = suffix_index(occurrence["raw_suffix"])
            if index is not None:
                index_counts[family][index] += 1
            families[family].append(occurrence)
            if family == "r":
                r_family_rows.append({"card_code": card["card_code"], **{
                    k: occurrence.get(k) for k in
                    ("entry_id", "product_code", "product_names", "rarity", "image_sha256")}})

        letter_families = {f for f in families if f not in (BASE_FAMILY, UNPARSEABLE)}
        if len(letter_families) > 1:
            both_families.append(card["card_code"])

        # Does the same suffix index appear against more than one product?
        seen: dict[str, set] = defaultdict(set)
        for occurrence in card["occurrences"]:
            if occurrence["raw_suffix"]:
                seen[occurrence["raw_suffix"]].add(
                    occurrence["product_code"] or (occurrence["product_names"] or [None])[0]
                )
        for suffix, products in seen.items():
            if len({p for p in products if p}) > 1:
                repeats_across_products.append(
                    {"card_code": card["card_code"], "suffix": suffix,
                     "products": sorted(str(p) for p in products if p)}
                )

    return {
        "index_counts_per_family": {k: dict(sorted(v.items())) for k, v in index_counts.items()},
        "cards_with_more_than_one_letter_family": both_families,
        "same_suffix_across_multiple_products": repeats_across_products[:50],
        "same_suffix_across_multiple_products_count": len(repeats_across_products),
        "r_family_occurrences": r_family_rows[:80],
        "r_family_count": len(r_family_rows),
    }
