"""The signed-in user and their organization memberships."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from sellerscope.auth.deps import PrincipalDep, SessionDep
from sellerscope.models import Organization, OrganizationMember, User
from sellerscope.models.enums import MemberStatus
from sellerscope.schemas.accounts import MembershipOut, MeOut, MeUpdate

router = APIRouter(prefix="/me", tags=["account"])


async def _me(session: SessionDep, principal: PrincipalDep) -> MeOut:
    user = await session.get(User, principal.user_id)
    assert user is not None
    rows = (
        await session.execute(
            select(Organization.id, Organization.name, Organization.slug, OrganizationMember.role)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(
                OrganizationMember.user_id == principal.user_id,
                OrganizationMember.status == MemberStatus.ACTIVE,
                Organization.deleted_at.is_(None),
            )
            .order_by(Organization.name)
        )
    ).all()
    return MeOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        memberships=[
            MembershipOut(
                organization_id=r.id,
                organization_name=r.name,
                organization_slug=r.slug,
                role=r.role,
            )
            for r in rows
        ],
    )


@router.get("", response_model=MeOut)
async def get_me(session: SessionDep, principal: PrincipalDep) -> MeOut:
    """Current user and the organizations they belong to (for the org switcher)."""
    return await _me(session, principal)


@router.patch("", response_model=MeOut)
async def update_me(body: MeUpdate, session: SessionDep, principal: PrincipalDep) -> MeOut:
    user = await session.get(User, principal.user_id)
    assert user is not None
    if "full_name" in body.model_fields_set:
        user.full_name = body.full_name
    await session.flush()
    out = await _me(session, principal)
    await session.commit()
    return out
