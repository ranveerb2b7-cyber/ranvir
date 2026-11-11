"""Seed reference data: Amazon.in marketplace and the trial plan.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-11

Trial plan limits are PROVISIONAL placeholders pending a pricing decision (M13); they are
flagged with features.provisional = true.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from sellerscope.core.ids import uuid7

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO marketplaces (id, code, name, country, currency, "
            "external_marketplace_id, identifier_label, is_enabled) "
            "VALUES (:id, 'amazon_in', 'Amazon.in', 'IN', 'INR', 'A21TJRUUN4KGV', 'ASIN', true)"
        ),
        {"id": uuid7()},
    )
    conn.execute(
        sa.text(
            "INSERT INTO plans (id, code, name, max_products, max_scans_per_month, max_members, "
            "min_scan_interval_minutes, features) VALUES "
            "(:id, 'trial', 'Trial', 100, 3000, 3, 1440, '{\"provisional\": true}'::jsonb)"
        ),
        {"id": uuid7()},
    )


def downgrade() -> None:
    op.execute("DELETE FROM plans WHERE code = 'trial'")
    op.execute("DELETE FROM marketplaces WHERE code = 'amazon_in'")
