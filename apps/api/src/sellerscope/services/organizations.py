"""Organization lifecycle."""

from __future__ import annotations

import re
import secrets

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sellerscope.auth.deps import Principal
from sellerscope.core.errors import AppError
from sellerscope.core.ids import uuid7
from sellerscope.db.tenant import set_tenant_context
from sellerscope.models import Organization, OrganizationMember, Plan, Subscription
from sellerscope.models.enums import MemberRole, MemberStatus, SubscriptionStatus
from sellerscope.services import audit

TRIAL_PLAN_CODE = "trial"


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "org"
    return f"{base}-{secrets.token_hex(3)}"


async def create_organization(
    session: AsyncSession, principal: Principal, name: str, request: Request | None = None
) -> Organization:
    """Creates the org, makes the caller its owner and starts a trial subscription.

    RLS only allows inserting an organization whose id is the current tenant context, so the
    context is switched to the new id before inserting.
    """
    org_id = uuid7()
    await set_tenant_context(session, organization_id=org_id, user_id=principal.user_id)

    plan_id = (
        await session.execute(
            select(Plan.id).where(Plan.code == TRIAL_PLAN_CODE, Plan.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if plan_id is None:
        raise AppError(500, "plan_missing", "Trial plan is not configured")

    org = Organization(id=org_id, name=name, slug=slugify(name), created_by=principal.user_id)
    session.add(org)
    await session.flush()
    session.add(
        OrganizationMember(
            organization_id=org_id,
            user_id=principal.user_id,
            role=MemberRole.OWNER,
            status=MemberStatus.ACTIVE,
        )
    )
    session.add(
        Subscription(organization_id=org_id, plan_id=plan_id, status=SubscriptionStatus.TRIALING)
    )
    audit.record(
        session,
        organization_id=org_id,
        actor_user_id=principal.user_id,
        action="organization.create",
        entity_type="organization",
        entity_id=org_id,
        request=request,
        details={"name": name},
    )
    await session.flush()
    return org
