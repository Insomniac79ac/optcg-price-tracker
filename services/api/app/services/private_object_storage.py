"""Operator-only private evidence storage; no public delivery or infrastructure API.

Only EVIDENCE_R2_* environment variables are consumed. Display-image settings
and ambient AWS credentials are never used. Importing this module opens no
connection; configuration is validated before client construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
from typing import Mapping

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.services.object_storage import (
    ObjectHead,
    R2ConfigurationError,
    R2_ENDPOINT_TEMPLATE,
    R2_REGION,
    _is_not_found,
    _validated_metadata,
    validate_object_key,
)


@dataclass(frozen=True)
class EvidenceR2Settings:
    account_id: str = field(repr=False)
    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)
    bucket_name: str = field(repr=False)

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None):
        values = os.environ if environment is None else environment
        configured = {}
        for suffix in ("ACCOUNT_ID", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY", "BUCKET_NAME"):
            name = f"EVIDENCE_R2_{suffix}"
            value = values.get(name, "").strip()
            if not value:
                raise R2ConfigurationError(f"{name} is not configured.")
            configured[suffix.lower()] = value
        return cls(**configured)


class PrivateR2ObjectStorage:
    """Bucket HEAD and object HEAD/PUT/GET only; no infrastructure mutations."""

    def __init__(self, *, client, bucket_name: str):
        self._client = client
        self.bucket_name = bucket_name

    @classmethod
    def from_settings(cls, settings: EvidenceR2Settings | None = None):
        cfg = settings if settings is not None else EvidenceR2Settings.from_environment()
        for name in ("account_id", "access_key_id", "secret_access_key", "bucket_name"):
            if not isinstance(getattr(cfg, name), str) or not getattr(cfg, name).strip():
                raise R2ConfigurationError(f"EVIDENCE_R2_{name.upper()} is not configured.")
        if not re.fullmatch(r"[a-fA-F0-9]{32}", cfg.account_id):
            raise R2ConfigurationError("EVIDENCE_R2_ACCOUNT_ID is malformed.")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", cfg.bucket_name):
            raise R2ConfigurationError("EVIDENCE_R2_BUCKET_NAME is malformed.")
        client = boto3.client(
            service_name="s3",
            endpoint_url=R2_ENDPOINT_TEMPLATE.format(account_id=cfg.account_id),
            aws_access_key_id=cfg.access_key_id,
            aws_secret_access_key=cfg.secret_access_key,
            region_name=R2_REGION,
            config=Config(connect_timeout=10, read_timeout=30, retries={"max_attempts": 2}),
        )
        return cls(client=client, bucket_name=cfg.bucket_name)

    def __repr__(self):
        return "<PrivateR2ObjectStorage>"

    def head_bucket(self):
        """Check only the configured bucket; never list its contents."""
        self._client.head_bucket(Bucket=self.bucket_name)

    def head_object(self, key: str) -> ObjectHead | None:
        key = validate_object_key(key)
        try:
            response = self._client.head_object(Bucket=self.bucket_name, Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                return None
            raise
        return ObjectHead(key=key, content_length=response.get("ContentLength"),
                          content_type=response.get("ContentType"), etag=response.get("ETag"),
                          cache_control=response.get("CacheControl"), metadata=response.get("Metadata", {}))

    def put_object(self, key: str, body: bytes, *, metadata: Mapping[str, str] | None = None):
        key = validate_object_key(key)
        if not isinstance(body, bytes):
            raise TypeError("Private object body must be bytes.")
        return self._client.put_object(
            Bucket=self.bucket_name, Key=key, Body=body, ContentType="application/gzip",
            CacheControl="private, no-store", Metadata=_validated_metadata(metadata),
            # Protect against an object appearing between HEAD and PUT.
            IfNoneMatch="*",
        )

    def get_object_bytes(self, key: str) -> bytes:
        key = validate_object_key(key)
        response = self._client.get_object(Bucket=self.bucket_name, Key=key)
        body = response["Body"]
        try:
            return body.read()
        finally:
            body.close()
