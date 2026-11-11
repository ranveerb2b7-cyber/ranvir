"""Request dependencies: DB session, authenticated principal, organization context, RBAC.

Transaction model: each request gets one AsyncSession. Tenant context is transaction-local,
so routes must perform all tenant queries before `await session.commit()`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sellerscope.auth.permissions import Permission, has_permission
from sellerscope.auth.tokens import TokenVerifier, unauthorized
from sellerscope.core.errors import AppError, forbidden
from sellerscope.core.rate_limit import RateLimiter
from sellerscope.db.tenant import set_tenant_context
from sellerscope.models import Organization, OrganizationMember, User
from sellerscope.models.enums import MemberStatus


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    email: str


@dataclass(frozen=True, slots=True)
class OrgContext:
    organization_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    role: str

    def can(self, permission: Permission) -> bool:
        return has_permission(self.role, permission)


def _bearer(authorization: str | None) -> str:
    if not authorization:
        raise unauthorized("Missing bearer token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthorized("Missing bearer token")
    return token.strip()


async def get_principal(
    request: Request,
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    verifier: TokenVerifier = request.app.state.token_verifier
    claims = await verifier.verify(_bearer(authorization))

    await set_tenant_context(session, organization_id=None, user_id=claims.user_id)
    user = await session.get(User, claims.user_id)
    if user is None or user.email != claims.email:
        # First login (or email changed at the identity provider): sync the local mirror.
        if user is None:
            session.add(User(id=claims.user_id, email=claims.email))
        else:
            user.email = claims.email
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise AppError(
                409, "email_in_use", "Conflict", "This email belongs to another account"
            ) from exc
        await set_tenant_context(session, organization_id=None, user_id=claims.user_id)
        user = await session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise forbidden("This account is deactivated")
    return Principal(user_id=claims.user_id, email=claims.email)


PrincipalDep = Annotated[Principal, Depends(get_principal)]


async def get_org_context(
    principal: PrincipalDep,
    session: SessionDep,
    x_organization_id: Annotated[uuid.UUID | None, Header(alias="X-Organization-Id")] = None,
) -> OrgContext:
    if x_organization_id is None:
        raise AppError(
            400, "organization_required", "Organization required", "Send X-Organization-Id"
        )
    await set_tenant_context(session, organization_id=x_organization_id, user_id=principal.user_id)
    role = (
        await session.execute(
            select(OrganizationMember.role)
            .join(Organization, Organization.id == OrganizationMember.organization_id)
            .where(
                OrganizationMember.organization_id == x_organization_id,
                OrganizationMember.user_id == principal.user_id,
                OrganizationMember.status == MemberStatus.ACTIVE,
                Organization.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if role is None:
        # 404 rather than 403: do not reveal whether the organization exists.
        raise AppError(404, "organization_not_found", "Organization not found")
    return OrgContext(
        organization_id=x_organization_id,
        user_id=principal.user_id,
        email=principal.email,
        role=role,
    )


OrgDep = Annotated[OrgContext, Depends(get_org_context)]


def require(permission: Permission) -> Callable[[OrgContext], Awaitable[OrgContext]]:
    async def _check(ctx: OrgDep) -> OrgContext:
        if not ctx.can(permission):
            raise forbidden(f"Your role ({ctx.role}) does not allow {permission}")
        return ctx

    return _check


def rate_limit(
    name: str, limit: int, window_s: int
) -> Callable[[Request, Principal], Awaitable[None]]:
    """Route dependency keyed on the verified user id (stable across token refreshes)."""

    async def _dep(request: Request, principal: PrincipalDep) -> None:
        limiter: RateLimiter = request.app.state.rate_limiter
        await limiter.check(f"{name}:user:{principal.user_id}", limit, window_s)

    return _dep
