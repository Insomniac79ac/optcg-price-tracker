"""Canonical one-shot capture keys; fresh evidence never resets old attempts."""

import re


def identity_evidence_scope(candidate_id, evidence_digest, version=1):
    if type(candidate_id) is not int or candidate_id <= 0:
        raise ValueError("positive candidate identity required")
    if type(version) is not int or version not in (1, 2):
        raise ValueError("recognized evidence capture version required")
    legacy = f"yuyu-identity:{candidate_id}"
    if version == 1:
        return legacy
    if not isinstance(evidence_digest, str) or not re.fullmatch(
        r"[0-9a-f]{64}", evidence_digest
    ):
        raise ValueError("current canonical evidence digest required")
    return f"{legacy}:sha256:{evidence_digest}"
