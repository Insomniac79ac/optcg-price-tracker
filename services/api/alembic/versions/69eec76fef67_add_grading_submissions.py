"""add grading submissions

Revision ID: 69eec76fef67
Revises: 3773b932102e
Create Date: 2026-07-14 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '69eec76fef67'
down_revision: Union[str, Sequence[str], None] = '3773b932102e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'grading_submissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('collection_item_id', sa.Integer(), nullable=False),
        sa.Column('grading_company', sa.String(length=32), nullable=False),
        sa.Column('submission_name', sa.String(length=255), nullable=True),
        sa.Column('submission_status', sa.String(length=32), server_default='planned', nullable=False),
        sa.Column('declared_value_jpy', sa.Integer(), nullable=True),
        sa.Column('grading_fee_jpy', sa.Integer(), nullable=True),
        sa.Column('shipping_fee_jpy', sa.Integer(), nullable=True),
        sa.Column('insurance_fee_jpy', sa.Integer(), nullable=True),
        sa.Column('other_fee_jpy', sa.Integer(), nullable=True),
        sa.Column('total_cost_jpy', sa.Integer(), nullable=True),
        sa.Column('submitted_at', sa.Date(), nullable=True),
        sa.Column('received_at', sa.Date(), nullable=True),
        sa.Column('expected_return_date', sa.Date(), nullable=True),
        sa.Column('tracking_number', sa.String(length=255), nullable=True),
        sa.Column('final_grade', sa.String(length=32), nullable=True),
        sa.Column('cert_number', sa.String(length=64), nullable=True),
        sa.Column('graded_value_jpy', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['collection_item_id'], ['collection_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "submission_status IN ('planned', 'preparing', 'submitted', 'grading', "
            "'shipped_back', 'received', 'cancelled')",
            name='ck_grading_submissions_status',
        ),
    )
    op.create_index(
        'ix_grading_submissions_collection_item_id', 'grading_submissions', ['collection_item_id']
    )
    op.create_index(
        'ix_grading_submissions_submission_status', 'grading_submissions', ['submission_status']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_grading_submissions_submission_status', table_name='grading_submissions')
    op.drop_index('ix_grading_submissions_collection_item_id', table_name='grading_submissions')
    op.drop_table('grading_submissions')
