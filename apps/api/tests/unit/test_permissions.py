import pytest

from sellerscope.auth.permissions import Permission, has_permission

# Mirrors the RBAC table in docs/plan/01-architecture.md §1.5.
EXPECTED = {
    Permission.PRODUCTS_WRITE: {"owner", "admin", "analyst"},
    Permission.SCANS_RUN: {"owner", "admin", "analyst"},
    Permission.ALERTS_MANAGE: {"owner", "admin", "analyst"},
    Permission.CONNECTIONS_MANAGE: {"owner", "admin"},
    Permission.MEMBERS_MANAGE: {"owner", "admin"},
    Permission.ORG_MANAGE: {"owner", "admin"},
    Permission.BILLING_MANAGE: {"owner"},
    Permission.ORG_DELETE: {"owner"},
}


@pytest.mark.parametrize("permission", list(Permission))
def test_role_permission_matrix(permission: Permission) -> None:
    allowed = {r for r in ("owner", "admin", "analyst", "viewer") if has_permission(r, permission)}
    assert allowed == EXPECTED[permission]


def test_viewer_has_no_write_permissions() -> None:
    assert not any(has_permission("viewer", p) for p in Permission)
