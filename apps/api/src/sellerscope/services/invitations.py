"""Invitation tokens, emails and acceptance.

Tokens are 256-bit random values. Only their SHA-256 is stored; the raw token exists only in
the email link. Acceptance happens before the user is a member of the organization, so it
uses SECURITY DEFINER database functions (migration 0004) that check the token, expiry and
that the invitation email matches the signed-in user's email.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from email.message import EmailMessage
from urllib.parse import quote

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from sellerscope.core.config import Settings
from sellerscope.core.errors import AppError
from sellerscope.services.mailer import build_message

_ACCEPT_ERRORS: dict[str, AppError] = {
    "invitation_not_found": AppError(404, "invitation_not_found", "Invitation not found"),
    "invitation_already_used": AppError(410, "invitation_already_used", "Invitation already used"),
    "invitation_revoked": AppError(410, "invitation_revoked", "Invitation was revoked"),
    "invitation_expired": AppError(410, "invitation_expired", "Invitation has expired"),
    "invitation_email_mismatch": AppError(
        403,
        "invitation_email_mismatch",
        "Forbidden",
        "This invitation was sent to a different email address",
    ),
    "already_member": AppError(409, "already_member", "You are already a member"),
}


def new_token() -> tuple[str, bytes]:
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def accept_url(settings: Settings, token: str) -> str:
    return f"{settings.web_base_url.rstrip('/')}/accept-invite?token={quote(token)}"


def invitation_email(
    settings: Settings, *, to: str, org_name: str, inviter: str, token: str
) -> EmailMessage:
    body = (
        f"{inviter} invited you to join {org_name} on SellerScope.\n\n"
        f"Accept the invitation:\n{accept_url(settings, token)}\n\n"
        f"The link expires in {settings.invitation_ttl_hours // 24} days. "
        "If you did not expect this email, you can ignore it."
    )
    return build_message(to, f"You're invited to {org_name} on SellerScope", body)


async def accept(session: AsyncSession, token: str) -> uuid.UUID:
    try:
        org_id = (
            await session.execute(text("SELECT accept_invitation(:h)"), {"h": hash_token(token)})
        ).scalar_one()
    except DBAPIError as exc:
        message = str(exc.orig)
        for code, error in _ACCEPT_ERRORS.items():
            if code in message:
                raise error from exc
        raise
    return uuid.UUID(str(org_id))
