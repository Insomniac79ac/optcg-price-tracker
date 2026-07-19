"""add file_jobs

Revision ID: a3f7c9e1b5d2
Revises: d1e2f3a4b5c6
Create Date: 2026-07-19 08:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f7c9e1b5d2'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'file_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_type', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), server_default='queued', nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('original_filename', sa.String(length=255), nullable=True),
        sa.Column('input_file_path', sa.String(length=500), nullable=True),
        sa.Column('output_file_path', sa.String(length=500), nullable=True),
        sa.Column('output_filename', sa.String(length=255), nullable=True),
        sa.Column('content_type', sa.String(length=100), nullable=True),
        sa.Column('dry_run', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('mode', sa.String(length=32), nullable=True),
        sa.Column('progress_current', sa.Integer(), server_default='0', nullable=False),
        sa.Column('progress_total', sa.Integer(), nullable=True),
        sa.Column('summary_json', sa.JSON(), nullable=True),
        sa.Column('errors_json', sa.JSON(), nullable=True),
        sa.Column('warnings_json', sa.JSON(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "job_type IN ('collection_import', 'wishlist_import', 'collection_export', "
            "'wishlist_export', 'backup_export', 'backup_validate', 'backup_restore')",
            name='ck_file_jobs_job_type',
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'success', 'failed', 'cancelled')",
            name='ck_file_jobs_status',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_file_jobs_job_type', 'file_jobs', ['job_type'])
    op.create_index('ix_file_jobs_status', 'file_jobs', ['status'])
    op.create_index('ix_file_jobs_user_id', 'file_jobs', ['user_id'])
    op.create_index('ix_file_jobs_created_at', 'file_jobs', ['created_at'])
    op.create_index('ix_file_jobs_finished_at', 'file_jobs', ['finished_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('file_jobs')
