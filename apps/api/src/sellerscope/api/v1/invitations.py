"""Team invitations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select, text

from sellerscope.auth.deps import (
    OrgContext,
    OrgDep,
    PrincipalDep,
    SessionDep,
    rate_limit,
    require,
)
from sellerscope.auth.permissions import Permission
from sellerscope.core.config import Settings
from sellerscope.core.errors import conflict, not_found
from sellerscope.core.ids import uuid7
from sellerscope.db.tenant import set_tenant_context
from sellerscope.models import Invitation, Organization, OrganizationMember, User
from sellerscope.schemas.accounts import (
    InvitationAccepted,
    InvitationCreate,
    InvitationOut,
    InvitationPreview,
    InvitationSent,
    InvitationToken,
)
from sellerscope.services import audit, invitations
from sellerscope.services.mailer import Mailer

log = structlog.get_logger()
router = APIRouter(prefix="/invitations", tags=["invitations"])

ManageMembers = Annotated[OrgContext, Depends(require(Permission.MEMBERS_MANAGE))]


def _out(inv: Invitation) -> InvitationOut:
    return InvitationOut.model_validate(inv)


async def _send(request: Request, inv: Invitation, token: str, org_name: str, inviter: str) -> bool:
    settings: Settings = request.app.state.settings
    mailer: Mailer = request.app.state.mailer
    message = invitations.invitation_email(
        settings, to=inv.email, org_name=org_name, inviter=inviter, token=token
    )
    try:
        await mailer.send(message)
    except Exception:
        log.exception("invitation_email_failed", invitation_id=str(inv.id))
        return False
    return True


@router.get("", response_model=list[InvitationOut])
async def list_pending(session: SessionDep, ctx: OrgDep) -> list[InvitationOut]:
    rows = (
        await session.execute(
            select(Invitation)
            .where(
                Invitation.organization_id == ctx.organization_id,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
            )
            .order_by(Invitation.created_at.desc())
        )
    ).scalars()
    return [_out(i) for i in rows]


@router.post(
    "",
    response_model=InvitationSent,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("invite-create", limit=30, window_s=3600))],
)
async def create_invitation(
    body: InvitationCreate, request: Request, session: SessionDep, ctx: ManageMembers
) -> InvitationSent:
    email = body.email.lower()
    already_member = (
        await session.execute(
            select(OrganizationMember.id)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == ctx.organization_id, User.email == email)
        )
    ).scalar_one_or_none()
    if already_member:
        raise conflict("already_member", "This person is already a member")
    pending = (
        await session.execute(
            select(Invitation.id).where(
                Invitation.organization_id == ctx.organization_id,
                Invitation.email == email,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if pending:
        raise conflict("invitation_pending", "An invitation is already pending; resend it instead")

    settings: Settings = request.app.state.settings
    token, token_hash = invitations.new_token()
    inv = Invitation(
        id=uuid7(),
        organization_id=ctx.organization_id,
        email=email,
        role=body.role,
        token_hash=token_hash,
        invited_by=ctx.user_id,
        expires_at=datetime.now(UTC) + timedelta(hours=settings.invitation_ttl_hours),
    )
    session.add(inv)
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="invitation.create",
        entity_type="invitation",
        entity_id=inv.id,
        request=request,
        details={"email": email, "role": body.role},
    )
    await session.flush()
    await session.refresh(inv)
    org = await session.get(Organization, ctx.organization_id)
    assert org is not None
    out = _out(inv)
    org_name = org.name
    await session.commit()
    # Send only after the invitation is durably stored.
    sent = await _send(request, inv, token, org_name, ctx.email)
    return InvitationSent(**out.model_dump(), email_sent=sent)


async def _pending(session: SessionDep, ctx: OrgContext, invitation_id: uuid.UUID) -> Invitation:
    inv = (
        await session.execute(
            select(Invitation).where(
                Invitation.id == invitation_id,
                Invitation.organization_id == ctx.organization_id,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if inv is None:
        raise not_found("Invitation")
    return inv


@router.post(
    "/{invitation_id}/resend",
    response_model=InvitationSent,
    dependencies=[Depends(rate_limit("invite-resend", limit=30, window_s=3600))],
)
async def resend_invitation(
    invitation_id: uuid.UUID, request: Request, session: SessionDep, ctx: ManageMembers
) -> InvitationSent:
    """Issues a fresh token (the old link stops working) and extends the expiry."""
    settings: Settings = request.app.state.settings
    inv = await _pending(session, ctx, invitation_id)
    token, inv.token_hash = invitations.new_token()
    inv.expires_at = datetime.now(UTC) + timedelta(hours=settings.invitation_ttl_hours)
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="invitation.resend",
        entity_type="invitation",
        entity_id=inv.id,
        request=request,
    )
    await session.flush()
    await session.refresh(inv)
    org = await session.get(Organization, ctx.organization_id)
    assert org is not None
    out, org_name = _out(inv), org.name
    await session.commit()
    sent = await _send(request, inv, token, org_name, ctx.email)
    return InvitationSent(**out.model_dump(), email_sent=sent)


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: uuid.UUID, request: Request, session: SessionDep, ctx: ManageMembers
) -> Response:
    inv = await _pending(session, ctx, invitation_id)
    inv.revoked_at = datetime.now(UTC)
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="invitation.revoke",
        entity_type="invitation",
        entity_id=inv.id,
        request=request,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- invitee side (no organization context: the user is not a member yet) ----


@router.post(
    "/preview",
    response_model=InvitationPreview,
    dependencies=[Depends(rate_limit("invite-accept", limit=20, window_s=60))],
)
async def preview_invitation(
    body: InvitationToken, session: SessionDep, principal: PrincipalDep
) -> InvitationPreview:
    """What the invitation is for, so the user can confirm before joining."""
    row = (
        await session.execute(
            text("SELECT * FROM invitation_preview(:h)"),
            {"h": invitations.hash_token(body.token)},
        )
    ).one_or_none()
    if row is None:
        raise not_found("Invitation")
    return InvitationPreview(
        organization_name=row.organization_name,
        email=row.email,
        role=row.role,
        status=row.status,
        email_matches=row.email.lower() == principal.email,
    )


@router.post(
    "/accept",
    response_model=InvitationAccepted,
    dependencies=[Depends(rate_limit("invite-accept", limit=20, window_s=60))],
)
async def accept_invitation(
    body: InvitationToken, request: Request, session: SessionDep, principal: PrincipalDep
) -> InvitationAccepted:
    org_id = await invitations.accept(session, body.token)
    # Now a member: record the event inside the organization's tenant context.
    await set_tenant_context(session, organization_id=org_id, user_id=principal.user_id)
    audit.record(
        session,
        organization_id=org_id,
        actor_user_id=principal.user_id,
        action="invitation.accept",
        entity_type="user",
        entity_id=principal.user_id,
        request=request,
    )
    await session.commit()
    return InvitationAccepted(organization_id=org_id)
