"""Invitation acceptance functions (cross-tenant by necessity, narrowly scoped).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-11

An invitee is not yet a member, so RLS hides the invitation from them. These SECURITY DEFINER
functions run as the schema owner but only ever act on the single invitation whose token hash
the caller presents, and only for the signed-in user (app.current_user_id) whose email matches.
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "0004"
down_revision: str | None = "0003"
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


PREVIEW = """
CREATE FUNCTION invitation_preview(p_token_hash bytea)
RETURNS TABLE (organization_name text, email text, role text, status text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT o.name, i.email::text, i.role,
         CASE WHEN i.accepted_at IS NOT NULL THEN 'accepted'
              WHEN i.revoked_at IS NOT NULL THEN 'revoked'
              WHEN i.expires_at <= now() THEN 'expired'
              ELSE 'pending' END
  FROM invitations i
  JOIN organizations o ON o.id = i.organization_id
  WHERE i.token_hash = p_token_hash
    AND o.deleted_at IS NULL
    AND app_current_user() IS NOT NULL
$$
"""

ACCEPT = """
CREATE FUNCTION accept_invitation(p_token_hash bytea)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_user uuid := app_current_user();
  v_email citext;
  v_inv invitations%ROWTYPE;
BEGIN
  IF v_user IS NULL THEN
    RAISE EXCEPTION 'invitation_not_found';
  END IF;
  SELECT email INTO v_email FROM users WHERE id = v_user AND is_active;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'invitation_not_found';
  END IF;

  SELECT i.* INTO v_inv FROM invitations i
    JOIN organizations o ON o.id = i.organization_id AND o.deleted_at IS NULL
   WHERE i.token_hash = p_token_hash
   FOR UPDATE OF i;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'invitation_not_found';
  ELSIF v_inv.accepted_at IS NOT NULL THEN
    RAISE EXCEPTION 'invitation_already_used';
  ELSIF v_inv.revoked_at IS NOT NULL THEN
    RAISE EXCEPTION 'invitation_revoked';
  ELSIF v_inv.expires_at <= now() THEN
    RAISE EXCEPTION 'invitation_expired';
  ELSIF v_inv.email <> v_email THEN
    RAISE EXCEPTION 'invitation_email_mismatch';
  ELSIF v_inv.role = 'owner' THEN
    RAISE EXCEPTION 'invitation_not_found';
  END IF;

  IF EXISTS (SELECT 1 FROM organization_members
              WHERE organization_id = v_inv.organization_id AND user_id = v_user) THEN
    RAISE EXCEPTION 'already_member';
  END IF;

  INSERT INTO organization_members (id, organization_id, user_id, role, status)
  VALUES (gen_random_uuid(), v_inv.organization_id, v_user, v_inv.role, 'active');
  UPDATE invitations SET accepted_at = now() WHERE id = v_inv.id;
  RETURN v_inv.organization_id;
END
$$
"""


def upgrade() -> None:
    role = _app_role()
    op.drop_constraint(op.f("ck_invitations_role_valid"), "invitations", type_="check")
    op.create_check_constraint(
        op.f("ck_invitations_role_valid"), "invitations", "role IN ('admin', 'analyst', 'viewer')"
    )
    op.execute(PREVIEW)
    op.execute(ACCEPT)
    for fn in ("invitation_preview(bytea)", "accept_invitation(bytea)"):
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO {role}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS accept_invitation(bytea)")
    op.execute("DROP FUNCTION IF EXISTS invitation_preview(bytea)")
    op.drop_constraint(op.f("ck_invitations_role_valid"), "invitations", type_="check")
    op.create_check_constraint(
        op.f("ck_invitations_role_valid"),
        "invitations",
        "role IN ('owner', 'admin', 'analyst', 'viewer')",
    )
