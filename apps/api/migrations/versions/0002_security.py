"""Security layer: app role grants, row-level security, append-only and updated_at triggers.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-11

The API connects as a restricted role (settings.app_db_role, default ``sellerscope_app``)
that must already exist (created by infra/docker/postgres init or by ops). It gets no DDL
rights and no BYPASSRLS. Tables are owned by the migration role, so RLS applies to the app
role but not to migrations.
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables with an organization_id column (standard tenant isolation policy).
TENANT_TABLES = (
    "organization_members",
    "invitations",
    "subscriptions",
    "marketplace_connections",
    "product_batches",
    "product_batch_rows",
    "products",
    "scan_jobs",
    "scan_job_items",
    "scan_results",
    "seller_profiles",
    "product_offers",
    "scan_history",
    "alert_rules",
    "alerts",
    "report_exports",
    "extension_tokens",
    "audit_logs",
)
APPEND_ONLY_TABLES = ("scan_results", "product_offers", "scan_history", "audit_logs")
REFERENCE_TABLES = ("marketplaces", "plans")  # global, read-only for the app
# Tables with updated_at maintained by trigger.
UPDATED_AT_TABLES = (
    "users",
    "organizations",
    "plans",
    "marketplaces",
    *(t for t in TENANT_TABLES if t not in APPEND_ONLY_TABLES),
)


def _app_role() -> str:
    role = context.config.attributes.get("app_db_role")
    if not role:
        from sellerscope.core.config import get_settings

        role = get_settings().app_db_role
    if not str(role).replace("_", "").isalnum():
        raise ValueError(f"Invalid app role name: {role!r}")
    return str(role)


def _exec(*statements: str) -> None:
    """asyncpg runs one statement per call."""
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    role = _app_role()
    # role is validated as an identifier by _app_role(), so interpolation is safe.
    check_role = (
        "DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN "
        f'RAISE EXCEPTION \'Database role "{role}" does not exist. Create it before '
        "migrating (see infra/docker/postgres/init).'; "
        "END IF; END $$;"
    )
    op.execute(check_role)

    # ---- tenant context helpers (read transaction-local settings) ----
    _exec(
        "CREATE FUNCTION app_current_org() RETURNS uuid LANGUAGE sql STABLE AS "
        "$$ SELECT NULLIF(current_setting('app.current_org_id', true), '')::uuid $$",
        "CREATE FUNCTION app_current_user() RETURNS uuid LANGUAGE sql STABLE AS "
        "$$ SELECT NULLIF(current_setting('app.current_user_id', true), '')::uuid $$",
    )

    # ---- updated_at ----
    op.execute("""
        CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS
        $$ BEGIN NEW.updated_at := now(); RETURN NEW; END $$;
    """)
    for table in UPDATED_AT_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )

    # ---- append-only snapshots ----
    # UPDATE is never allowed. DELETE only for an explicit owner-run retention purge
    # (SET LOCAL app.retention_purge = 'on'); the app role has no DELETE grant anyway.
    op.execute("""
        CREATE FUNCTION forbid_snapshot_modification() RETURNS trigger LANGUAGE plpgsql AS
        $$ BEGIN
          IF TG_OP = 'DELETE' AND current_setting('app.retention_purge', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION '% on %.% is not allowed: snapshots are append-only',
            TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
        END $$;
    """)
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_snapshot_modification()"
        )

    # ---- grants ----
    op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
    for table in REFERENCE_TABLES:
        op.execute(f"GRANT SELECT ON {table} TO {role}")
    for table in APPEND_ONLY_TABLES:
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {role}")
    for table in ("users", "organizations", *TENANT_TABLES):
        if table not in APPEND_ONLY_TABLES:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {role}")

    # ---- row-level security ----
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        if table == "organization_members":
            continue
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (organization_id = app_current_org()) "
            "WITH CHECK (organization_id = app_current_org())"
        )

    # A user may see their own memberships in any org (to list/switch orgs),
    # but may only modify memberships of the current org.
    _exec(
        "CREATE POLICY member_select ON organization_members FOR SELECT "
        "USING (organization_id = app_current_org() OR user_id = app_current_user())",
        "CREATE POLICY member_modify ON organization_members FOR ALL "
        "USING (organization_id = app_current_org()) "
        "WITH CHECK (organization_id = app_current_org())",
    )

    # Organizations: the current one, plus any the user is a member of (org switcher).
    _exec(
        "ALTER TABLE organizations ENABLE ROW LEVEL SECURITY",
        "CREATE POLICY org_select ON organizations FOR SELECT "
        "USING (id = app_current_org() OR id IN ("
        "SELECT organization_id FROM organization_members WHERE user_id = app_current_user()))",
        "CREATE POLICY org_modify ON organizations FOR ALL "
        "USING (id = app_current_org()) WITH CHECK (id = app_current_org())",
    )

    # Users: yourself, plus members of the current org (for team listings).
    _exec(
        "ALTER TABLE users ENABLE ROW LEVEL SECURITY",
        "CREATE POLICY user_select ON users FOR SELECT "
        "USING (id = app_current_user() OR id IN ("
        "SELECT user_id FROM organization_members WHERE organization_id = app_current_org()))",
        "CREATE POLICY user_modify ON users FOR ALL "
        "USING (id = app_current_user()) WITH CHECK (id = app_current_user())",
    )


def downgrade() -> None:
    role = _app_role()
    _exec(
        "DROP POLICY IF EXISTS user_select ON users",
        "DROP POLICY IF EXISTS user_modify ON users",
        "ALTER TABLE users DISABLE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS org_select ON organizations",
        "DROP POLICY IF EXISTS org_modify ON organizations",
        "ALTER TABLE organizations DISABLE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS member_select ON organization_members",
        "DROP POLICY IF EXISTS member_modify ON organization_members",
    )
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    for table in ("users", "organizations", *TENANT_TABLES, *REFERENCE_TABLES):
        op.execute(f"REVOKE ALL ON {table} FROM {role}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {role}")
    for table in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS forbid_snapshot_modification()")
    for table in UPDATED_AT_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")
    _exec(
        "DROP FUNCTION IF EXISTS set_updated_at()",
        "DROP FUNCTION IF EXISTS app_current_user()",
        "DROP FUNCTION IF EXISTS app_current_org()",
    )
