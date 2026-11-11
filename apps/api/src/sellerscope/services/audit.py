"""Append-only audit trail of security-relevant actions."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from sellerscope.models import AuditLog
from sellerscope.models.enums import ActorType


def record(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    action: str,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    request: Request | None = None,
    actor_type: ActorType = ActorType.USER,
    details: dict[str, Any] | None = None,
) -> None:
    """Adds an audit row to the session; it is committed with the action it describes."""
    session.add(
        AuditLog(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            ip=request.client.host if request and request.client else None,
            user_agent=(request.headers.get("user-agent", "")[:500] or None) if request else None,
            details={
                k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in (details or {}).items()
            },
        )
    )
