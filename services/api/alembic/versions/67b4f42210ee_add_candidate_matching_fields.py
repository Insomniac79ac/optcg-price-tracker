"""add candidate matching fields and migrate match_status vocabulary

Revision ID: 67b4f42210ee
Revises: c732eaf8e4bb
Create Date: 2026-07-20 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '67b4f42210ee'
down_revision: Union[str, Sequence[str], None] = 'c732eaf8e4bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'snkrdunk_candidates', sa.Column('best_match_card_id', sa.Integer(), nullable=True)
    )
    op.add_column(
        'snkrdunk_candidates', sa.Column('best_match_score', sa.Integer(), nullable=True)
    )
    op.add_column(
        'snkrdunk_candidates',
        sa.Column('best_match_confidence_label', sa.String(length=16), nullable=True),
    )
    op.add_column(
        'snkrdunk_candidates', sa.Column('match_explanation_json', sa.JSON(), nullable=True)
    )
    op.add_column(
        'snkrdunk_candidates', sa.Column('ambiguous_matches_json', sa.JSON(), nullable=True)
    )
    op.create_foreign_key(
        'fk_snkrdunk_candidates_best_match_card_id',
        'snkrdunk_candidates', 'cards',
        ['best_match_card_id'], ['id'],
        ondelete='SET NULL',
    )

    # match_status vocabulary change: pending/auto_matched/needs_review/
    # rejected -> unmatched/suggested/ambiguous/matched/rejected - see
    # app/models/snkrdunk_candidate.py's MATCH_STATUSES docstring for what
    # each new value means. Existing rows are remapped to their closest
    # semantic equivalent (rejected is unchanged); nothing maps to the new
    # 'ambiguous' value here, since that's a property of a *ranking* over
    # every card (see app.services.card_matching) that a pre-migration row
    # never had computed - a rematch is required to discover it.
    op.execute("UPDATE snkrdunk_candidates SET match_status = 'unmatched' WHERE match_status = 'pending'")
    op.execute("UPDATE snkrdunk_candidates SET match_status = 'matched' WHERE match_status = 'auto_matched'")
    op.execute("UPDATE snkrdunk_candidates SET match_status = 'suggested' WHERE match_status = 'needs_review'")

    op.drop_constraint('ck_snkrdunk_candidates_match_status', 'snkrdunk_candidates', type_='check')
    op.create_check_constraint(
        'ck_snkrdunk_candidates_match_status',
        'snkrdunk_candidates',
        "match_status IN ('unmatched', 'suggested', 'ambiguous', 'matched', 'rejected')",
    )
    op.alter_column(
        'snkrdunk_candidates', 'match_status',
        server_default='unmatched',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        'snkrdunk_candidates', 'match_status',
        server_default='pending',
    )
    op.drop_constraint('ck_snkrdunk_candidates_match_status', 'snkrdunk_candidates', type_='check')

    op.execute("UPDATE snkrdunk_candidates SET match_status = 'pending' WHERE match_status = 'unmatched'")
    op.execute("UPDATE snkrdunk_candidates SET match_status = 'auto_matched' WHERE match_status = 'matched'")
    op.execute("UPDATE snkrdunk_candidates SET match_status = 'needs_review' WHERE match_status IN ('suggested', 'ambiguous')")

    op.create_check_constraint(
        'ck_snkrdunk_candidates_match_status',
        'snkrdunk_candidates',
        "match_status IN ('pending', 'auto_matched', 'needs_review', 'rejected')",
    )

    op.drop_constraint(
        'fk_snkrdunk_candidates_best_match_card_id', 'snkrdunk_candidates', type_='foreignkey'
    )
    op.drop_column('snkrdunk_candidates', 'ambiguous_matches_json')
    op.drop_column('snkrdunk_candidates', 'match_explanation_json')
    op.drop_column('snkrdunk_candidates', 'best_match_confidence_label')
    op.drop_column('snkrdunk_candidates', 'best_match_score')
    op.drop_column('snkrdunk_candidates', 'best_match_card_id')
