"""String enums persisted as text + CHECK constraints."""

from __future__ import annotations

from enum import StrEnum


class MemberRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class MemberStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class SubscriptionStatus(StrEnum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"


class BillingProvider(StrEnum):
    RAZORPAY = "razorpay"
    STRIPE = "stripe"


class ConnectionType(StrEnum):
    SP_API_OAUTH = "sp_api_oauth"
    SP_API_SELF_AUTH = "sp_api_self_auth"


class ConnectionStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"
    ERROR = "error"


class BatchStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PREVIEW_READY = "preview_ready"
    COMMITTED = "committed"
    FAILED = "failed"
    DISCARDED = "discarded"


class BatchRowStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    DUPLICATE_IN_FILE = "duplicate_in_file"
    DUPLICATE_EXISTING = "duplicate_existing"


class IdentifierStatus(StrEnum):
    FORMAT_VALID = "format_valid"
    VERIFIED = "verified"
    NOT_FOUND = "not_found"
    UNVERIFIABLE = "unverifiable"


class ScanTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    EXTENSION = "extension"
    API = "api"


class ScanJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScanItemStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_SCAN_ITEM_STATUSES = (ScanItemStatus.PENDING, ScanItemStatus.PROCESSING)


class ScanResultStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class FulfilmentChannel(StrEnum):
    AMAZON = "amazon"
    MERCHANT = "merchant"
    UNKNOWN = "unknown"


class HistoryEventType(StrEnum):
    SELLER_NEWLY_OBSERVED = "seller_newly_observed"
    SELLER_NO_LONGER_OBSERVED = "seller_no_longer_observed"
    SELLER_NOT_OBSERVED_INCONCLUSIVE = "seller_not_observed_inconclusive"
    OFFER_COUNT_CHANGED = "offer_count_changed"
    PRICE_CHANGED = "price_changed"
    BUY_BOX_CHANGED = "buy_box_changed"
    SCAN_UNAVAILABLE = "scan_unavailable"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AlertRuleType(StrEnum):
    NEW_SELLER = "new_seller"
    SELLER_COUNT_ABOVE = "seller_count_above"
    PRICE_BELOW = "price_below"
    OFFER_COUNT_CHANGE = "offer_count_change"
    SCAN_FAILED = "scan_failed"
    SELLER_GONE = "seller_gone"
    BUY_BOX_CHANGED = "buy_box_changed"


class AlertChannel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class ReportType(StrEnum):
    PRODUCT = "product"
    MARKETPLACE = "marketplace"
    BRAND = "brand"
    SELLER = "seller"
    SCAN_SUMMARY = "scan_summary"
    ERRORS = "errors"


class ReportFormat(StrEnum):
    XLSX = "xlsx"
    CSV = "csv"


class ReportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class ActorType(StrEnum):
    USER = "user"
    SYSTEM = "system"
    EXTENSION = "extension"
