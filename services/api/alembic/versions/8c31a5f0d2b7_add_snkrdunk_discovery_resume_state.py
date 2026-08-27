"""add snkrdunk discovery resume state

Bounded SNKRDUNK discovery walks the publisher's sitemap a few dozen URLs at a
time, so it only makes progress if each run can resume where the last stopped.
Before this column that state existed only in memory: a fresh process or a
Railway restart began again from the same offsets.

The payload is compact and versioned - one integer per anchor plus a two-integer
sequential cursor, roughly 400 bytes for the six anchors in use - and never
holds HTML, listing bodies, secrets, or an array of consumed URLs. See
worker.jobs.snkrdunk_checkpoint for the shape and the selection rule.

Nullable, with no backfill: every existing run row keeps NULL, which the loader
skips rather than reading as "no progress".

Revision ID: 8c31a5f0d2b7
Revises: d1c48b7f36ae
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op

revision: str = "8c31a5f0d2b7"
down_revision: str | None = "d1c48b7f36ae"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "snkrdunk_discovery_runs",
        sa.Column("resume_state_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("snkrdunk_discovery_runs", "resume_state_json")
