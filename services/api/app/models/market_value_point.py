"""Append-only evidence for the frozen Market Value v1 calculation.

One row is one archived snapshot day for either Overall or one authoritative
``ReleaseProduct``.  It stores the literal tracked JPY sum independently from
the coverage-neutral P/Q movement step and its dimensionless chain state.
Nothing in this model calculates either measurement.

The two partial unique indexes are the natural key.  A conventional UNIQUE
constraint containing nullable ``release_product_id`` would allow duplicate
Overall rows on PostgreSQL, because NULL values are distinct.  Splitting the
key by scope closes that hole and also supplies the expected date-range/latest
read paths without speculative indexes.

JPY sums use BIGINT.  Even a deliberately conservative projected catalogue of
ten million prints valued at JPY 100 billion each totals 10^18, below signed
BIGINT's 9.22e18 ceiling.  Ratios and performance factors use unconstrained
NUMERIC: A2 computes 50 significant digits, but an open-ended chained series
has no honest finite bound on integer or fractional places.  PostgreSQL
NUMERIC preserves the emitted Decimal exactly instead of imposing a schema
rounding rule that is not part of the methodology.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

MARKET_VALUE_SCOPE_KINDS = ("overall", "release")


class MarketValuePoint(Base):
    __tablename__ = "market_value_points"
    __table_args__ = (
        Index(
            "uq_market_value_points_overall_point",
            "methodology_version",
            "point_date",
            unique=True,
            postgresql_where=text(
                "scope_kind = 'overall' AND release_product_id IS NULL"
            ),
            sqlite_where=text(
                "scope_kind = 'overall' AND release_product_id IS NULL"
            ),
        ),
        Index(
            "uq_market_value_points_release_point",
            "release_product_id",
            "methodology_version",
            "point_date",
            unique=True,
            postgresql_where=text(
                "scope_kind = 'release' AND release_product_id IS NOT NULL"
            ),
            sqlite_where=text(
                "scope_kind = 'release' AND release_product_id IS NOT NULL"
            ),
        ),
        CheckConstraint(
            "scope_kind IN ('overall', 'release')",
            name="ck_market_value_points_scope_kind",
        ),
        CheckConstraint(
            "(scope_kind = 'overall' AND release_product_id IS NULL) OR "
            "(scope_kind = 'release' AND release_product_id IS NOT NULL)",
            name="ck_market_value_points_scope_identity",
        ),
        CheckConstraint(
            "methodology_version > 0",
            name="ck_market_value_points_methodology_version_positive",
        ),
        CheckConstraint(
            "priced_print_count >= 0 AND total_physical_print_count >= 0 "
            "AND priced_print_count <= total_physical_print_count",
            name="ck_market_value_points_current_counts",
        ),
        CheckConstraint(
            "(priced_print_count = 0 AND tracked_value_jpy IS NULL) OR "
            "(priced_print_count > 0 AND tracked_value_jpy > 0)",
            name="ck_market_value_points_current_value_presence",
        ),
        CheckConstraint(
            "(prior_point_date IS NULL) = (step_days IS NULL) "
            "AND (prior_point_date IS NULL) = "
            "(prior_priced_print_count IS NULL) "
            "AND (prior_point_date IS NULL) = "
            "(prior_total_physical_print_count IS NULL) "
            "AND (prior_point_date IS NULL) = "
            "(comparable_print_count IS NULL) "
            "AND (prior_point_date IS NULL) = "
            "(prior_comparable_value_jpy IS NULL) "
            "AND (prior_point_date IS NULL) = "
            "(current_comparable_value_jpy IS NULL) "
            "AND (prior_point_date IS NULL) = "
            "(step_publication_eligible IS NULL) "
            "AND (prior_point_date IS NULL) = "
            "(publication_reasons IS NULL) "
            "AND (prior_point_date IS NULL) = "
            "(prior_version_pairs IS NULL)",
            name="ck_market_value_points_step_pairing",
        ),
        CheckConstraint(
            "prior_point_date IS NULL OR "
            "(prior_point_date < point_date AND step_days >= 1)",
            name="ck_market_value_points_step_order",
        ),
        CheckConstraint(
            "prior_priced_print_count IS NULL OR "
            "(prior_priced_print_count >= 0 "
            "AND prior_total_physical_print_count >= 0 "
            "AND prior_priced_print_count <= prior_total_physical_print_count)",
            name="ck_market_value_points_prior_counts",
        ),
        CheckConstraint(
            "prior_priced_print_count IS NULL OR "
            "(prior_priced_print_count = 0 AND prior_tracked_value_jpy IS NULL) OR "
            "(prior_priced_print_count > 0 AND prior_tracked_value_jpy > 0)",
            name="ck_market_value_points_prior_value_presence",
        ),
        CheckConstraint(
            "comparable_print_count IS NULL OR "
            "(comparable_print_count >= 0 "
            "AND comparable_print_count <= priced_print_count "
            "AND comparable_print_count <= prior_priced_print_count)",
            name="ck_market_value_points_comparable_counts",
        ),
        CheckConstraint(
            "comparable_print_count IS NULL OR "
            "(comparable_print_count = 0 "
            "AND prior_comparable_value_jpy = 0 "
            "AND current_comparable_value_jpy = 0 "
            "AND step_ratio IS NULL) OR "
            "(comparable_print_count > 0 "
            "AND prior_comparable_value_jpy > 0 "
            "AND current_comparable_value_jpy > 0 "
            "AND step_ratio > 0)",
            name="ck_market_value_points_comparable_value_presence",
        ),
        CheckConstraint(
            "prior_comparable_value_jpy IS NULL OR "
            "(prior_comparable_value_jpy <= COALESCE(prior_tracked_value_jpy, 0) "
            "AND current_comparable_value_jpy <= COALESCE(tracked_value_jpy, 0))",
            name="ck_market_value_points_comparable_values_le_tracked",
        ),
        CheckConstraint(
            "(step_publication_eligible IS NULL) = "
            "(publication_reasons IS NULL)",
            name="ck_market_value_points_publication_pairing",
        ),
        CheckConstraint(
            "step_publication_eligible IS NULL OR "
            "(step_publication_eligible AND publication_reasons = 'publishable') OR "
            "(NOT step_publication_eligible "
            "AND publication_reasons <> 'publishable')",
            name="ck_market_value_points_publication_reason",
        ),
        CheckConstraint(
            "NOT COALESCE(step_publication_eligible, FALSE) OR step_ratio IS NOT NULL",
            name="ck_market_value_points_publishable_has_ratio",
        ),
        CheckConstraint(
            "segment_number >= 0 AND performance_factor > 0",
            name="ck_market_value_points_chain_state",
        ),
        CheckConstraint(
            "prior_point_date IS NOT NULL OR "
            "(segment_number = 0 AND performance_factor = 1 "
            "AND step_ratio IS NULL)",
            name="ck_market_value_points_initial_state",
        ),
        CheckConstraint(
            "step_publication_eligible IS NULL OR step_publication_eligible "
            "OR performance_factor = 1",
            name="ck_market_value_points_break_resets_factor",
        ),
        CheckConstraint(
            "trim(membership_revision, ' \t\n\r') <> ''",
            name="ck_market_value_points_membership_revision_not_blank",
        ),
    )

    # Internal surrogate only. Public and replay contracts use the natural key.
    id: Mapped[int] = mapped_column(primary_key=True)
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    release_product_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "release_products.id",
            name="fk_market_value_points_release_product_id",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        nullable=True,
    )
    methodology_version: Mapped[int] = mapped_column(Integer, nullable=False)
    point_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Literal current basket facts. Coverage is exactly priced / total.
    tracked_value_jpy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    priced_print_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_physical_print_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Prior endpoint and comparable-panel facts. Value coverage is exactly
    # P/prior_tracked and Q/tracked; no rounded percentage is persisted.
    prior_point_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    step_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prior_tracked_value_jpy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    prior_priced_print_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prior_total_physical_print_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    comparable_print_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prior_comparable_value_jpy: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    current_comparable_value_jpy: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    step_ratio: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)

    # Dimensionless A2 chain state. A failed step has NULL step_ratio only
    # when arithmetic itself was unavailable; performance_factor=1 is the new
    # segment base and never a claim of 0% daily movement.
    segment_number: Mapped[int] = mapped_column(Integer, nullable=False)
    performance_factor: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    step_publication_eligible: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    # Exact ordered A2 reason tuple joined by '|'. The primary reason is the
    # first token, so it is not duplicated in a presentation column.
    publication_reasons: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Compact deterministic provenance, never constituent ID blobs.
    membership_revision: Mapped[str] = mapped_column(String(160), nullable=False)
    prior_version_pairs: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_version_pairs: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = ["MARKET_VALUE_SCOPE_KINDS", "MarketValuePoint"]
