"""allow blocked and completed_with_warnings discovery run statuses

Revision ID: c1d53b8f0bb5
Revises: 95e04918e3c1
Create Date: 2026-07-08 08:24:16.206475

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d53b8f0bb5'
down_revision: Union[str, Sequence[str], None] = '95e04918e3c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_check_constraint(
        "ck_snkrdunk_discovery_runs_status",
        "snkrdunk_discovery_runs",
        "status IN ('running', 'completed', 'completed_with_warnings', 'blocked', 'failed')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_snkrdunk_discovery_runs_status", "snkrdunk_discovery_runs", type_="check"
    )
