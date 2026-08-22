"""activate final exact-print identity

Phase 4/5 of exact-print identity, in ONE migration so there is never an
intermediate state where a nullable treatment sits under a unique index that
still contains it (PostgreSQL admits many NULLs in a plain unique index, so
that window would silently weaken uniqueness).

What changes:
  * treatment becomes nullable and stops being identity-bearing. It is
    editable Atlas descriptive metadata; NULL means "not classified".
  * a verified print must instead carry release_product_id and
    official_artwork_variant - the fields that actually name the physical
    printing.
  * the verified identity becomes
        (canonical_card_id, language, release_product_id, official_artwork_variant)
    keeping the existing index NAME so no caller or doc has to be renamed.

What does NOT change: release_product_code (uncoded limited products are
legitimate and must stay representable), artwork_key's own no-fake rule and
its independent role as the SHA-256 evidence anchor, the verification-status
vocabulary, and every other table.

Unlike the earlier additive backfills this migration activates a STRONGER
contract, so it refuses to run on data that cannot satisfy it - see
_preflight_upgrade. Nothing is guessed, deduplicated or deactivated.

Revision ID: d4b17c9e2a83
Revises: c2f7b48a91d6
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4b17c9e2a83'
down_revision: Union[str, Sequence[str], None] = 'c2f7b48a91d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


IDENTITY_INDEX = 'uq_card_prints_active_verified_identity'
VERIFIED_CHECK = 'ck_card_prints_verified_requires_fields'

ACTIVE_VERIFIED = "is_active = true AND verification_status = 'verified'"

# --- the new contract ------------------------------------------------------

# canonical_card_id and language are NOT NULL at column level already; they
# are restated here so the whole identity contract reads in one place.
NEW_VERIFIED_CHECK_SQL = (
    "verification_status <> 'verified' OR ("
    "canonical_card_id IS NOT NULL AND "
    "language IS NOT NULL AND trim(language, ' \t\n\r') <> '' AND "
    "release_product_id IS NOT NULL AND "
    "official_artwork_variant IS NOT NULL AND "
    "artwork_key IS NOT NULL AND "
    # treatment is optional now, but on a verified print a placeholder is
    # still not a classification - the rule the old check carried, kept at the
    # same scope. An unverified print may still park 'unknown' there.
    "(treatment IS NULL OR ("
    "trim(treatment, ' \t\n\r') <> '' AND "
    "lower(trim(treatment, ' \t\n\r')) <> 'unknown'"
    "))"
    ")"
)

# --- the contract being replaced (restored verbatim on downgrade) ----------

OLD_VERIFIED_CHECK_SQL = (
    "verification_status <> 'verified' OR ("
    "treatment IS NOT NULL AND trim(treatment, ' \t\n\r') <> '' AND "
    "lower(trim(treatment, ' \t\n\r')) <> 'unknown' AND "
    "release_product_code IS NOT NULL AND "
    "artwork_key IS NOT NULL"
    ")"
)
OLD_IDENTITY_COLUMNS = [
    'canonical_card_id', 'language', 'treatment', 'release_product_code', 'artwork_key'
]
NEW_IDENTITY_COLUMNS = [
    'canonical_card_id', 'language', 'release_product_id', 'official_artwork_variant'
]


def _scalar(bind, sql: str) -> int:
    return bind.execute(sa.text(sql)).scalar_one()


def _preflight_upgrade() -> None:
    """Refuses to activate the new identity on data that cannot satisfy it.

    Runs BEFORE any DDL, inside the migration's own transaction, so a refusal
    leaves the schema exactly as it was. Every failure names the offending
    rows rather than repairing them: filling a NULL, deduplicating, or
    deactivating a row here would be Atlas inventing identity evidence, which
    is the one thing this whole tranche exists to prevent.
    """
    bind = op.get_bind()

    missing_product = _scalar(
        bind,
        f"SELECT count(*) FROM card_prints WHERE {ACTIVE_VERIFIED} "
        "AND release_product_id IS NULL",
    )
    missing_variant = _scalar(
        bind,
        f"SELECT count(*) FROM card_prints WHERE {ACTIVE_VERIFIED} "
        "AND official_artwork_variant IS NULL",
    )
    duplicates = _scalar(
        bind,
        "SELECT count(*) FROM (SELECT canonical_card_id, language, release_product_id, "
        f"official_artwork_variant FROM card_prints WHERE {ACTIVE_VERIFIED} "
        "GROUP BY 1, 2, 3, 4 HAVING count(*) > 1) d",
    )

    problems: list[str] = []
    if missing_product:
        ids = bind.execute(
            sa.text(
                f"SELECT id FROM card_prints WHERE {ACTIVE_VERIFIED} "
                "AND release_product_id IS NULL ORDER BY id LIMIT 20"
            )
        ).scalars().all()
        problems.append(
            f"{missing_product} active+verified card_prints have no release_product_id "
            f"(ids: {ids})"
        )
    if missing_variant:
        ids = bind.execute(
            sa.text(
                f"SELECT id FROM card_prints WHERE {ACTIVE_VERIFIED} "
                "AND official_artwork_variant IS NULL ORDER BY id LIMIT 20"
            )
        ).scalars().all()
        problems.append(
            f"{missing_variant} active+verified card_prints have no "
            f"official_artwork_variant (ids: {ids})"
        )
    if duplicates:
        rows = bind.execute(
            sa.text(
                "SELECT canonical_card_id, language, release_product_id, "
                f"official_artwork_variant, count(*) FROM card_prints WHERE {ACTIVE_VERIFIED} "
                "GROUP BY 1, 2, 3, 4 HAVING count(*) > 1 ORDER BY 1, 2, 3, 4 LIMIT 20"
            )
        ).all()
        problems.append(
            f"{duplicates} duplicate group(s) already exist under the new identity "
            f"(canonical_card_id, language, release_product_id, official_artwork_variant): "
            f"{[tuple(r) for r in rows]}"
        )

    if problems:
        raise RuntimeError(
            f"[{revision}] ABORTED - the data cannot satisfy the exact-print identity "
            "contract, and this migration will not guess, deduplicate or deactivate "
            "anything to make it fit. Resolve these first:\n  - " + "\n  - ".join(problems)
        )

    total = _scalar(bind, f"SELECT count(*) FROM card_prints WHERE {ACTIVE_VERIFIED}")
    print(
        f"[{revision}] preflight OK - {total} active+verified card_prints all carry "
        "release_product_id and official_artwork_variant, with no duplicate identity"
    )


def _preflight_downgrade() -> None:
    """Refuses to restore the old contract on data that cannot satisfy it.

    Going back means treatment becomes NOT NULL and identity-bearing again.
    A row classified since the upgrade - or never classified at all - cannot
    be made to fit without inventing a treatment, so this aborts instead.
    Nothing is derived from official_artwork_variant, copied from a source,
    deleted, or coerced.
    """
    bind = op.get_bind()

    null_treatment = _scalar(bind, "SELECT count(*) FROM card_prints WHERE treatment IS NULL")
    verified_missing = _scalar(
        bind,
        f"SELECT count(*) FROM card_prints WHERE {ACTIVE_VERIFIED} AND ("
        "release_product_code IS NULL OR artwork_key IS NULL)",
    )
    old_key_duplicates = _scalar(
        bind,
        "SELECT count(*) FROM (SELECT canonical_card_id, language, treatment, "
        "release_product_code, artwork_key FROM card_prints "
        f"WHERE {ACTIVE_VERIFIED} GROUP BY 1, 2, 3, 4, 5 HAVING count(*) > 1) d",
    )

    problems: list[str] = []
    if null_treatment:
        ids = bind.execute(
            sa.text(
                "SELECT id FROM card_prints WHERE treatment IS NULL ORDER BY id LIMIT 20"
            )
        ).scalars().all()
        problems.append(
            f"{null_treatment} card_prints have treatment IS NULL, which the old schema "
            f"forbids (ids: {ids}). A treatment cannot be invented, derived from "
            "official_artwork_variant, or copied from a source"
        )
    if verified_missing:
        problems.append(
            f"{verified_missing} active+verified card_prints have no release_product_code "
            "or no artwork_key, both of which the old verified check requires"
        )
    if old_key_duplicates:
        problems.append(
            f"{old_key_duplicates} duplicate group(s) exist under the old identity "
            "(canonical_card_id, language, treatment, release_product_code, artwork_key), "
            "so the old unique index cannot be recreated"
        )

    if problems:
        raise RuntimeError(
            f"[{revision}] DOWNGRADE ABORTED - the data no longer satisfies the previous "
            "identity contract, and nothing here will coerce it to fit. Resolve these "
            "first:\n  - " + "\n  - ".join(problems)
        )

    print(f"[{revision}] downgrade preflight OK - every row satisfies the previous contract")


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Refuse before touching anything.
    _preflight_upgrade()

    # 2-3. Release treatment from the old contract. Both must go before the
    #      column can be relaxed: the check names treatment explicitly and the
    #      index would keep it identity-bearing.
    op.drop_constraint(VERIFIED_CHECK, 'card_prints', type_='check')
    op.drop_index(IDENTITY_INDEX, table_name='card_prints')

    # 4. treatment becomes optional. No value is rewritten.
    op.alter_column(
        'card_prints', 'treatment', existing_type=sa.String(length=64), nullable=True
    )

    # 5. The new requirements. The placeholder rule the old check carried is
    #    kept inside it, at the same verified-only scope.
    op.create_check_constraint(VERIFIED_CHECK, 'card_prints', NEW_VERIFIED_CHECK_SQL)

    # 6. The new identity, under the same index name, over the same
    #    active+verified population. NULLs cannot weaken it because the check
    #    above forbids a verified row from having either identity field null.
    op.create_index(
        IDENTITY_INDEX,
        'card_prints',
        NEW_IDENTITY_COLUMNS,
        unique=True,
        postgresql_where=sa.text(ACTIVE_VERIFIED),
        sqlite_where=sa.text("is_active = 1 AND verification_status = 'verified'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    _preflight_downgrade()

    op.drop_index(IDENTITY_INDEX, table_name='card_prints')
    op.drop_constraint(VERIFIED_CHECK, 'card_prints', type_='check')

    op.alter_column(
        'card_prints', 'treatment', existing_type=sa.String(length=64), nullable=False
    )

    op.create_check_constraint(VERIFIED_CHECK, 'card_prints', OLD_VERIFIED_CHECK_SQL)
    op.create_index(
        IDENTITY_INDEX,
        'card_prints',
        OLD_IDENTITY_COLUMNS,
        unique=True,
        postgresql_where=sa.text(ACTIVE_VERIFIED),
        sqlite_where=sa.text("is_active = 1 AND verification_status = 'verified'"),
    )
    # release_products, release_product_aliases, release_product_id and
    # official_artwork_variant are all left in place - this only undoes the
    # identity activation, not the infrastructure it activates.
