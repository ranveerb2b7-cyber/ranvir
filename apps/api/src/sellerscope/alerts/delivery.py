"""Sends pending alert emails, one digest per recipient, AFTER the alerts were committed.

Lifecycle of an alert_deliveries row: pending -> sending (claimed) -> sent | pending (retry
with backoff) | failed (gave up) | skipped (recipient no longer an active member). Every
failure is recorded on the row (last_error) and shown in the app; nothing is swallowed.
A worker that dies mid-send leaves rows in "sending"; alert_delivery_orgs() returns them to
"pending" after a timeout (so an email may, rarely, be sent twice; never silently lost).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import structlog
from sqlalchemy import and_, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sellerscope.core.config import Settings
from sellerscope.db.tenant import set_tenant_context
from sellerscope.models import (
    Alert,
    AlertDelivery,
    Organization,
    OrganizationMember,
    User,
)
from sellerscope.models.enums import AlertChannel, DeliveryStatus, MemberStatus
from sellerscope.services.mailer import Mailer, build_message

log = structlog.get_logger()

MAX_IN_EMAIL = 25
NOT_A_MEMBER = "Recipient is no longer an active member of this organization."


@dataclass(slots=True)
class _Item:
    delivery_id: uuid.UUID
    alert_id: uuid.UUID
    severity: str
    title: str
    body: str | None
    created_at: datetime


@dataclass(slots=True)
class _Digest:
    email: str
    items: list[_Item] = field(default_factory=list)


@dataclass(slots=True)
class DeliveryReport:
    sent: int = 0
    retrying: int = 0
    failed: int = 0
    skipped: int = 0


def backoff(attempt: int, settings: Settings) -> timedelta:
    return timedelta(seconds=min(settings.alert_delivery_backoff_s * 2 ** (attempt - 1), 3600))


def render_digest(org_name: str, digest: _Digest, web_base_url: str) -> tuple[str, str]:
    items = sorted(digest.items, key=lambda i: i.created_at)
    n = len(items)
    subject = f"[SellerScope] {items[0].title}" if n == 1 else f"[SellerScope] {n} new alerts"
    lines = [f"{n} new alert{'s' if n != 1 else ''} for {org_name}:", ""]
    for item in items[:MAX_IN_EMAIL]:
        lines.append(f"[{item.severity.upper()}] {item.title}")
        if item.body:
            lines.append(f"  {item.body}")
        lines.append(f"  {web_base_url}/alerts?alert={item.alert_id}")
        lines.append("")
    if n > MAX_IN_EMAIL:
        lines += [f"...and {n - MAX_IN_EMAIL} more: {web_base_url}/alerts", ""]
    lines += [
        "You receive these emails because an alert rule in SellerScope lists you as a recipient.",
        f"Manage alert rules: {web_base_url}/alerts?tab=rules",
    ]
    return subject, "\n".join(lines)


async def _claim(
    session: AsyncSession, org: uuid.UUID, now: datetime, limit: int
) -> tuple[str, dict[uuid.UUID, _Digest], list[uuid.UUID]]:
    """Claims due email deliveries. Returns (org name, digests by user, skipped ids)."""
    rows = (
        await session.execute(
            select(
                AlertDelivery.id,
                AlertDelivery.recipient_user_id,
                Alert.id.label("alert_id"),
                Alert.severity,
                Alert.title,
                Alert.body,
                Alert.created_at,
                User.email,
                OrganizationMember.id.label("member_id"),
            )
            .join(
                Alert,
                and_(
                    Alert.id == AlertDelivery.alert_id,
                    Alert.organization_id == AlertDelivery.organization_id,
                ),
            )
            .outerjoin(User, and_(User.id == AlertDelivery.recipient_user_id, User.is_active))
            .outerjoin(
                OrganizationMember,
                and_(
                    OrganizationMember.organization_id == AlertDelivery.organization_id,
                    OrganizationMember.user_id == AlertDelivery.recipient_user_id,
                    OrganizationMember.status == MemberStatus.ACTIVE,
                ),
            )
            .where(
                AlertDelivery.organization_id == org,
                AlertDelivery.channel == AlertChannel.EMAIL,
                AlertDelivery.status == DeliveryStatus.PENDING,
                (AlertDelivery.next_attempt_at.is_(None)) | (AlertDelivery.next_attempt_at <= now),
            )
            .order_by(AlertDelivery.created_at, AlertDelivery.id)
            .limit(limit)
            .with_for_update(of=AlertDelivery, skip_locked=True)
        )
    ).all()
    org_name = (
        await session.execute(select(Organization.name).where(Organization.id == org))
    ).scalar_one()
    digests: dict[uuid.UUID, _Digest] = {}
    skipped: list[uuid.UUID] = []
    for r in rows:
        if r.recipient_user_id is None or r.email is None or r.member_id is None:
            skipped.append(r.id)
            continue
        digest = digests.setdefault(r.recipient_user_id, _Digest(r.email))
        digest.items.append(_Item(r.id, r.alert_id, r.severity, r.title, r.body, r.created_at))
    claimed = [i.delivery_id for d in digests.values() for i in d.items]
    if claimed:
        await session.execute(
            update(AlertDelivery)
            .where(AlertDelivery.id.in_(claimed))
            .values(
                status=DeliveryStatus.SENDING,
                claimed_at=now,
                attempt_count=AlertDelivery.attempt_count + 1,
            )
        )
    if skipped:
        await session.execute(
            update(AlertDelivery)
            .where(AlertDelivery.id.in_(skipped))
            .values(status=DeliveryStatus.SKIPPED, last_error=NOT_A_MEMBER, next_attempt_at=None)
        )
    return org_name, digests, skipped


async def deliver_pending(
    session_factory: async_sessionmaker[AsyncSession],
    mailer: Mailer,
    settings: Settings,
    *,
    organization_id: uuid.UUID,
    now: datetime,
    limit: int = 500,
) -> DeliveryReport:
    report = DeliveryReport()
    async with session_factory() as session, session.begin():
        await set_tenant_context(session, organization_id=organization_id, user_id=None)
        org_name, digests, skipped = await _claim(session, organization_id, now, limit)
    report.skipped = len(skipped)
    if not digests:
        return report

    # Network I/O happens outside any transaction.
    outcomes: dict[uuid.UUID, str | None] = {}
    for user_id, digest in digests.items():
        subject, body = render_digest(org_name, digest, settings.web_base_url)
        try:
            await mailer.send(build_message(digest.email, subject, body))
            outcomes[user_id] = None
        except Exception as exc:
            outcomes[user_id] = f"{type(exc).__name__}: {exc}"[:500]
            log.warning(
                "alert_email_failed",
                organization_id=str(organization_id),
                error=outcomes[user_id],
                alerts=len(digest.items),
            )

    async with session_factory() as session, session.begin():
        await set_tenant_context(session, organization_id=organization_id, user_id=None)
        for user_id, digest in digests.items():
            ids = [i.delivery_id for i in digest.items]
            error = outcomes[user_id]
            if error is None:
                await session.execute(
                    update(AlertDelivery)
                    .where(AlertDelivery.id.in_(ids))
                    .values(status=DeliveryStatus.SENT, sent_at=now, last_error=None)
                )
                await session.execute(
                    update(Alert)
                    .where(
                        Alert.organization_id == organization_id,
                        Alert.id.in_([i.alert_id for i in digest.items]),
                        ~Alert.delivered_channels.contains([AlertChannel.EMAIL.value]),
                    )
                    .values(
                        delivered_channels=func.array_append(
                            Alert.delivered_channels, AlertChannel.EMAIL.value
                        )
                    )
                )
                report.sent += len(ids)
                continue
            rows = (
                await session.execute(
                    select(AlertDelivery.id, AlertDelivery.attempt_count).where(
                        AlertDelivery.id.in_(ids)
                    )
                )
            ).all()
            for row in rows:
                if row.attempt_count >= settings.alert_delivery_max_attempts:
                    values: dict[str, object] = {
                        "status": DeliveryStatus.FAILED,
                        "next_attempt_at": None,
                    }
                    report.failed += 1
                else:
                    values = {
                        "status": DeliveryStatus.PENDING,
                        "next_attempt_at": now + backoff(row.attempt_count, settings),
                    }
                    report.retrying += 1
                await session.execute(
                    update(AlertDelivery)
                    .where(AlertDelivery.id == row.id)
                    .values(last_error=error, **values)
                )
    return report


async def deliver_all_due(
    session_factory: async_sessionmaker[AsyncSession],
    mailer: Mailer,
    settings: Settings,
    *,
    now: datetime,
    stale_after_s: int = 600,
) -> int:
    """Beat entry point: every organization with due deliveries. Returns orgs processed."""
    async with session_factory() as session, session.begin():
        orgs = (
            (
                await session.execute(
                    text("SELECT * FROM alert_delivery_orgs(:s)"), {"s": stale_after_s}
                )
            )
            .scalars()
            .all()
        )
    for org in orgs:
        try:
            await deliver_pending(session_factory, mailer, settings, organization_id=org, now=now)
        except Exception:  # one organization's problem must not block the others
            log.exception("alert_delivery_run_failed", organization_id=str(org))
    return len(orgs)
