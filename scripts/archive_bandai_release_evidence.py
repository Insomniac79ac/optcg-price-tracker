#!/usr/bin/env python3
"""Deterministically package, privately archive, and independently recover API3.

No source HTTP, DB access, bucket provisioning, token provisioning, or application
data writes. `prepare` and `recover` are offline. `upload` uses the operator's
already-provisioned private destination and separate EVIDENCE_R2_* credentials.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile
import tempfile

from verify_bandai_release_evidence import audit, DEFAULT_ROOT

VERSION = "bandai_release_archive_v1"
BUCKET = "cardpirate-atlas-evidence-staging"
MAPPING = "release_date_evidence_audited.json"
INDEX_FILES = ("manifest.json", "release_products_staging.json", "release_date_evidence.jsonl",
               MAPPING, "index_products.jsonl", "acquisition_boundary.json")
COUNTS = {"accepted_product_count": 59, "accepted_date_count": 59, "conflict_count": 0,
          "acquisition_record_count": 75, "raw_payload_count": 67, "product_source_association_count": 117}
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_EXPANDED_BYTES = 16 * 1024 * 1024


def check(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(body):
    return hashlib.sha256(body).hexdigest()


def verify_bundle(root):
    result, _ = audit(root)
    accepted = json.loads((root / MAPPING).read_bytes())
    check(result["rows"] == accepted["rows"], "Recovered extraction differs from accepted audit")
    summary = result["summary"]
    counts = {"accepted_product_count": len(result["rows"]),
              "accepted_date_count": sum(bool(r["release_date"]) for r in result["rows"]),
              "conflict_count": len(summary["conflicts"]),
              "acquisition_record_count": summary["raw_acquisition_records_verified"],
              "raw_payload_count": summary["unique_raw_payloads_verified"],
              "product_source_association_count": summary["product_evidence_associations"]}
    check(counts == COUNTS, "Evidence counts differ from the accepted API3 scope")
    mapping = [{k: row[k] for k in ("release_product_id", "source_catalogue", "official_code", "release_date", "classification")}
               for row in result["rows"]]
    return counts, mapping


def build_archive(root):
    counts, mapping = verify_bundle(root)
    paths = [root / name for name in INDEX_FILES]
    paths += sorted((root / "records").glob("*.json"))
    paths += sorted((root / "raw").glob("*.html.gz"))
    files = {}
    for path in paths:
        check(path.is_file() and not path.is_symlink(), "Archive source is not a regular file")
        check(path.resolve().is_relative_to(root.resolve()), "Archive source escapes bundle")
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    manifest = {"evidence_bundle_version": VERSION, "source_catalogue": "bandai_jp",
                "acquisition_date": "2026-09-24", **counts,
                "file_count": len(files) + 1, "mapping_sha256": digest(canonical(mapping)),
                "audited_mapping_sha256": digest(files[MAPPING]),
                "files": {name: {"sha256": digest(body), "size": len(body)} for name, body in sorted(files.items())}}
    files["archive-manifest.json"] = canonical(manifest)
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, body in sorted(files.items()):
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(body), 0o644, 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                archive.addfile(info, io.BytesIO(body))
    payload = buffer.getvalue()
    check(len(payload) <= MAX_ARCHIVE_BYTES, "Archive exceeds bounded evidence size")
    sha = digest(payload)
    return payload, {"evidence_bundle_version": VERSION, "source_catalogue": "bandai_jp",
                     "acquisition_date": "2026-09-24", "format": "tar.gz",
                     "object_key": f"official-evidence/bandai_jp/release-dates/2026-09-24/sha256/{sha}.tar.gz",
                     "archive_sha256": sha, "archive_size": len(payload),
                     "file_count": len(files), **counts, "accepted_mapping": mapping,
                     "mapping_sha256": digest(canonical(mapping)),
                     "audited_mapping_sha256": digest(files[MAPPING]),
                     "accepted_mapping_reference": {"archive_member": MAPPING,
                                                    "receipt_field": "accepted_mapping"},
                     "verification_status": "LOCAL_PREPARED_NOT_DURABLE"}


def recover_archive(payload, expected):
    """Uses downloaded bytes + small manifest only; source root is not an input."""
    check(len(payload) == expected["archive_size"] <= MAX_ARCHIVE_BYTES, "Archive size mismatch")
    check(digest(payload) == expected["archive_sha256"], "Archive SHA-256 mismatch")
    # Only this disposable extracted copy is removed on exit.
    with tempfile.TemporaryDirectory(prefix="bandai-evidence-recovery-") as directory:
        root = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            check(len(members) == expected["file_count"] and len(set(names)) == len(names), "Archive member count/uniqueness mismatch")
            check(sum(m.size for m in members) <= MAX_EXPANDED_BYTES, "Expanded archive too large")
            for member in members:
                parts = PurePosixPath(member.name)
                check(member.isfile() and not parts.is_absolute() and ".." not in parts.parts,
                      "Unsafe archive member")
                check("\\" not in member.name and parts.as_posix() == member.name, "Noncanonical archive member")
                target = root / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as stream:
                    target.write_bytes(stream.read())
        internal = json.loads((root / "archive-manifest.json").read_bytes())
        check(internal["file_count"] == len(names), "Internal file count mismatch")
        check(set(names) == set(internal["files"]) | {"archive-manifest.json"}, "Internal inventory mismatch")
        for name, entry in internal["files"].items():
            body = (root / name).read_bytes()
            check(len(body) == entry["size"] and digest(body) == entry["sha256"], "Embedded file digest mismatch")
        counts, mapping = verify_bundle(root)
        check(mapping == expected["accepted_mapping"], "Recovered product/date mapping differs")
        check(digest(canonical(mapping)) == internal["mapping_sha256"] == expected["mapping_sha256"], "Mapping digest mismatch")
        check(digest((root / MAPPING).read_bytes()) == internal["audited_mapping_sha256"] == expected["audited_mapping_sha256"], "Audited JSON digest mismatch")
        check(all(internal[k] == expected[k] == value for k, value in counts.items()), "Embedded evidence counts differ")
    return {"result": "passed", **counts, "file_count": len(names),
            "all_internal_file_hashes_verified": True, "all_raw_payload_hashes_verified": True,
            "mapping_sha256": digest(canonical(mapping)),
            "audited_mapping_sha256": expected["audited_mapping_sha256"],
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "source_directory_used": False, "temporary_extraction_removed": True}


def upload_archive(storage, payload, expected):
    key = expected["object_key"]
    check(digest(payload) == expected["archive_sha256"] and len(payload) == expected["archive_size"],
          "Upload bytes differ from the prepared manifest")
    check(key == f"official-evidence/bandai_jp/release-dates/2026-09-24/sha256/{digest(payload)}.tar.gz", "Object key is not content-addressed")
    check(storage.bucket_name == BUCKET, "Refusing a bucket outside the dedicated staging archive")
    storage.head_bucket()
    head = storage.head_object(key)
    if head is None:
        storage.put_object(key, payload, metadata={"sha256": expected["archive_sha256"],
                           "evidence-kind": "bandai-jp-release-dates", "acquisition-date": "2026-09-24"})
    else:
        existing = storage.get_object_bytes(key)
        check(digest(existing) == expected["archive_sha256"] and existing == payload,
              "Existing object differs; it was not overwritten")
    # A fresh GET is required even after verifying an existing object for reuse.
    downloaded = storage.get_object_bytes(key)
    check(len(downloaded) == expected["archive_size"] and digest(downloaded) == expected["archive_sha256"]
          and downloaded == payload, "Private GET bytes differ; existing object was not overwritten")
    recovery = recover_archive(downloaded, expected)
    return {**expected, "storage": {"bucket": BUCKET, "purpose": "private official evidence archive",
                                   "environment": "staging", "public_delivery": False},
            "destination_verification": {"bucket_reachable": True,
                                         "public_base_url_required": False,
                                         "public_url_constructed": False,
                                         "privacy_basis": "operator-provided private archive configuration",
                                         "cloudflare_management_configuration_accessed": False,
                                         "display_bucket_accessed": False,
                                         "display_bucket_configuration_changed": False},
            "verification_status": "DURABLE_GET_AND_RECOVERY_VERIFIED",
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "head_result": "absent" if head is None else "present_reused",
            "get_back_sha256": digest(downloaded), "get_back_size": len(downloaded), "recovery": recovery}


def write_new_or_identical(path, body):
    if path.exists():
        check(path.read_bytes() == body, "Output already exists with different bytes")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--source", type=Path, default=DEFAULT_ROOT)
    prepare.add_argument("--archive", type=Path, required=True)
    prepare.add_argument("--manifest", type=Path, required=True)
    upload = commands.add_parser("upload")
    upload.add_argument("--archive", type=Path, required=True)
    upload.add_argument("--manifest", type=Path, required=True)
    upload.add_argument("--receipt", type=Path, required=True)
    recover = commands.add_parser("recover", help="Verify a downloaded archive using its committed receipt")
    recover.add_argument("--archive", type=Path, required=True)
    recover.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        payload, manifest = build_archive(args.source)
        recovery = recover_archive(payload, manifest)
        write_new_or_identical(args.archive, payload)
        write_new_or_identical(args.manifest, json.dumps(manifest, ensure_ascii=False, indent=2).encode() + b"\n")
        print(json.dumps({k: manifest[k] for k in ("verification_status", "archive_sha256", "archive_size", "file_count")}))
        print(json.dumps({"local_recovery": recovery}))
        return
    expected = json.loads(args.manifest.read_bytes())
    payload = args.archive.read_bytes()
    recovery = recover_archive(payload, expected)  # Validate locally before any S3 request.
    if args.command == "recover":
        print(json.dumps(recovery))
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
    from app.services.private_object_storage import PrivateR2ObjectStorage
    receipt = upload_archive(PrivateR2ObjectStorage.from_settings(), payload, expected)
    write_new_or_identical(args.receipt, json.dumps(receipt, ensure_ascii=False, indent=2).encode() + b"\n")
    print(json.dumps({"verification_status": receipt["verification_status"], "archive_sha256": receipt["archive_sha256"]}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Provider exceptions can contain credential-bearing endpoints. Never
        # print exception strings, response bodies, headers, or tracebacks.
        print(json.dumps({"result": "failed", "error_type": type(exc).__name__}), file=sys.stderr)
        raise SystemExit(1)
