"""Health of the self-hosted official images.

Database consistency (always): every active print with an official image_url
must have a row for that exact URL whose digest equals its artwork_key.
Object presence (optional): every current row's object exists in R2 with the
recorded length. Read-only either way.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CardPrint
from app.official_images.mirror import is_official_url
from app.official_images.models import CardPrintImageAsset
from app.services.object_storage import R2ObjectStorage


@dataclass
class HealthReport:
    prints_checked: int = 0
    missing_copy: list[int] = field(default_factory=list)
    digest_mismatch: list[int] = field(default_factory=list)
    missing_object: list[int] = field(default_factory=list)
    objects_checked: int = 0

    @property
    def healthy(self) -> bool:
        return not (self.missing_copy or self.digest_mismatch or self.missing_object)

    def summary(self) -> dict:
        return {
            "prints_checked": self.prints_checked,
            "missing_copy": len(self.missing_copy),
            "digest_mismatch": len(self.digest_mismatch),
            "missing_object": len(self.missing_object),
            "objects_checked": self.objects_checked,
            "sample_print_ids": {
                "missing_copy": self.missing_copy[:20],
                "digest_mismatch": self.digest_mismatch[:20],
                "missing_object": self.missing_object[:20],
            },
        }


def check_health(db: Session, storage: R2ObjectStorage | None = None) -> HealthReport:
    report = HealthReport()
    prints = [
        row
        for row in db.execute(
            select(CardPrint.id, CardPrint.image_url, CardPrint.artwork_key)
            .where(CardPrint.is_active.is_(True), CardPrint.image_url.is_not(None))
            .order_by(CardPrint.id.asc())
        )
        if is_official_url(row.image_url)
    ]
    report.prints_checked = len(prints)
    assets = {
        (a.card_print_id, a.source_url): a
        for a in db.scalars(select(CardPrintImageAsset))
    }
    current = []
    for row in prints:
        asset = assets.get((row.id, row.image_url))
        if asset is None:
            report.missing_copy.append(row.id)
        elif asset.sha256 != row.artwork_key:
            report.digest_mismatch.append(row.id)
        else:
            current.append(asset)
    if storage is not None:
        lengths: dict[str, int | None] = {}
        for asset in current:
            if asset.object_key not in lengths:
                head = storage.head_object(asset.object_key)
                lengths[asset.object_key] = head.content_length if head else None
                report.objects_checked += 1
            if lengths[asset.object_key] != asset.byte_size:
                report.missing_object.append(asset.card_print_id)
    return report
