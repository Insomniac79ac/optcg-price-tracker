from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PriceObservation(Base):
    __tablename__ = "price_observations"
    __table_args__ = (
        # Backs the latest-price-per-(card, source, price_type) window-
        # function query in app.services.latest_prices - see that module's
        # docstring. Column order matters: (card_id, source_id, price_type)
        # is the partition key, observed_at last so the same index also
        # serves ORDER BY observed_at DESC within each partition.
        Index(
            "ix_price_observations_card_source_type_observed",
            "card_id",
            "source_id",
            "price_type",
            "observed_at",
        ),
        # The exact-print counterpart of the index above, for the public read
        # path: every query in app.services.print_pricing/print_market_index
        # filters on card_print_id, not card_id (see
        # docs/print_centric_pricing.md). Same column order and same
        # reasoning - (card_print_id, source_id, price_type) is the partition
        # key, observed_at last so the index also covers the trailing range/
        # ORDER BY within a series.
        # Does NOT replace the single-column ix_price_observations_card_print_id
        # (b858237e3706): measured on Postgres 16, a predicate on card_print_id
        # alone (get_latest_prices_for_prints, get_price_history_for_print)
        # still plans onto that narrower index, and both indexes coexist
        # exactly as ix_price_observations_card_id coexists with the composite
        # above. This one is what serves the multi-column predicate -
        # print_market_index's (card_print_id, source_id, price_type,
        # observed_at >= cutoff) sold/floor window - as a single index scan.
        Index(
            "ix_price_observations_print_source_type_observed",
            "card_print_id",
            "source_id",
            "price_type",
            "observed_at",
        ),
        # Backs "latest observation(s) for one source across all cards"
        # queries (e.g. a per-source freshness/staleness sweep) that don't
        # filter by card_id at all.
        Index("ix_price_observations_source_observed", "source_id", "observed_at"),
        # Pins an observation to the exact print and source its
        # source_card_mapping was made against - source_card_mappings.
        # card_print_id/source_id can each differ per mapping, so a narrower
        # FK couldn't catch a mismatch between the observation's own print/
        # source and the mapping it claims to use. Composite by design, not
        # independent FKs (see
        # uq_source_card_mappings_print_lineage_identity).
        #
        # card_id is deliberately absent. It is legacy compatibility and is
        # now nullable, and Postgres FKs default to MATCH SIMPLE: including a
        # nullable column would switch the check OFF entirely for any row
        # that leaves it NULL - precisely the print-authoritative rows this
        # constraint exists to police. Narrowing the key is what keeps them
        # enforced.
        ForeignKeyConstraint(
            ["source_card_mapping_id", "card_print_id", "source_id"],
            [
                "source_card_mappings.id",
                "source_card_mappings.card_print_id",
                "source_card_mappings.source_id",
            ],
            ondelete="RESTRICT",
            name="fk_price_observations_mapping_print_source",
        ),
        # Legacy observations carry neither lineage field; print-linked ones
        # must carry both together, never just one.
        CheckConstraint(
            "(source_card_mapping_id IS NULL AND card_print_id IS NULL) OR "
            "(source_card_mapping_id IS NOT NULL AND card_print_id IS NOT NULL)",
            name="ck_price_observations_lineage_paired",
        ),
        # The vocabulary of promotion_state below, enforced by the database
        # rather than by convention. NULL stays permitted - it is the
        # "not determined" state every pre-existing row carries - but a
        # non-null value outside this set is a collector bug, and letting one
        # land would put a string into the column that
        # app.services.source_semantics has no rule for and would silently
        # treat as unconstrained.
        CheckConstraint(
            "promotion_state IS NULL OR promotion_state IN ('none', 'sale')",
            name="ck_price_observations_promotion_state",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # LEGACY COMPATIBILITY, NOT IDENTITY. A priced observation is identified
    # by (source_card_mapping_id, card_print_id, source_id) below. This
    # column stays for the older read paths that still join `cards`
    # (app.services.latest_prices, catalog_coverage, card_audit) and is set
    # on every row written so far, but a print-authoritative observation may
    # leave it NULL - the legacy table cannot name most of the catalogue.
    card_id: Mapped[int | None] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    price_type: Mapped[str] = mapped_column(String(32), index=True)
    price_jpy: Mapped[int] = mapped_column(Integer)
    condition_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stock_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    listing_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("snkrdunk_candidates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Additive print lineage alongside the legacy card_id/source_id above -
    # nothing reads or writes these yet. Both nullable so every existing
    # observation stays valid as legacy (untagged) lineage; the pair is
    # enforced together by ck_price_observations_lineage_paired and their
    # mutual consistency by fk_price_observations_mapping_print above. No
    # single-column ForeignKey() here - the composite constraint is the only
    # FK tying these two columns to source_card_mappings.
    source_card_mapping_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    card_print_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # WHAT THE SOURCE SAID ABOUT ITS OWN PRICE, at the moment this observation
    # was captured. Deliberately generic and source-neutral - it is a property
    # of the observation, not of Yuyu-Tei - so a second source that displays
    # promotions can populate it without a schema change or a renamed column.
    #
    # THREE-VALUED, AND THE THIRD VALUE IS LOAD-BEARING:
    #   NULL     the promotion state was not determined. Either the row
    #            predates this column entirely (every observation written
    #            before it), or the collector looked and the page's markers
    #            disagreed. It never means "no promotion".
    #   "none"   the collector looked and the source displayed no promotion.
    #   "sale"   the collector looked and the source explicitly displayed its
    #            own sale state (for Yuyu-Tei: a SALE badge beside a struck
    #            former price - see yuyutei_collector.extractor).
    #
    # Distinguishing NULL from "none" is the whole reason this is not a
    # boolean. A boolean would force every legacy row to claim "not on sale",
    # which is a fact Atlas does not have: the 549 Yuyu observations written
    # before this column existed include known sale-priced ones (prints 4, 12,
    # 14 and 17 carried a SALE badge on every captured page). No backfill is
    # performed for exactly that reason - see the accompanying migration.
    #
    # WHAT IS NOT HERE. The struck FORMER price is deliberately absent. It is
    # not an offer and never a current market price, so it is not stored as
    # one anywhere; the full page HTML that displayed it is retained in
    # raw_snapshots.raw_content, which is where that evidence belongs.
    #
    # Read by app.services.source_semantics.classify_observation, which turns
    # "sale" into the "sale_price" constraint. That constraint describes the
    # value; it never makes the observation ineligible.
    promotion_state: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Read-only convenience accessor for the composite lineage FK above -
    # viewonly because the pairing is already fully owned by the plain
    # columns plus fk_price_observations_mapping_print_source/
    # ck_price_observations_lineage_paired; a writable relationship here
    # would offer a second, redundant way to set the same columns.
    # Not accessed by any existing code path, so this doesn't change current
    # loading or write behaviour, and (being viewonly) can never cascade a
    # delete. foreign_keys is explicit because source_id also carries its own
    # single-column ForeignKey to sources, so the join here would otherwise
    # be ambiguous.
    source_card_mapping: Mapped["SourceCardMapping | None"] = relationship(
        "SourceCardMapping",
        primaryjoin=(
            "and_(PriceObservation.source_card_mapping_id == SourceCardMapping.id, "
            "PriceObservation.card_print_id == SourceCardMapping.card_print_id, "
            "PriceObservation.source_id == SourceCardMapping.source_id)"
        ),
        foreign_keys=(
            "[PriceObservation.source_card_mapping_id, PriceObservation.card_print_id, "
            "PriceObservation.source_id]"
        ),
        viewonly=True,
    )
