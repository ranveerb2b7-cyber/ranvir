"""Per-transaction tenant context consumed by PostgreSQL row-level security policies.

The RLS policies (see migrations) read two transaction-local settings:
- app.current_org_id   — the organization the request acts on
- app.current_user_id  — the authenticated user (lets a user see their own memberships)

`set_config(..., is_local => true)` scopes them to the current transaction, so they cannot
leak to another request that reuses the pooled connection.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SET = text(
    "SELECT set_config('app.current_org_id', :org, true), "
    "set_config('app.current_user_id', :user, true)"
)


async def set_tenant_context(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
) -> None:
    """Must be called inside the transaction that performs tenant queries."""
    await session.execute(
        _SET,
        {
            "org": str(organization_id) if organization_id else "",
            "user": str(user_id) if user_id else "",
        },
    )
