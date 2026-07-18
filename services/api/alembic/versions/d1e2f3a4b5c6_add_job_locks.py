"""add job_locks

Revision ID: d1e2f3a4b5c6
Revises: 9f3f33e40199
Create Date: 2026-07-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = '9f3f33e40199'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'job_locks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lock_name', sa.String(length=64), nullable=False),
        sa.Column('owner_id', sa.String(length=255), nullable=False),
        sa.Column('acquired_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=16), server_default='active', nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('active', 'released', 'expired')", name='ck_job_locks_status'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_job_locks_lock_name', 'job_locks', ['lock_name'], unique=True)
    op.create_index('ix_job_locks_owner_id', 'job_locks', ['owner_id'])
    op.create_index('ix_job_locks_status', 'job_locks', ['status'])
    op.create_index('ix_job_locks_expires_at', 'job_locks', ['expires_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('job_locks')
