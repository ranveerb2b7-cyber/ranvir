"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-11 11:48:21.547772+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Trusted extensions: creatable by the database owner without superuser.
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "marketplaces",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("external_marketplace_id", sa.Text(), nullable=True),
        sa.Column("identifier_label", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marketplaces")),
        sa.UniqueConstraint("code", name=op.f("uq_marketplaces_code")),
    )
    op.create_table(
        "plans",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("max_products", sa.Integer(), nullable=False),
        sa.Column("max_scans_per_month", sa.Integer(), nullable=False),
        sa.Column("max_members", sa.Integer(), nullable=False),
        sa.Column("min_scan_interval_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "features",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "max_products > 0 AND max_scans_per_month > 0 AND max_members > 0 AND min_scan_interval_minutes > 0",
            name=op.f("ck_plans_limits_positive"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
        sa.UniqueConstraint("code", name=op.f("uq_plans_code")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "organizations",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", postgresql.CITEXT(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_organizations_created_by"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
    )
    op.create_table(
        "alert_rules",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("rule_type", sa.Text(), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "scope",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "channels",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{in_app}'"),
            nullable=False,
        ),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "rule_type IN ('new_seller', 'seller_count_above', 'price_below', 'offer_count_change', 'scan_failed')",
            name=op.f("ck_alert_rules_rule_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_alert_rules_created_by"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_alert_rules_organization_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_rules")),
        sa.UniqueConstraint("organization_id", "id", name="uq_alert_rules_org_id"),
    )
    op.create_table(
        "audit_logs",
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=True),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actor_type IN ('user', 'system', 'extension')",
            name=op.f("ck_audit_logs_actor_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_audit_logs_organization_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
        sa.UniqueConstraint("organization_id", "id", name="uq_audit_logs_org_id"),
    )
    op.create_index(
        op.f("ix_audit_logs_organization_id"),
        "audit_logs",
        ["organization_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "extension_tokens",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column(
            "scopes", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_extension_tokens_organization_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_extension_tokens_user_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extension_tokens")),
        sa.UniqueConstraint("organization_id", "id", name="uq_extension_tokens_org_id"),
        sa.UniqueConstraint("token_hash", name=op.f("uq_extension_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_extension_tokens_user_id"), "extension_tokens", ["user_id"], unique=False
    )
    op.create_table(
        "invitations",
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("invited_by", sa.UUID(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'analyst', 'viewer')",
            name=op.f("ck_invitations_role_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["users.id"],
            name=op.f("fk_invitations_invited_by"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_invitations_organization_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.UniqueConstraint("organization_id", "id", name="uq_invitations_org_id"),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invitations_token_hash")),
    )
    op.create_index(
        "uq_invitations_org_email_pending",
        "invitations",
        ["organization_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )
    op.create_table(
        "marketplace_connections",
        sa.Column("marketplace_id", sa.UUID(), nullable=False),
        sa.Column("connection_type", sa.Text(), nullable=False),
        sa.Column("external_account_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("encrypted_secret", sa.LargeBinary(), nullable=True),
        sa.Column("encryption_key_id", sa.Text(), nullable=True),
        sa.Column(
            "granted_scopes",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "connection_type IN ('sp_api_oauth', 'sp_api_self_auth')",
            name=op.f("ck_marketplace_connections_connection_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'revoked', 'error')",
            name=op.f("ck_marketplace_connections_status_valid"),
        ),
        sa.CheckConstraint(
            "(encrypted_secret IS NULL) = (encryption_key_id IS NULL)",
            name=op.f("ck_marketplace_connections_secret_has_key"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_marketplace_connections_created_by"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["marketplace_id"],
            ["marketplaces.id"],
            name=op.f("fk_marketplace_connections_marketplace_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_marketplace_connections_organization_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marketplace_connections")),
        sa.UniqueConstraint("organization_id", "id", name="uq_marketplace_connections_org_id"),
        sa.UniqueConstraint(
            "organization_id",
            "marketplace_id",
            "external_account_id",
            name=op.f(
                "uq_marketplace_connections_organization_id_marketplace_id_external_account_id"
            ),
        ),
    )
    op.create_table(
        "organization_members",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'analyst', 'viewer')",
            name=op.f("ck_organization_members_role_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended')", name=op.f("ck_organization_members_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_members_organization_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_organization_members_user_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_members")),
        sa.UniqueConstraint("organization_id", "id", name="uq_organization_members_org_id"),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            name=op.f("uq_organization_members_organization_id_user_id"),
        ),
    )
    op.create_index(
        op.f("ix_organization_members_user_id"), "organization_members", ["user_id"], unique=False
    )
    op.create_table(
        "product_batches",
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'uploaded'"), nullable=False),
        sa.Column("total_rows", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("valid_rows", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("invalid_rows", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("duplicate_rows", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('uploaded', 'parsing', 'preview_ready', 'committed', 'failed', 'discarded')",
            name=op.f("ck_product_batches_status_valid"),
        ),
        sa.CheckConstraint(
            "file_size_bytes > 0", name=op.f("ck_product_batches_file_size_positive")
        ),
        sa.CheckConstraint(
            "total_rows >= 0 AND valid_rows >= 0 AND invalid_rows >= 0 AND duplicate_rows >= 0",
            name=op.f("ck_product_batches_row_counts_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_product_batches_organization_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_product_batches_uploaded_by"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_batches")),
        sa.UniqueConstraint("organization_id", "id", name="uq_product_batches_org_id"),
    )
    op.create_index(
        op.f("ix_product_batches_organization_id"),
        "product_batches",
        ["organization_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "report_exports",
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("report_type", sa.Text(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column(
            "filters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "format IN ('xlsx', 'csv')", name=op.f("ck_report_exports_format_valid")
        ),
        sa.CheckConstraint(
            "report_type IN ('product', 'marketplace', 'brand', 'seller', 'scan_summary', 'errors')",
            name=op.f("ck_report_exports_report_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'expired')",
            name=op.f("ck_report_exports_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_report_exports_organization_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_report_exports_requested_by"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_exports")),
        sa.UniqueConstraint("organization_id", "id", name="uq_report_exports_org_id"),
    )
    op.create_index(
        op.f("ix_report_exports_organization_id"),
        "report_exports",
        ["organization_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "scan_jobs",
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("total_items", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("completed_items", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failed_items", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("unavailable_items", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cancelled_items", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'completed_with_errors', 'failed', 'cancelled')",
            name=op.f("ck_scan_jobs_status_valid"),
        ),
        sa.CheckConstraint(
            "trigger IN ('manual', 'scheduled', 'extension', 'api')",
            name=op.f("ck_scan_jobs_trigger_valid"),
        ),
        sa.CheckConstraint(
            "total_items >= 0 AND completed_items >= 0 AND failed_items >= 0 AND unavailable_items >= 0 AND cancelled_items >= 0",
            name=op.f("ck_scan_jobs_counters_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_scan_jobs_organization_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_scan_jobs_requested_by"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_jobs")),
        sa.UniqueConstraint("organization_id", "id", name="uq_scan_jobs_org_id"),
    )
    op.create_index(
        op.f("ix_scan_jobs_organization_id"),
        "scan_jobs",
        ["organization_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "seller_profiles",
        sa.Column("marketplace_id", sa.UUID(), nullable=False),
        sa.Column("external_seller_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("display_name_source", sa.Text(), nullable=True),
        sa.Column("is_marketplace_retail", sa.Boolean(), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "tags", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "display_name IS NULL OR display_name_source IS NOT NULL",
            name=op.f("ck_seller_profiles_display_name_has_source"),
        ),
        sa.ForeignKeyConstraint(
            ["marketplace_id"],
            ["marketplaces.id"],
            name=op.f("fk_seller_profiles_marketplace_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_seller_profiles_organization_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_seller_profiles")),
        sa.UniqueConstraint("organization_id", "id", name="uq_seller_profiles_org_id"),
        sa.UniqueConstraint(
            "organization_id",
            "marketplace_id",
            "external_seller_id",
            name=op.f("uq_seller_profiles_organization_id_marketplace_id_external_seller_id"),
        ),
    )
    op.create_table(
        "subscriptions",
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("provider_customer_id", sa.Text(), nullable=True),
        sa.Column("provider_subscription_id", sa.Text(), nullable=True),
        sa.Column(
            "scans_used_this_period", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider IS NULL OR provider IN ('razorpay', 'stripe')",
            name=op.f("ck_subscriptions_provider_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('trialing', 'active', 'past_due', 'cancelled')",
            name=op.f("ck_subscriptions_status_valid"),
        ),
        sa.CheckConstraint(
            "scans_used_this_period >= 0", name=op.f("ck_subscriptions_scans_used_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_subscriptions_organization_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name=op.f("fk_subscriptions_plan_id"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
        sa.UniqueConstraint("organization_id", "id", name="uq_subscriptions_org_id"),
        sa.UniqueConstraint(
            "provider_subscription_id", name=op.f("uq_subscriptions_provider_subscription_id")
        ),
    )
    op.create_index(
        "uq_subscriptions_org_live",
        "subscriptions",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('trialing', 'active', 'past_due')"),
    )
    op.create_table(
        "products",
        sa.Column("marketplace_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("product_name", sa.Text(), nullable=True),
        sa.Column("brand_name", sa.Text(), nullable=True),
        sa.Column("catalog_title", sa.Text(), nullable=True),
        sa.Column("catalog_brand", sa.Text(), nullable=True),
        sa.Column(
            "identifier_status", sa.Text(), server_default=sa.text("'format_valid'"), nullable=False
        ),
        sa.Column(
            "monitoring_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("scan_frequency_minutes", sa.Integer(), nullable=True),
        sa.Column("source_batch_id", sa.UUID(), nullable=True),
        sa.Column("latest_scan_result_id", sa.UUID(), nullable=True),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "identifier_status IN ('format_valid', 'verified', 'not_found', 'unverifiable')",
            name=op.f("ck_products_identifier_status_valid"),
        ),
        sa.CheckConstraint(
            "external_id = upper(btrim(external_id)) AND length(external_id) > 0",
            name=op.f("ck_products_external_id_normalized"),
        ),
        sa.CheckConstraint(
            "scan_frequency_minutes IS NULL OR scan_frequency_minutes > 0",
            name=op.f("ck_products_scan_frequency_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_products_created_by"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["marketplace_id"],
            ["marketplaces.id"],
            name=op.f("fk_products_marketplace_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_batch_id"],
            ["product_batches.organization_id", "product_batches.id"],
            name=op.f("fk_products_organization_id_source_batch_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_products_organization_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("organization_id", "id", name="uq_products_org_id"),
    )
    op.create_index(
        op.f("ix_products_organization_id_brand_name"),
        "products",
        ["organization_id", "brand_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_products_organization_id_marketplace_id"),
        "products",
        ["organization_id", "marketplace_id"],
        unique=False,
    )
    op.create_index(
        "ix_products_product_name_trgm",
        "products",
        ["product_name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"product_name": "gin_trgm_ops"},
    )
    op.create_index(
        "uq_products_org_marketplace_external_id_live",
        "products",
        ["organization_id", "marketplace_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "product_batch_rows",
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("marketplace_code", sa.Text(), nullable=True),
        sa.Column("external_id_normalized", sa.Text(), nullable=True),
        sa.Column("brand_name", sa.Text(), nullable=True),
        sa.Column("product_name", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "errors", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('valid', 'invalid', 'duplicate_in_file', 'duplicate_existing')",
            name=op.f("ck_product_batch_rows_status_valid"),
        ),
        sa.CheckConstraint(
            "row_number > 0", name=op.f("ck_product_batch_rows_row_number_positive")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "batch_id"],
            ["product_batches.organization_id", "product_batches.id"],
            name=op.f("fk_product_batch_rows_organization_id_batch_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "product_id"],
            ["products.organization_id", "products.id"],
            name=op.f("fk_product_batch_rows_organization_id_product_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_product_batch_rows_organization_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_batch_rows")),
        sa.UniqueConstraint(
            "batch_id", "row_number", name=op.f("uq_product_batch_rows_batch_id_row_number")
        ),
        sa.UniqueConstraint("organization_id", "id", name="uq_product_batch_rows_org_id"),
    )
    op.create_table(
        "scan_job_items",
        sa.Column("scan_job_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'partial', 'unavailable', 'failed', 'cancelled')",
            name=op.f("ck_scan_job_items_status_valid"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name=op.f("ck_scan_job_items_attempt_count_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "product_id"],
            ["products.organization_id", "products.id"],
            name=op.f("fk_scan_job_items_organization_id_product_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "scan_job_id"],
            ["scan_jobs.organization_id", "scan_jobs.id"],
            name=op.f("fk_scan_job_items_organization_id_scan_job_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_scan_job_items_organization_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_job_items")),
        sa.UniqueConstraint("organization_id", "id", name="uq_scan_job_items_org_id"),
        sa.UniqueConstraint(
            "scan_job_id", "product_id", name=op.f("uq_scan_job_items_scan_job_id_product_id")
        ),
    )
    op.create_index(
        "ix_scan_job_items_dispatch",
        "scan_job_items",
        ["status", "next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )
    op.create_index(
        "uq_scan_job_items_product_active",
        "scan_job_items",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )
    op.create_table(
        "scan_results",
        sa.Column("scan_job_item_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("marketplace_connection_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("data_source", sa.Text(), nullable=False),
        sa.Column("total_offer_count", sa.Integer(), nullable=True),
        sa.Column(
            "observed_offer_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("unique_seller_count", sa.Integer(), nullable=True),
        sa.Column("is_offer_list_truncated", sa.Boolean(), nullable=True),
        sa.Column("offer_count_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("lowest_observed_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("highest_observed_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("buy_box_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column(
            "limitations",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("raw_payload_key", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ok', 'partial', 'not_found', 'unavailable', 'error')",
            name=op.f("ck_scan_results_status_valid"),
        ),
        sa.CheckConstraint(
            "(lowest_observed_price IS NULL AND highest_observed_price IS NULL AND buy_box_price IS NULL) OR currency IS NOT NULL",
            name=op.f("ck_scan_results_prices_have_currency"),
        ),
        sa.CheckConstraint(
            "lowest_observed_price IS NULL OR highest_observed_price IS NULL OR lowest_observed_price <= highest_observed_price",
            name=op.f("ck_scan_results_price_range_valid"),
        ),
        sa.CheckConstraint(
            "observed_offer_count >= 0", name=op.f("ck_scan_results_observed_offers_valid")
        ),
        sa.CheckConstraint(
            "total_offer_count IS NULL OR total_offer_count >= 0",
            name=op.f("ck_scan_results_total_offers_valid"),
        ),
        sa.CheckConstraint(
            "unique_seller_count IS NULL OR (unique_seller_count >= 0 AND unique_seller_count <= observed_offer_count)",
            name=op.f("ck_scan_results_unique_sellers_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "marketplace_connection_id"],
            ["marketplace_connections.organization_id", "marketplace_connections.id"],
            name=op.f("fk_scan_results_organization_id_marketplace_connection_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "product_id"],
            ["products.organization_id", "products.id"],
            name=op.f("fk_scan_results_organization_id_product_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "scan_job_item_id"],
            ["scan_job_items.organization_id", "scan_job_items.id"],
            name=op.f("fk_scan_results_organization_id_scan_job_item_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_scan_results_organization_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_results")),
        sa.UniqueConstraint("organization_id", "id", name="uq_scan_results_org_id"),
        sa.UniqueConstraint("scan_job_item_id", name=op.f("uq_scan_results_scan_job_item_id")),
    )
    op.create_index(
        op.f("ix_scan_results_organization_id_product_id"),
        "scan_results",
        ["organization_id", "product_id", sa.literal_column("retrieved_at DESC")],
        unique=False,
    )
    op.create_table(
        "product_offers",
        sa.Column("scan_result_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("seller_profile_id", sa.UUID(), nullable=True),
        sa.Column("listing_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("shipping_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("landed_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("condition", sa.Text(), nullable=True),
        sa.Column("sub_condition", sa.Text(), nullable=True),
        sa.Column(
            "fulfilment_channel", sa.Text(), server_default=sa.text("'unknown'"), nullable=False
        ),
        sa.Column("is_buy_box_winner", sa.Boolean(), nullable=True),
        sa.Column("is_featured_merchant", sa.Boolean(), nullable=True),
        sa.Column("is_prime", sa.Boolean(), nullable=True),
        sa.Column("seller_feedback_rating", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("seller_feedback_count", sa.Integer(), nullable=True),
        sa.Column("ships_from_country", sa.Text(), nullable=True),
        sa.Column("shipping_time", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "fulfilment_channel IN ('amazon', 'merchant', 'unknown')",
            name=op.f("ck_product_offers_fulfilment_channel_valid"),
        ),
        sa.CheckConstraint(
            "(listing_price IS NULL AND shipping_price IS NULL AND landed_price IS NULL) OR currency IS NOT NULL",
            name=op.f("ck_product_offers_prices_have_currency"),
        ),
        sa.CheckConstraint("position >= 0", name=op.f("ck_product_offers_position_non_negative")),
        sa.ForeignKeyConstraint(
            ["organization_id", "product_id"],
            ["products.organization_id", "products.id"],
            name=op.f("fk_product_offers_organization_id_product_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "scan_result_id"],
            ["scan_results.organization_id", "scan_results.id"],
            name=op.f("fk_product_offers_organization_id_scan_result_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "seller_profile_id"],
            ["seller_profiles.organization_id", "seller_profiles.id"],
            name=op.f("fk_product_offers_organization_id_seller_profile_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_product_offers_organization_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_offers")),
        sa.UniqueConstraint("organization_id", "id", name="uq_product_offers_org_id"),
    )
    op.create_index(
        op.f("ix_product_offers_organization_id_product_id_created_at"),
        "product_offers",
        ["organization_id", "product_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_offers_organization_id_seller_profile_id_created_at"),
        "product_offers",
        ["organization_id", "seller_profile_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_offers_scan_result_id"), "product_offers", ["scan_result_id"], unique=False
    )
    op.create_table(
        "scan_history",
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("scan_result_id", sa.UUID(), nullable=False),
        sa.Column("previous_scan_result_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("seller_profile_id", sa.UUID(), nullable=True),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence IN ('high', 'medium', 'low')",
            name=op.f("ck_scan_history_confidence_valid"),
        ),
        sa.CheckConstraint(
            "event_type IN ('seller_newly_observed', 'seller_no_longer_observed', 'seller_not_observed_inconclusive', 'offer_count_changed', 'price_changed', 'buy_box_changed', 'scan_unavailable')",
            name=op.f("ck_scan_history_event_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "previous_scan_result_id"],
            ["scan_results.organization_id", "scan_results.id"],
            name=op.f("fk_scan_history_organization_id_previous_scan_result_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "product_id"],
            ["products.organization_id", "products.id"],
            name=op.f("fk_scan_history_organization_id_product_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "scan_result_id"],
            ["scan_results.organization_id", "scan_results.id"],
            name=op.f("fk_scan_history_organization_id_scan_result_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "seller_profile_id"],
            ["seller_profiles.organization_id", "seller_profiles.id"],
            name=op.f("fk_scan_history_organization_id_seller_profile_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_scan_history_organization_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_history")),
        sa.UniqueConstraint("organization_id", "id", name="uq_scan_history_org_id"),
    )
    op.create_index(
        op.f("ix_scan_history_organization_id_event_type"),
        "scan_history",
        ["organization_id", "event_type", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        op.f("ix_scan_history_organization_id_product_id"),
        "scan_history",
        ["organization_id", "product_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "alerts",
        sa.Column("alert_rule_id", sa.UUID(), nullable=True),
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.Column("scan_history_id", sa.UUID(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("acknowledged_by", sa.UUID(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "delivered_channels",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')", name=op.f("ck_alerts_severity_valid")
        ),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved')", name=op.f("ck_alerts_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["acknowledged_by"],
            ["users.id"],
            name=op.f("fk_alerts_acknowledged_by"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "alert_rule_id"],
            ["alert_rules.organization_id", "alert_rules.id"],
            name=op.f("fk_alerts_organization_id_alert_rule_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "product_id"],
            ["products.organization_id", "products.id"],
            name=op.f("fk_alerts_organization_id_product_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "scan_history_id"],
            ["scan_history.organization_id", "scan_history.id"],
            name=op.f("fk_alerts_organization_id_scan_history_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_alerts_organization_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
        sa.UniqueConstraint("organization_id", "id", name="uq_alerts_org_id"),
    )
    op.create_index(
        op.f("ix_alerts_organization_id_status"),
        "alerts",
        ["organization_id", "status", sa.literal_column("created_at DESC")],
        unique=False,
    )

    # products <-> scan_results reference each other; add this FK once both exist.
    op.create_foreign_key(
        op.f("fk_products_organization_id_latest_scan_result_id"),
        "products",
        "scan_results",
        ["organization_id", "latest_scan_result_id"],
        ["organization_id", "id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_products_organization_id_latest_scan_result_id"), "products", type_="foreignkey"
    )
    op.drop_index(op.f("ix_alerts_organization_id_status"), table_name="alerts")
    op.drop_table("alerts")
    op.drop_index(op.f("ix_scan_history_organization_id_product_id"), table_name="scan_history")
    op.drop_index(op.f("ix_scan_history_organization_id_event_type"), table_name="scan_history")
    op.drop_table("scan_history")
    op.drop_index(op.f("ix_product_offers_scan_result_id"), table_name="product_offers")
    op.drop_index(
        op.f("ix_product_offers_organization_id_seller_profile_id_created_at"),
        table_name="product_offers",
    )
    op.drop_index(
        op.f("ix_product_offers_organization_id_product_id_created_at"), table_name="product_offers"
    )
    op.drop_table("product_offers")
    op.drop_index(op.f("ix_scan_results_organization_id_product_id"), table_name="scan_results")
    op.drop_table("scan_results")
    op.drop_index(
        "uq_scan_job_items_product_active",
        table_name="scan_job_items",
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )
    op.drop_index(
        "ix_scan_job_items_dispatch",
        table_name="scan_job_items",
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )
    op.drop_table("scan_job_items")
    op.drop_table("product_batch_rows")
    op.drop_index(
        "uq_products_org_marketplace_external_id_live",
        table_name="products",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(
        "ix_products_product_name_trgm",
        table_name="products",
        postgresql_using="gin",
        postgresql_ops={"product_name": "gin_trgm_ops"},
    )
    op.drop_index(op.f("ix_products_organization_id_marketplace_id"), table_name="products")
    op.drop_index(op.f("ix_products_organization_id_brand_name"), table_name="products")
    op.drop_table("products")
    op.drop_index(
        "uq_subscriptions_org_live",
        table_name="subscriptions",
        postgresql_where=sa.text("status IN ('trialing', 'active', 'past_due')"),
    )
    op.drop_table("subscriptions")
    op.drop_table("seller_profiles")
    op.drop_index(op.f("ix_scan_jobs_organization_id"), table_name="scan_jobs")
    op.drop_table("scan_jobs")
    op.drop_index(op.f("ix_report_exports_organization_id"), table_name="report_exports")
    op.drop_table("report_exports")
    op.drop_index(op.f("ix_product_batches_organization_id"), table_name="product_batches")
    op.drop_table("product_batches")
    op.drop_index(op.f("ix_organization_members_user_id"), table_name="organization_members")
    op.drop_table("organization_members")
    op.drop_table("marketplace_connections")
    op.drop_index(
        "uq_invitations_org_email_pending",
        table_name="invitations",
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )
    op.drop_table("invitations")
    op.drop_index(op.f("ix_extension_tokens_user_id"), table_name="extension_tokens")
    op.drop_table("extension_tokens")
    op.drop_index(op.f("ix_audit_logs_organization_id"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("alert_rules")
    op.drop_table("organizations")
    op.drop_table("users")
    op.drop_table("plans")
    op.drop_table("marketplaces")
