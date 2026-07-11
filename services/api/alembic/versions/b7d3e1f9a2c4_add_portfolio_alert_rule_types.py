"""add portfolio alert rule types

Revision ID: b7d3e1f9a2c4
Revises: a1c2e4f6b8d0
Create Date: 2026-07-11 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d3e1f9a2c4'
down_revision: Union[str, Sequence[str], None] = 'a1c2e4f6b8d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("ck_alert_rules_rule_type", "alert_rules", type_="check")
    op.create_check_constraint(
        "ck_alert_rules_rule_type",
        "alert_rules",
        "rule_type IN ('price_change_pct', 'yuyutei_buy_change_pct', "
        "'stock_status_change', 'refresh_failed', 'owned_card_above_target_sell', "
        "'owned_card_below_cost_basis', 'portfolio_value_change_pct')",
    )

    op.drop_constraint("ck_alert_events_event_type", "alert_events", type_="check")
    op.create_check_constraint(
        "ck_alert_events_event_type",
        "alert_events",
        "event_type IN ('price_up', 'price_down', 'yuyutei_buy_up', 'stock_out', "
        "'refresh_failed', 'owned_card_above_target_sell', 'owned_card_below_cost_basis', "
        "'portfolio_value_up', 'portfolio_value_down')",
    )

    alert_rules_table = sa.table(
        'alert_rules',
        sa.column('name', sa.String),
        sa.column('rule_type', sa.String),
        sa.column('source_name', sa.String),
        sa.column('price_type', sa.String),
        sa.column('threshold_pct', sa.Float),
        sa.column('is_active', sa.Boolean),
    )
    op.bulk_insert(
        alert_rules_table,
        [
            {
                'name': 'Owned card above target sell',
                'rule_type': 'owned_card_above_target_sell',
                'source_name': None,
                'price_type': None,
                'threshold_pct': None,
                'is_active': True,
            },
            {
                'name': 'Owned card below cost basis 15%',
                'rule_type': 'owned_card_below_cost_basis',
                'source_name': None,
                'price_type': None,
                'threshold_pct': 15.0,
                'is_active': False,
            },
            {
                'name': 'Portfolio value change 10%',
                'rule_type': 'portfolio_value_change_pct',
                'source_name': None,
                'price_type': None,
                'threshold_pct': 10.0,
                'is_active': False,
            },
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DELETE FROM alert_rules WHERE rule_type IN "
        "('owned_card_above_target_sell', 'owned_card_below_cost_basis', "
        "'portfolio_value_change_pct')"
    )

    op.drop_constraint("ck_alert_events_event_type", "alert_events", type_="check")
    op.create_check_constraint(
        "ck_alert_events_event_type",
        "alert_events",
        "event_type IN ('price_up', 'price_down', 'yuyutei_buy_up', 'stock_out', "
        "'refresh_failed')",
    )

    op.drop_constraint("ck_alert_rules_rule_type", "alert_rules", type_="check")
    op.create_check_constraint(
        "ck_alert_rules_rule_type",
        "alert_rules",
        "rule_type IN ('price_change_pct', 'yuyutei_buy_change_pct', "
        "'stock_status_change', 'refresh_failed')",
    )
