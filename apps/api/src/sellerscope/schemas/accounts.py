"""Schemas for the current user, organizations, members and invitations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import EmailStr, Field, StringConstraints

from sellerscope.schemas.common import ApiModel

AssignableRole = Literal["admin", "analyst", "viewer"]
Role = Literal["owner", "admin", "analyst", "viewer"]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]


class MembershipOut(ApiModel):
    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    role: Role


class MeOut(ApiModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    memberships: list[MembershipOut]


class MeUpdate(ApiModel):
    full_name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
        | None
    ) = None


class OrganizationCreate(ApiModel):
    name: Name


class OrganizationUpdate(ApiModel):
    name: Name


class OrganizationOut(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    role: Role
    permissions: list[str]
    created_at: datetime


class MemberOut(ApiModel):
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: Role
    status: Literal["active", "suspended"]
    joined_at: datetime


class MemberUpdate(ApiModel):
    role: AssignableRole | None = None
    status: Literal["active", "suspended"] | None = None


class TransferOwnership(ApiModel):
    user_id: uuid.UUID


class InvitationCreate(ApiModel):
    email: EmailStr
    role: AssignableRole


class InvitationOut(ApiModel):
    id: uuid.UUID
    email: str
    role: AssignableRole
    expires_at: datetime
    created_at: datetime
    invited_by: uuid.UUID | None


class InvitationSent(InvitationOut):
    # False if the email could not be delivered; the invitation still exists and can be resent.
    email_sent: bool


class InvitationToken(ApiModel):
    token: Annotated[str, Field(min_length=20, max_length=200)]


class InvitationPreview(ApiModel):
    organization_name: str
    email: str
    role: AssignableRole
    status: Literal["pending", "accepted", "revoked", "expired"]
    email_matches: bool


class InvitationAccepted(ApiModel):
    organization_id: uuid.UUID
