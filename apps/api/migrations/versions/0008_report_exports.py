"""report exports

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-12

Report export bookkeeping columns, the "alerts" report type, and two SECURITY DEFINER
maintenance functions (the only cross-tenant paths for reports):
- reset_stale_reports: re-queues exports a lost worker or queue message left behind
- expire_report_exports: marks exports past their retention as expired and returns their file
  keys so the worker can delete the files
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPES = ("product", "marketplace", "brand", "seller", "scan_summary", "errors", "alerts")

RESET_STALE = """
CREATE FUNCTION reset_stale_reports(p_stale_after_s integer)
RETURNS TABLE (organization_id uuid, report_id uuid)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  WITH reset AS (
    UPDATE report_exports SET status = 'queued', started_at = NULL
     WHERE status = 'running'
       AND started_at < now() - make_interval(secs => p_stale_after_s)
    RETURNING organization_id, id
  )
  SELECT organization_id, id FROM reset
  UNION
  SELECT r.organization_id, r.id FROM report_exports r
  WHERE r.status = 'queued'
    AND r.created_at < now() - make_interval(secs => p_stale_after_s)
$$
"""

EXPIRE = """
CREATE FUNCTION expire_report_exports()
RETURNS TABLE (organization_id uuid, report_id uuid, storage_key text)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  UPDATE report_exports SET status = 'expired'
   WHERE status = 'completed' AND expires_at < now()
  RETURNING organization_id, id, storage_key
$$
"""

FUNCTIONS = (
    ("reset_stale_reports(integer)", RESET_STALE),
    ("expire_report_exports()", EXPIRE),
)


def _app_role() -> str:
    role = context.config.attributes.get("app_db_role")
    if not role:
        from sellerscope.core.config import get_settings

        role = get_settings().app_db_role
    if not str(role).replace("_", "").isalnum():
        raise ValueError(f"Invalid app role name: {role!r}")
    return str(role)


def _types_check(types: Sequence[str]) -> str:
    return f"report_type IN ({', '.join(repr(t) for t in types)})"


def upgrade() -> None:
    role = _app_role()
    op.add_column("report_exports", sa.Column("size_bytes", sa.Integer(), nullable=True))
    op.add_column("report_exports", sa.Column("contains_mock", sa.Boolean(), nullable=True))
    op.add_column(
        "report_exports", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.drop_constraint(op.f("ck_report_exports_report_type_valid"), "report_exports", type_="check")
    op.create_check_constraint(
        op.f("ck_report_exports_report_type_valid"), "report_exports", _types_check(TYPES)
    )
    for signature, body in FUNCTIONS:
        op.execute(body)
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {role}")


def downgrade() -> None:
    for signature, _ in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")
    op.drop_constraint(op.f("ck_report_exports_report_type_valid"), "report_exports", type_="check")
    op.execute("DELETE FROM report_exports WHERE report_type = 'alerts'")
    op.create_check_constraint(
        op.f("ck_report_exports_report_type_valid"), "report_exports", _types_check(TYPES[:6])
    )
    op.drop_column("report_exports", "started_at")
    op.drop_column("report_exports", "contains_mock")
    op.drop_column("report_exports", "size_bytes")
