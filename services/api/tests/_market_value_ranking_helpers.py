"""Synthetic A2-derived two-day evidence; never calls a live price resolver."""

from datetime import date, datetime, timezone

from app.models import CanonicalCard, CardPrint, MarketIndexSnapshot, ReleaseProduct
from app.models.market_value_point import MarketValuePoint
from app.services.market_value_replay import (
    build_market_value_point_drafts,
    load_market_value_replay_input,
)

PRIOR = date(2026, 9, 25)
AS_OF = date(2026, 9, 26)
CALCULATED = datetime(2026, 9, 26, 20, tzinfo=timezone.utc)


def seed_rankings(db, *, prior_shift=0, identity_offset=0, flat=False):
    for rid, code in ((1, "OP-01"), (2, "EB-01"), (5, "OP-05"), (17, "OP-17")):
        db.add(
            ReleaseProduct(
                id=rid + identity_offset,
                source_catalogue="bandai_jp",
                official_code=f"TEST-RANK-{code}" if identity_offset else code,
                display_name=f"Release {code}",
                first_seen_name=code,
                source_series_id=f"ranking-{rid}",
                source_url=f"https://example.invalid/{rid}",
                verification_status="verified",
            )
        )
    db.flush()
    prior = {pid: 100 for pid in range(1, 301)}
    prior.update({1: 100000, 2: 500, 3: 500, 4: 1000, 5: 1000})
    prior[60] = 125000 - sum(prior[pid] for pid in range(1, 60))
    prior[300] = 75000 - sum(prior[pid] for pid in range(61, 300))
    prior[60] += prior_shift  # PostgreSQL precision fixture uses repeating ratios.
    current = dict(prior)
    if not flat:
        current.update({1: 110000, 2: 1000, 3: 1000, 4: 500, 5: 500})
    for pid in range(1, 303):
        cid = 1 if pid <= 3 else pid
        if pid not in (2, 3):
            db.add(
                CanonicalCard(
                    id=cid + identity_offset,
                    card_code=(
                        f"RANKING-{identity_offset}-EB04-{cid:03}"
                        if identity_offset
                        else f"EB04-{cid:03}"
                    ),
                    name_en=f"Print {cid}",
                    card_type="CHARACTER",
                    rarity="R",
                )
            )
    db.flush()
    for pid in range(1, 303):
        db.add(
            CardPrint(
                id=pid + identity_offset,
                canonical_card_id=(1 if pid <= 3 else pid) + identity_offset,
                language="jp",
                release_product_id=(1 if pid <= 60 else 2) + identity_offset,
                official_asset_variant=f"p{pid - 1}" if pid in (2, 3) else "base",
                artwork_key="a" * 64,
                verification_status="verified",
                is_active=True,
                official_rarity="SP" if pid <= 3 else None,
                image_url=f"https://example.invalid/{pid}.png",
                treatment=None,
            )
        )
    db.flush()
    for day, values in ((PRIOR, prior), (AS_OF, current)):
        for pid in range(1, 303):
            value = values.get(pid)
            db.add(
                MarketIndexSnapshot(
                    card_print_id=pid + identity_offset,
                    snapshot_date=day,
                    calculated_at=datetime.combine(day, CALCULATED.timetz()),
                    index_value_jpy=value,
                    calculation_method="median",
                    source_count=1 if value else 0,
                    coverage_status="limited" if value else "none",
                    confidence="medium" if value else "low",
                    index_version=3,
                    source_semantics_version=2,
                    provenance={
                        "source_values": [
                            {
                                "source": "yuyutei",
                                "reference_type": "retail_ask",
                                "contributes_to_index": True,
                                "value_jpy": value,
                            }
                        ]
                    },
                )
            )
    db.flush()
    loaded = load_market_value_replay_input(db, through=AS_OF, include_current=False)
    points = [
        MarketValuePoint(**draft.values())
        for draft in build_market_value_point_drafts(loaded)
    ]
    db.add_all(points)
    db.commit()
    return points
