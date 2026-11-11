"""Role-based permissions (see docs/plan/01-architecture.md §1.5)."""

from __future__ import annotations

from enum import StrEnum

from sellerscope.models.enums import MemberRole


class Permission(StrEnum):
    ORG_MANAGE = "org.manage"
    ORG_DELETE = "org.delete"
    MEMBERS_MANAGE = "members.manage"
    CONNECTIONS_MANAGE = "connections.manage"
    PRODUCTS_WRITE = "products.write"
    SCANS_RUN = "scans.run"
    ALERTS_MANAGE = "alerts.manage"
    BILLING_MANAGE = "billing.manage"


# Every active member can view data and export reports; listed here is everything beyond that.
_ANALYST = frozenset({Permission.PRODUCTS_WRITE, Permission.SCANS_RUN, Permission.ALERTS_MANAGE})
_ADMIN = _ANALYST | {
    Permission.ORG_MANAGE,
    Permission.MEMBERS_MANAGE,
    Permission.CONNECTIONS_MANAGE,
}
_OWNER = _ADMIN | {Permission.ORG_DELETE, Permission.BILLING_MANAGE}

ROLE_PERMISSIONS: dict[MemberRole, frozenset[Permission]] = {
    MemberRole.OWNER: _OWNER,
    MemberRole.ADMIN: _ADMIN,
    MemberRole.ANALYST: _ANALYST,
    MemberRole.VIEWER: frozenset(),
}

# Roles that can be granted by invitation or role change (ownership only via transfer).
ASSIGNABLE_ROLES = (MemberRole.ADMIN, MemberRole.ANALYST, MemberRole.VIEWER)


def has_permission(role: str, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(MemberRole(role), frozenset())


def permissions_for(role: str) -> list[str]:
    return sorted(ROLE_PERMISSIONS[MemberRole(role)])
