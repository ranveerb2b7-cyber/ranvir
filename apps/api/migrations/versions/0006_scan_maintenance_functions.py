"""Cross-tenant maintenance functions for the scheduler and stale-work reaper.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-12

Background maintenance must look across all organizations, which RLS forbids for the app role.
These SECURITY DEFINER functions are the only cross-tenant paths. Each does one narrow thing
and returns only (organization_id, id) pairs; workers then act on each pair inside that
organization's tenant context, under RLS as usual.
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_role() -> str:
    role = context.config.attributes.get("app_db_role")
    if not role:
        from sellerscope.core.config import get_settings

        role = get_settings().app_db_role
    if not str(role).replace("_", "").isalnum():
        raise ValueError(f"Invalid app role name: {role!r}")
    return str(role)


# Monitored products whose next scheduled scan is due. A product is due when its interval
# (product setting, never shorter than the plan minimum) has passed since its last scan
# ATTEMPT, so products whose scans keep failing are not retried every few minutes.
DUE = """
CREATE FUNCTION due_scan_products(p_limit integer)
RETURNS TABLE (organization_id uuid, product_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT p.organization_id, p.id
  FROM products p
  JOIN organizations o ON o.id = p.organization_id AND o.deleted_at IS NULL
  JOIN subscriptions s ON s.organization_id = p.organization_id
       AND s.status IN ('trialing', 'active', 'past_due')
  JOIN plans pl ON pl.id = s.plan_id
  WHERE p.deleted_at IS NULL
    AND p.monitoring_enabled
    AND NOT EXISTS (
      SELECT 1 FROM scan_job_items i
      WHERE i.product_id = p.id
        AND (i.status IN ('pending', 'processing')
             OR i.created_at > now() - make_interval(
                  mins => GREATEST(COALESCE(p.scan_frequency_minutes, 0),
                                   pl.min_scan_interval_minutes))))
  ORDER BY p.last_scanned_at NULLS FIRST, p.id
  LIMIT p_limit
$$
"""

# Items a crashed/killed worker left in "processing" go back to "pending"; jobs with due
# pending items that nobody is working on (lost queue message) are reported for re-dispatch.
RESET_STALE = """
CREATE FUNCTION reset_stale_scan_items(p_stale_after_s integer)
RETURNS TABLE (organization_id uuid, scan_job_id uuid)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  WITH reset AS (
    UPDATE scan_job_items
       SET status = 'pending', next_attempt_at = now(),
           attempt_count = GREATEST(attempt_count - 1, 0),
           last_error_code = 'worker_lost',
           last_error_message = 'The worker processing this product stopped; retried.'
     WHERE status = 'processing'
       AND started_at < now() - make_interval(secs => p_stale_after_s)
    RETURNING organization_id, scan_job_id
  )
  SELECT organization_id, scan_job_id FROM reset
  UNION
  SELECT i.organization_id, i.scan_job_id FROM scan_job_items i
  WHERE i.status = 'pending'
    AND COALESCE(i.next_attempt_at, i.created_at) < now() - make_interval(secs => p_stale_after_s)
$$
"""

# Uploads stuck before preview (lost queue message, or worker died while parsing).
STALE_UPLOADS = """
CREATE FUNCTION reset_stale_uploads(p_stale_after_s integer)
RETURNS TABLE (organization_id uuid, batch_id uuid)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  WITH reset AS (
    UPDATE product_batches SET status = 'uploaded'
     WHERE status = 'parsing'
       AND updated_at < now() - make_interval(secs => p_stale_after_s)
    RETURNING organization_id, id
  )
  SELECT organization_id, id FROM reset
  UNION
  SELECT b.organization_id, b.id FROM product_batches b
  WHERE b.status = 'uploaded'
    AND b.updated_at < now() - make_interval(secs => p_stale_after_s)
$$
"""

FUNCTIONS = (
    ("due_scan_products(integer)", DUE),
    ("reset_stale_scan_items(integer)", RESET_STALE),
    ("reset_stale_uploads(integer)", STALE_UPLOADS),
)


def upgrade() -> None:
    role = _app_role()
    for signature, body in FUNCTIONS:
        op.execute(body)
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {role}")


def downgrade() -> None:
    for signature, _ in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")
