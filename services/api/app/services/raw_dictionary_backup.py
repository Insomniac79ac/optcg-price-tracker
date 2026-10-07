"""Pure validation of complete portable plaintext and internal RAW lineage."""

from opcg_source_identity.raw_payload import MAX_BYTES, PREFIX, sha256


def validate_dictionary_references(tables):
    errors = []
    raw_by_id = {row["id"]: row for row in tables.get("raw_snapshots", [])}
    for index, row in enumerate(tables.get("raw_snapshot_dictionaries", [])):
        child = raw_by_id.get(row["id"])
        base = raw_by_id.get(row.get("base_snapshot_id"))
        if child is None or base is None:
            errors.append(
                f"raw_snapshot_dictionaries[{index}] requires both retained snapshots"
            )
            continue
        try:
            child_body = child["raw_content"].encode("utf-8")
            base_body = base["raw_content"].encode("utf-8")
            valid = (
                type(row["id"]) is int
                and type(row["base_snapshot_id"]) is int
                and 0 < row["base_snapshot_id"] < row["id"]
                and not child["raw_content"].startswith(PREFIX)
                and not base["raw_content"].startswith(PREFIX)
                and 0 < len(child_body) <= MAX_BYTES
                and 0 < len(base_body) <= MAX_BYTES
                and type(row["original_bytes"]) is int
                and len(child_body) == row["original_bytes"]
                and type(row["encoded_bytes"]) is int
                and 0 < row["encoded_bytes"] <= 2 * MAX_BYTES
                and sha256(child_body)
                == row["original_sha256"]
                == child["content_hash"]
                and sha256(base_body) == row["base_sha256"] == base["content_hash"]
                and all(
                    child[field] == base[field]
                    for field in ("source_id", "source_url", "parser_version")
                )
            )
        except (KeyError, TypeError, AttributeError):
            valid = False
        if not valid:
            errors.append(
                f"raw_snapshot_dictionaries[{index}] original plaintext identity/hash mismatch"
            )
    return errors
