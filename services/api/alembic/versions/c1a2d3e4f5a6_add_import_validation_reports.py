"""add import_validation_reports table

Revision ID: c1a2d3e4f5a6
Revises: b8f3d6a9c1e5
Create Date: 2026-07-21 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1a2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'b8f3d6a9c1e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'import_validation_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('import_type', sa.String(length=32), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=True),
        sa.Column('valid', sa.Boolean(), nullable=False),
        sa.Column('strict', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('total_rows', sa.Integer(), server_default='0', nullable=False),
        sa.Column('valid_rows', sa.Integer(), server_default='0', nullable=False),
        sa.Column('error_rows', sa.Integer(), server_default='0', nullable=False),
        sa.Column('warning_rows', sa.Integer(), server_default='0', nullable=False),
        sa.Column('duplicate_rows', sa.Integer(), server_default='0', nullable=False),
        sa.Column('report_payload_json', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_import_validation_reports_created_at', 'import_validation_reports', ['created_at']
    )
    op.create_index(
        'ix_import_validation_reports_import_type', 'import_validation_reports', ['import_type']
    )
    op.create_index(
        'ix_import_validation_reports_valid', 'import_validation_reports', ['valid']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_import_validation_reports_valid', table_name='import_validation_reports')
    op.drop_index('ix_import_validation_reports_import_type', table_name='import_validation_reports')
    op.drop_index('ix_import_validation_reports_created_at', table_name='import_validation_reports')
    op.drop_table('import_validation_reports')
