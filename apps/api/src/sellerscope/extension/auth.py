"""Browser extension credentials: one-time pairing codes (PKCE-bound) and opaque tokens.

- Pairing codes: 8 characters from an unambiguous alphabet, stored as SHA-256, valid for
  `extension_pairing_ttl_s`, usable once, and only together with the extension's PKCE
  verifier (S256). Seeing the code on screen is not enough to redeem it.
- Tokens: "sse_" + 256 random bits, stored as SHA-256 only, scoped, expiring, revocable.
  Every request re-checks that the member is still active in the organization.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from sellerscope.auth.deps import SessionDep
from sellerscope.auth.permissions import Permission, has_permission
from sellerscope.core.errors import AppError
from sellerscope.db.tenant import set_tenant_context
from sellerscope.models import Organization, OrganizationMember, User
from sellerscope.models.enums import MemberStatus

TOKEN_PREFIX = "sse_"  # noqa: S105  # public prefix, not a secret
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
CODE_LENGTH = 8
SCOPE_READ = "extension:read"
SCOPE_CHECK = "extension:check"
SCOPES = (SCOPE_READ, SCOPE_CHECK)
PKCE_RE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")


def sha256(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def new_pairing_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_code(code: str) -> str:
    """Accepts any case, spaces and dashes: 'abcd efgh' -> 'ABCD-EFGH'."""
    raw = re.sub(r"[\s-]", "", code).upper()
    return f"{raw[:4]}-{raw[4:]}" if len(raw) == CODE_LENGTH else raw


def s256_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def invalid_token(detail: str = "Reconnect the extension to SellerScope.") -> AppError:
    return AppError(
        401,
        "extension_token_invalid",
        "Extension not connected",
        detail,
        headers={"WWW-Authenticate": 'Bearer realm="sellerscope-extension"'},
    )


@dataclass(frozen=True, slots=True)
class ExtensionContext:
    organization_id: uuid.UUID
    organization_name: str
    user_id: uuid.UUID
    email: str
    role: str
    token_id: uuid.UUID
    scopes: tuple[str, ...]

    def can(self, permission: Permission) -> bool:
        return has_permission(self.role, permission)


async def member_role(
    session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[str, str, str] | None:
    """(role, email, organization name) for an ACTIVE member of a live organization."""
    row = (
        await session.execute(
            select(OrganizationMember.role, User.email, Organization.name)
            .join(Organization, Organization.id == OrganizationMember.organization_id)
            .join(User, User.id == OrganizationMember.user_id)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
                OrganizationMember.status == MemberStatus.ACTIVE,
                Organization.deleted_at.is_(None),
                User.is_active.is_(True),
            )
        )
    ).one_or_none()
    return (row[0], row[1], row[2]) if row else None


async def get_extension_context(
    request: Request,
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> ExtensionContext:
    scheme, _, token = (authorization or "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token.startswith(TOKEN_PREFIX):
        raise invalid_token("Missing extension token.")
    row = (
        await session.execute(
            text("SELECT * FROM extension_token_principal(:h)"), {"h": sha256(token)}
        )
    ).one_or_none()
    # Persist last_used_at now: read-only routes never commit their own transaction.
    await session.commit()
    if row is None:
        raise invalid_token("This connection was revoked or has expired.")
    org, token_id, user_id, scopes = row
    await set_tenant_context(session, organization_id=org, user_id=user_id)
    member = await member_role(session, org, user_id)
    if member is None:
        raise invalid_token("You are no longer a member of this organization.")
    role, email, org_name = member
    return ExtensionContext(org, org_name, user_id, email, role, token_id, tuple(scopes))


ExtensionDep = Annotated[ExtensionContext, Depends(get_extension_context)]
