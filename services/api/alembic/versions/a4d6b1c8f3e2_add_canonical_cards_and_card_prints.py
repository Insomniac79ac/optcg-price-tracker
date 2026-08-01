"""add canonical_cards and card_prints

Revision ID: a4d6b1c8f3e2
Revises: f35ff2f33090
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4d6b1c8f3e2'
down_revision: Union[str, Sequence[str], None] = 'f35ff2f33090'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'canonical_cards',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('card_code', sa.String(length=64), nullable=False),
        sa.Column('name_en', sa.String(length=255), nullable=True),
        sa.Column('name_jp', sa.String(length=255), nullable=True),
        sa.Column('original_set_code', sa.String(length=32), nullable=False),
        sa.Column('rarity', sa.String(length=32), nullable=False),
        sa.Column('card_type', sa.String(length=64), nullable=False),
        sa.Column('colors', sa.JSON(), nullable=True),
        sa.Column('cost', sa.Integer(), nullable=True),
        sa.Column('power', sa.Integer(), nullable=True),
        sa.Column('counter', sa.Integer(), nullable=True),
        sa.Column('attribute', sa.String(length=64), nullable=True),
        sa.Column('effect_text', sa.Text(), nullable=True),
        sa.Column('trigger_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('card_code', name='uq_canonical_cards_card_code'),
        sa.CheckConstraint(
            "trim(original_set_code, ' \t\n\r') <> ''",
            name='ck_canonical_cards_original_set_code_not_blank',
        ),
        sa.CheckConstraint(
            "trim(rarity, ' \t\n\r') <> ''",
            name='ck_canonical_cards_rarity_not_blank',
        ),
        sa.CheckConstraint(
            "trim(card_type, ' \t\n\r') <> ''",
            name='ck_canonical_cards_card_type_not_blank',
        ),
        sa.CheckConstraint(
            "(name_en IS NOT NULL AND trim(name_en, ' \t\n\r') <> '') OR "
            "(name_jp IS NOT NULL AND trim(name_jp, ' \t\n\r') <> '')",
            name='ck_canonical_cards_requires_a_name',
        ),
    )
    op.create_index('ix_canonical_cards_original_set_code', 'canonical_cards', ['original_set_code'])
    op.create_index('ix_canonical_cards_rarity', 'canonical_cards', ['rarity'])

    op.create_table(
        'card_prints',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('canonical_card_id', sa.Integer(), nullable=False),
        sa.Column('language', sa.String(length=8), nullable=False),
        sa.Column('treatment', sa.String(length=64), nullable=False),
        sa.Column('release_product_code', sa.String(length=64), nullable=True),
        sa.Column('artwork_key', sa.String(length=64), nullable=True),
        sa.Column('image_url', sa.String(length=1024), nullable=True),
        sa.Column('artist', sa.String(length=255), nullable=True),
        sa.Column(
            'verification_status', sa.String(length=16), server_default='unverified', nullable=False
        ),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "verification_status IN ('verified', 'unverified', 'needs_review')",
            name='ck_card_prints_verification_status',
        ),
        sa.CheckConstraint(
            "verification_status <> 'verified' OR ("
            "treatment IS NOT NULL AND trim(treatment, ' \t\n\r') <> '' AND "
            "lower(trim(treatment, ' \t\n\r')) <> 'unknown' AND "
            "release_product_code IS NOT NULL AND "
            "artwork_key IS NOT NULL"
            ")",
            name='ck_card_prints_verified_requires_fields',
        ),
        sa.CheckConstraint(
            "release_product_code IS NULL OR ("
            "trim(release_product_code, ' \t\n\r') <> '' AND "
            "lower(trim(release_product_code, ' \t\n\r')) <> 'original'"
            ")",
            name='ck_card_prints_no_fake_release_product_code',
        ),
        sa.CheckConstraint(
            "artwork_key IS NULL OR ("
            "trim(artwork_key, ' \t\n\r') <> '' AND "
            "lower(trim(artwork_key, ' \t\n\r')) <> 'original'"
            ")",
            name='ck_card_prints_no_fake_artwork_key',
        ),
        sa.ForeignKeyConstraint(
            ['canonical_card_id'], ['canonical_cards.id'], ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_card_prints_canonical_card_id', 'card_prints', ['canonical_card_id'])
    op.create_index('ix_card_prints_language', 'card_prints', ['language'])
    op.create_index('ix_card_prints_is_active', 'card_prints', ['is_active'])
    op.create_index(
        'uq_card_prints_active_verified_identity',
        'card_prints',
        ['canonical_card_id', 'language', 'treatment', 'release_product_code', 'artwork_key'],
        unique=True,
        postgresql_where=sa.text("is_active = true AND verification_status = 'verified'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('card_prints')
    op.drop_table('canonical_cards')
