"""ops metrics function

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-12

One SECURITY DEFINER function for monitoring. It returns platform-wide COUNTS ONLY (no ids,
no names, nothing per organization) so /metrics can report backlogs and failures across all
tenants without giving the app role cross-tenant read access.
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPS_METRICS = """
CREATE FUNCTION ops_metrics()
RETURNS TABLE (
  scan_items_pending bigint,
  scan_items_processing bigint,
  oldest_pending_scan_item_s double precision,
  scan_results_last_hour bigint,
  scan_errors_last_hour bigint,
  alert_deliveries_pending bigint,
  alert_deliveries_failed bigint,
  reports_active bigint,
  reports_failed_last_day bigint
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT
    (SELECT count(*) FROM scan_job_items WHERE status = 'pending'),
    (SELECT count(*) FROM scan_job_items WHERE status = 'processing'),
    (SELECT COALESCE(EXTRACT(EPOCH FROM now() - min(COALESCE(next_attempt_at, created_at))), 0)
       FROM scan_job_items
      WHERE status = 'pending' AND COALESCE(next_attempt_at, created_at) <= now()),
    (SELECT count(*) FROM scan_results WHERE retrieved_at > now() - interval '1 hour'),
    (SELECT count(*) FROM scan_results
      WHERE status = 'error' AND retrieved_at > now() - interval '1 hour'),
    (SELECT count(*) FROM alert_deliveries WHERE status IN ('pending', 'sending')),
    (SELECT count(*) FROM alert_deliveries WHERE status = 'failed'),
    (SELECT count(*) FROM report_exports WHERE status IN ('queued', 'running')),
    (SELECT count(*) FROM report_exports
      WHERE status = 'failed' AND updated_at > now() - interval '1 day')
$$
"""


def _app_role() -> str:
    role = context.config.attributes.get("app_db_role")
    if not role:
        from sellerscope.core.config import get_settings

        role = get_settings().app_db_role
    if not str(role).replace("_", "").isalnum():
        raise ValueError(f"Invalid app role name: {role!r}")
    return str(role)


def upgrade() -> None:
    role = _app_role()
    op.execute(OPS_METRICS)
    op.execute("REVOKE ALL ON FUNCTION ops_metrics() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION ops_metrics() TO {role}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS ops_metrics()")
