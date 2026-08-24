"""Rebuilds planner input from a frozen local snapshot, with no network at all.

WHY THIS EXISTS. `app.plan_canonical_print_import` fetches Bandai's Card List
live, which is right for planning: you want to know what the catalogue says
*now*. It is wrong for applying. An apply run that fetched during its own
transaction would be writing from data nobody reviewed, and a mid-run change
at the source would silently split one run across two versions of the truth.

So the apply engine reads only from `data/official_snapshots/<catalogue>/current`,
the on-disk corpus `app.collect_official_cardlist_snapshot` captured. Every
value here is the verbatim record that snapshot froze - this module parses,
it never derives, normalises or fills in.

WHAT IT REBUILDS. The three inputs `print_import_planner.plan_entries` takes:

    entries.jsonl -> OfficialCardEntry, published blocks included
    series.jsonl  -> OfficialSeries, the product authority index
    assets.jsonl  -> a DigestProvider, url -> SHA-256 of the fetched bytes

The digest provider is a dict lookup over what the snapshot already hashed.
It returns None for a URL the snapshot never fetched, which is what makes a
print with no digest evidence fall to needs_review rather than be waved
through - exactly as the network fetcher does when a fetch fails.

SNAPSHOT IDENTITY. `SnapshotInput.identity` is a SHA-256 over the three record
files' own bytes plus the manifest's timestamps. It is what an apply run pins
itself to: re-running against a snapshot that has been recollected changes the
identity, and the apply engine refuses rather than writing from input its plan
was not built on.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from app.services.official_cardlist import OfficialCardEntry, OfficialSeries, RawField

SOURCE_CATALOGUE = "bandai_jp"

# Relative to the repo root. The apply CLI resolves it; tests point at a
# temporary directory built the same way.
DEFAULT_SNAPSHOT_ROOT = Path("data/official_snapshots")

ENTRIES = "entries.jsonl"
SERIES = "series.jsonl"
ASSETS = "assets.jsonl"
MANIFEST = "manifest.json"

RECORD_FILES = (ENTRIES, SERIES, ASSETS)


class SnapshotInputError(RuntimeError):
    """The snapshot on disk cannot be read as planner input."""


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        raise SnapshotInputError(f"snapshot file missing: {path}")
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise SnapshotInputError(f"{path}:{number} is not valid JSON: {exc}") from exc


def _entry_from_record(record: dict[str, Any]) -> OfficialCardEntry:
    """One occurrence, exactly as the snapshot froze it.

    `fields` keeps Bandai's own div class as `name` and its own heading as
    `label`, so a block is never re-keyed on the way back in - the planner
    reads `cost`/`power`/`text`/`block` by those names and would silently read
    the wrong block if this renamed anything.
    """
    fields = tuple(
        RawField(
            name=field.get("name") or "",
            label=field.get("label") or "",
            value=field.get("value") or "",
            image_alt=field.get("image_alt"),
            image_src=field.get("image_src"),
        )
        for field in record.get("fields") or ()
    )
    for required in ("entry_id", "card_code"):
        if not record.get(required):
            raise SnapshotInputError(
                f"entry record is missing {required!r}: {json.dumps(record)[:200]}"
            )
    return OfficialCardEntry(
        entry_id=record["entry_id"],
        card_code=record["card_code"],
        rarity=record.get("rarity") or "",
        category=record.get("category") or "",
        card_name=record.get("card_name") or "",
        image_url=record.get("image_url"),
        product_names=tuple(record.get("product_names") or ()),
        fields=fields,
        fragment_sha256=record.get("fragment_sha256"),
    )


def _series_from_record(record: dict[str, Any]) -> OfficialSeries:
    return OfficialSeries(
        series_id=record["source_series_id"],
        display_name=record.get("display_name") or "",
        official_code=record.get("official_code"),
    )


@dataclass(frozen=True)
class SnapshotInput:
    """Everything one apply run reads, frozen and identified.

    `digests` maps an asset URL to the SHA-256 of the bytes the snapshot
    fetched for it. `entry_source` maps an entry id to the series it was
    captured under, which is the authority evidence a created ReleaseProduct
    is populated from.
    """

    root: Path
    source_catalogue: str
    identity: str
    entries: tuple[OfficialCardEntry, ...]
    series: tuple[OfficialSeries, ...]
    digests: dict[str, str]
    entry_source: dict[str, dict[str, Any]]
    manifest: dict[str, Any]

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    def digest_provider(self):
        """A DigestProvider over frozen bytes. Returns None for anything the
        snapshot did not fetch - never a guess, never a live request."""
        return self.digests.get

    def describe(self) -> dict[str, Any]:
        return {
            "source_catalogue": self.source_catalogue,
            "snapshot_identity": self.identity,
            "snapshot_root": str(self.root),
            "entries": len(self.entries),
            "series": len(self.series),
            "assets_with_digest": len(self.digests),
            "collected_started_at": self.manifest.get("started_at"),
            "collected_finished_at": self.manifest.get("finished_at"),
            "snapshot_version": self.manifest.get("snapshot_version"),
        }


def snapshot_identity(root: Path, manifest: dict[str, Any]) -> str:
    """SHA-256 over the record files' bytes plus the manifest's own timestamps.

    Hashing the files rather than the parsed rows means an edit that parses
    identically still changes the identity: the point is to pin the exact
    bytes an apply run was planned against, not an interpretation of them.
    """
    digest = hashlib.sha256()
    for name in RECORD_FILES:
        path = root / name
        if not path.exists():
            raise SnapshotInputError(f"snapshot file missing: {path}")
        digest.update(name.encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    for key in ("snapshot_version", "source_catalogue", "started_at", "finished_at"):
        digest.update(f"{key}={manifest.get(key)}".encode("utf-8"))
    return digest.hexdigest()


def load_snapshot(
    root: Path | str,
    *,
    source_catalogue: str = SOURCE_CATALOGUE,
) -> SnapshotInput:
    """Reads `<root>` as planner input. No network, no writes, no derivation."""
    root = Path(root)
    if not root.is_dir():
        raise SnapshotInputError(f"snapshot directory not found: {root}")

    manifest_path = root / MANIFEST
    if not manifest_path.exists():
        raise SnapshotInputError(f"snapshot file missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    recorded = manifest.get("source_catalogue")
    if recorded and recorded != source_catalogue:
        raise SnapshotInputError(
            f"snapshot at {root} was collected from '{recorded}', not '{source_catalogue}'"
        )

    entries: list[OfficialCardEntry] = []
    entry_source: dict[str, dict[str, Any]] = {}
    for record in _rows(root / ENTRIES):
        entry = _entry_from_record(record)
        entries.append(entry)
        # Last write wins only if an entry id repeats, which the corpus does
        # not do; recorded per entry so a created product's authority evidence
        # comes from the series this occurrence was actually captured under.
        entry_source[entry.entry_id] = {
            "source_series_id": record.get("source_series_id"),
            "source_url": record.get("source_url"),
            "product_title": record.get("product_title"),
            "product_code": record.get("product_code"),
        }

    series = tuple(_series_from_record(record) for record in _rows(root / SERIES))

    digests: dict[str, str] = {}
    for record in _rows(root / ASSETS):
        url, sha256 = record.get("url"), record.get("sha256")
        if url and sha256:
            digests[url] = sha256

    return SnapshotInput(
        root=root,
        source_catalogue=source_catalogue,
        identity=snapshot_identity(root, manifest),
        entries=tuple(entries),
        series=series,
        digests=digests,
        entry_source=entry_source,
        manifest=manifest,
    )


def default_snapshot_root(
    repo_root: Path | str,
    *,
    source_catalogue: str = SOURCE_CATALOGUE,
) -> Path:
    return Path(repo_root) / DEFAULT_SNAPSHOT_ROOT / source_catalogue / "current"
