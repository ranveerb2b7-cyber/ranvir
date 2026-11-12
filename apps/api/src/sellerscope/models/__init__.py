"""All ORM models. Importing this package registers every table on Base.metadata."""

from sellerscope.models.billing import Plan, Subscription
from sellerscope.models.identity import Invitation, Organization, OrganizationMember, User
from sellerscope.models.marketplace import Marketplace, MarketplaceConnection
from sellerscope.models.operations import (
    Alert,
    AlertDelivery,
    AlertRule,
    AuditLog,
    ExtensionToken,
    ReportExport,
)
from sellerscope.models.products import Product, ProductBatch, ProductBatchRow
from sellerscope.models.scanning import (
    APPEND_ONLY_TABLES,
    ProductOffer,
    ScanHistory,
    ScanJob,
    ScanJobItem,
    ScanResult,
    SellerProfile,
)

__all__ = [
    "APPEND_ONLY_TABLES",
    "Alert",
    "AlertDelivery",
    "AlertRule",
    "AuditLog",
    "ExtensionToken",
    "Invitation",
    "Marketplace",
    "MarketplaceConnection",
    "Organization",
    "OrganizationMember",
    "Plan",
    "Product",
    "ProductBatch",
    "ProductBatchRow",
    "ProductOffer",
    "ReportExport",
    "ScanHistory",
    "ScanJob",
    "ScanJobItem",
    "ScanResult",
    "SellerProfile",
    "Subscription",
    "User",
]
