"""Organizations and team members."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select

from sellerscope.auth.deps import (
    OrgContext,
    OrgDep,
    PrincipalDep,
    SessionDep,
    rate_limit,
    require,
)
from sellerscope.auth.permissions import Permission, permissions_for
from sellerscope.core.errors import AppError, forbidden, not_found
from sellerscope.models import Organization, OrganizationMember, User
from sellerscope.models.enums import MemberRole, MemberStatus
from sellerscope.schemas.accounts import (
    MemberOut,
    MemberUpdate,
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
    TransferOwnership,
)
from sellerscope.services import audit
from sellerscope.services.organizations import create_organization

router = APIRouter(tags=["organizations"])

ManageMembers = Annotated[OrgContext, Depends(require(Permission.MEMBERS_MANAGE))]


def _org_out(org: Organization, role: str) -> OrganizationOut:
    return OrganizationOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        role=role,
        permissions=permissions_for(role),
        created_at=org.created_at,
    )


@router.post(
    "/organizations",
    response_model=OrganizationOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("org-create", limit=10, window_s=3600))],
)
async def create_org(
    body: OrganizationCreate, request: Request, session: SessionDep, principal: PrincipalDep
) -> OrganizationOut:
    """Create an organization. The caller becomes its owner; a trial subscription starts."""
    org = await create_organization(session, principal, body.name, request)
    await session.refresh(org)
    out = _org_out(org, MemberRole.OWNER)
    await session.commit()
    return out


async def _current_org(session: SessionDep, ctx: OrgContext) -> Organization:
    org = await session.get(Organization, ctx.organization_id)
    if org is None:
        raise not_found("Organization")
    return org


@router.get("/organizations/current", response_model=OrganizationOut)
async def get_current_org(session: SessionDep, ctx: OrgDep) -> OrganizationOut:
    return _org_out(await _current_org(session, ctx), ctx.role)


@router.patch("/organizations/current", response_model=OrganizationOut)
async def update_current_org(
    body: OrganizationUpdate,
    request: Request,
    session: SessionDep,
    ctx: Annotated[OrgContext, Depends(require(Permission.ORG_MANAGE))],
) -> OrganizationOut:
    org = await _current_org(session, ctx)
    old = org.name
    org.name = body.name
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="organization.update",
        entity_type="organization",
        entity_id=org.id,
        request=request,
        details={"old_name": old, "new_name": body.name},
    )
    await session.flush()
    await session.refresh(org)
    out = _org_out(org, ctx.role)
    await session.commit()
    return out


@router.delete("/organizations/current", status_code=status.HTTP_204_NO_CONTENT)
async def delete_current_org(
    request: Request,
    session: SessionDep,
    ctx: Annotated[OrgContext, Depends(require(Permission.ORG_DELETE))],
) -> Response:
    """Soft-delete. Data is retained for a grace period before purge (see retention policy)."""
    org = await _current_org(session, ctx)
    org.deleted_at = datetime.now(UTC)
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="organization.delete",
        entity_type="organization",
        entity_id=org.id,
        request=request,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------------------ members


async def _member(session: SessionDep, ctx: OrgContext, user_id: uuid.UUID) -> OrganizationMember:
    member = (
        await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == ctx.organization_id,
                OrganizationMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise not_found("Member")
    return member


async def _member_out(session: SessionDep, member: OrganizationMember) -> MemberOut:
    user = await session.get(User, member.user_id)
    assert user is not None
    return MemberOut(
        user_id=member.user_id,
        email=user.email,
        full_name=user.full_name,
        role=member.role,
        status=member.status,
        joined_at=member.created_at,
    )


@router.get("/members", response_model=list[MemberOut])
async def list_members(session: SessionDep, ctx: OrgDep) -> list[MemberOut]:
    rows = (
        await session.execute(
            select(OrganizationMember, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == ctx.organization_id)
            .order_by(OrganizationMember.created_at)
        )
    ).all()
    return [
        MemberOut(
            user_id=m.user_id,
            email=u.email,
            full_name=u.full_name,
            role=m.role,
            status=m.status,
            joined_at=m.created_at,
        )
        for m, u in rows
    ]


@router.delete("/members/me", status_code=status.HTTP_204_NO_CONTENT)
async def leave_org(request: Request, session: SessionDep, ctx: OrgDep) -> Response:
    """Leave the organization. Owners must transfer ownership first."""
    if ctx.role == MemberRole.OWNER:
        raise forbidden("Owners must transfer ownership before leaving")
    member = await _member(session, ctx, ctx.user_id)
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="member.leave",
        entity_type="user",
        entity_id=ctx.user_id,
        request=request,
    )
    await session.delete(member)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _guard_target(ctx: OrgContext, target: OrganizationMember) -> None:
    if target.user_id == ctx.user_id:
        raise forbidden("You cannot change your own membership")
    if target.role == MemberRole.OWNER:
        raise forbidden("The owner can only change through ownership transfer")


@router.patch("/members/{user_id}", response_model=MemberOut)
async def update_member(
    user_id: uuid.UUID,
    body: MemberUpdate,
    request: Request,
    session: SessionDep,
    ctx: ManageMembers,
) -> MemberOut:
    target = await _member(session, ctx, user_id)
    _guard_target(ctx, target)
    changes: dict[str, str] = {}
    if body.role is not None and body.role != target.role:
        changes["role"] = f"{target.role}->{body.role}"
        target.role = body.role
    if body.status is not None and body.status != target.status:
        changes["status"] = f"{target.status}->{body.status}"
        target.status = body.status
    if changes:
        audit.record(
            session,
            organization_id=ctx.organization_id,
            actor_user_id=ctx.user_id,
            action="member.update",
            entity_type="user",
            entity_id=user_id,
            request=request,
            details=changes,
        )
    await session.flush()
    await session.refresh(target)
    out = await _member_out(session, target)
    await session.commit()
    return out


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    user_id: uuid.UUID, request: Request, session: SessionDep, ctx: ManageMembers
) -> Response:
    target = await _member(session, ctx, user_id)
    _guard_target(ctx, target)
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="member.remove",
        entity_type="user",
        entity_id=user_id,
        request=request,
        details={"role": target.role},
    )
    await session.delete(target)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/organizations/current/transfer-ownership", response_model=list[MemberOut])
async def transfer_ownership(
    body: TransferOwnership, request: Request, session: SessionDep, ctx: OrgDep
) -> list[MemberOut]:
    """The owner hands ownership to another active member and becomes an admin."""
    if ctx.role != MemberRole.OWNER:
        raise forbidden("Only the owner can transfer ownership")
    if body.user_id == ctx.user_id:
        raise AppError(400, "invalid_target", "Bad request", "You already own this organization")
    target = await _member(session, ctx, body.user_id)
    if target.status != MemberStatus.ACTIVE:
        raise AppError(400, "invalid_target", "Bad request", "The new owner must be active")
    me = await _member(session, ctx, ctx.user_id)
    target.role = MemberRole.OWNER
    me.role = MemberRole.ADMIN
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="organization.transfer_ownership",
        entity_type="user",
        entity_id=body.user_id,
        request=request,
    )
    await session.flush()
    out = [await _member_out(session, me), await _member_out(session, target)]
    await session.commit()
    return out
