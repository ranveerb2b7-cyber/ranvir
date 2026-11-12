"""upload batch details

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-12 07:33:21.319790+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_batch_rows",
        sa.Column(
            "warnings", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
    )
    op.create_index(
        op.f("ix_product_batch_rows_batch_id_status_row_number"),
        "product_batch_rows",
        ["batch_id", "status", "row_number"],
        unique=False,
    )
    op.add_column(
        "product_batches",
        sa.Column(
            "duplicate_in_file_rows", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.add_column(
        "product_batches",
        sa.Column(
            "duplicate_existing_rows", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.add_column(
        "product_batches",
        sa.Column("committed_rows", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "product_batches",
        sa.Column("column_mapping", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "product_batches", sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("product_batches", sa.Column("error_code", sa.Text(), nullable=True))
    # Autogenerate does not detect CHECK constraints.
    op.create_check_constraint(
        op.f("ck_product_batches_extra_counts_non_negative"),
        "product_batches",
        "duplicate_in_file_rows >= 0 AND duplicate_existing_rows >= 0 AND committed_rows >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_product_batches_extra_counts_non_negative"), "product_batches", type_="check"
    )
    op.drop_column("product_batches", "error_code")
    op.drop_column("product_batches", "parsed_at")
    op.drop_column("product_batches", "column_mapping")
    op.drop_column("product_batches", "committed_rows")
    op.drop_column("product_batches", "duplicate_existing_rows")
    op.drop_column("product_batches", "duplicate_in_file_rows")
    op.drop_index(
        op.f("ix_product_batch_rows_batch_id_status_row_number"), table_name="product_batch_rows"
    )
    op.drop_column("product_batch_rows", "warnings")
