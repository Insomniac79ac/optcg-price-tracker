"""allow manual_import discovery run status

Revision ID: 2acfab78d531
Revises: c1d53b8f0bb5
Create Date: 2026-07-08 08:55:21.990791

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2acfab78d531'
down_revision: Union[str, Sequence[str], None] = 'c1d53b8f0bb5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(
        "ck_snkrdunk_discovery_runs_status", "snkrdunk_discovery_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_snkrdunk_discovery_runs_status",
        "snkrdunk_discovery_runs",
        "status IN ('running', 'completed', 'completed_with_warnings', 'blocked', "
        "'failed', 'manual_import')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_snkrdunk_discovery_runs_status", "snkrdunk_discovery_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_snkrdunk_discovery_runs_status",
        "snkrdunk_discovery_runs",
        "status IN ('running', 'completed', 'completed_with_warnings', 'blocked', 'failed')",
    )
