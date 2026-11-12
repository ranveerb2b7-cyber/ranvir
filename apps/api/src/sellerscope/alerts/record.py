"""Runs alert rules inside the scan transaction and stores the resulting alerts.

Alerts and their pending email deliveries are written in the SAME transaction as the snapshot
and change events, so an alert exists exactly when its scan does. Emails are sent later by the
delivery worker (after commit).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from sellerscope.alerts.engine import (
    Decision,
    EventFacts,
    OfferFacts,
    ProductFacts,
    Raise,
    Rule,
    ScanOutcome,
    SellerFacts,
    evaluate,
)
from sellerscope.alerts.rules import ParamsError, RuleScope, parse_params
from sellerscope.core.ids import uuid7
from sellerscope.models import (
    Alert,
    AlertDelivery,
    AlertRule,
    Product,
    ProductOffer,
    ScanResult,
    SellerProfile,
)
from sellerscope.models.enums import AlertChannel, AlertRuleType, AlertStatus
from sellerscope.scanning.diff import Change

log = structlog.get_logger()


def to_rule(row: AlertRule) -> Rule:
    return Rule(
        id=row.id,
        name=row.name,
        rule_type=AlertRuleType(row.rule_type),
        severity=row.severity,
        params=parse_params(row.rule_type, row.params),
        scope=RuleScope.model_validate(row.scope or {}),
        channels=tuple(row.channels),
        recipients=tuple(row.recipient_user_ids),
    )


async def load_rules(session: AsyncSession, organization_id: uuid.UUID) -> list[Rule]:
    rows = (
        (
            await session.execute(
                select(AlertRule)
                .where(AlertRule.organization_id == organization_id, AlertRule.is_enabled)
                .order_by(AlertRule.created_at, AlertRule.id)
            )
        )
        .scalars()
        .all()
    )
    rules: list[Rule] = []
    for row in rows:
        try:
            rules.append(to_rule(row))
        except (ParamsError, ValueError):  # stored before a validation change; never crash scans
            log.error("alert_rule_invalid", rule_id=str(row.id), rule_type=row.rule_type)
    return rules


async def _sellers(
    session: AsyncSession, organization_id: uuid.UUID, ids: set[uuid.UUID]
) -> dict[uuid.UUID, SellerFacts]:
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(
                SellerProfile.id,
                SellerProfile.external_seller_id,
                SellerProfile.display_name,
                SellerProfile.tags,
            ).where(SellerProfile.organization_id == organization_id, SellerProfile.id.in_(ids))
        )
    ).all()
    return {
        r.id: SellerFacts(r.id, r.external_seller_id, r.display_name, frozenset(r.tags))
        for r in rows
    }


async def _product(
    session: AsyncSession, organization_id: uuid.UUID, product_id: uuid.UUID
) -> ProductFacts:
    row = (
        await session.execute(
            select(Product.id, Product.external_id, Product.product_name, Product.brand_name).where(
                Product.organization_id == organization_id, Product.id == product_id
            )
        )
    ).one()
    return ProductFacts(row.id, row.external_id, row.product_name, row.brand_name)


async def _apply(
    session: AsyncSession,
    organization_id: uuid.UUID,
    product: ProductFacts,
    scan_result_id: uuid.UUID,
    decisions: list[Decision],
    now: datetime,
) -> list[uuid.UUID]:
    created: list[uuid.UUID] = []
    for d in decisions:
        if not isinstance(d, Raise):
            await session.execute(
                update(Alert)
                .where(
                    Alert.organization_id == organization_id,
                    Alert.alert_rule_id == d.rule.id,
                    Alert.dedupe_key == d.dedupe_key,
                    Alert.status != AlertStatus.RESOLVED,
                )
                .values(status=AlertStatus.RESOLVED, resolved_at=now, resolved_by=None)
            )
            continue
        alert_id = (
            await session.execute(
                pg_insert(Alert)
                .values(
                    id=uuid7(),
                    organization_id=organization_id,
                    alert_rule_id=d.rule.id,
                    rule_name=d.rule.name,
                    rule_type=d.rule.rule_type,
                    dedupe_key=d.dedupe_key,
                    product_id=product.id,
                    scan_result_id=scan_result_id,
                    scan_history_id=d.scan_history_id,
                    seller_profile_id=d.seller_profile_id,
                    severity=d.rule.severity,
                    title=d.title,
                    body=d.body,
                    details=d.details,
                    delivered_channels=[AlertChannel.IN_APP],
                )
                .on_conflict_do_nothing(
                    index_elements=["organization_id", "alert_rule_id", "dedupe_key"],
                    index_where=text("status <> 'resolved'"),
                )
                .returning(Alert.id)
            )
        ).scalar_one_or_none()
        if alert_id is None:
            continue  # the same condition already has an unresolved alert
        created.append(alert_id)
        if AlertChannel.EMAIL in d.rule.channels and d.rule.recipients:
            await session.execute(
                pg_insert(AlertDelivery)
                .values(
                    [
                        {
                            "id": uuid7(),
                            "organization_id": organization_id,
                            "alert_id": alert_id,
                            "channel": AlertChannel.EMAIL,
                            "recipient_user_id": user_id,
                            "next_attempt_at": now,
                        }
                        for user_id in dict.fromkeys(d.rule.recipients)
                    ]
                )
                .on_conflict_do_nothing()
            )
    return created


async def alerts_for_scan(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    product_id: uuid.UUID,
    result_id: uuid.UUID,
    events: list[tuple[uuid.UUID, Change]],
    rules: list[Rule],
    now: datetime,
) -> list[uuid.UUID]:
    """Evaluates rules for a recorded snapshot (or failure). Returns ids of new alerts."""
    if not rules:
        return []
    result = (
        await session.execute(
            select(ScanResult).where(
                ScanResult.organization_id == organization_id, ScanResult.id == result_id
            )
        )
    ).scalar_one()
    offer_rows = (
        await session.execute(
            select(ProductOffer.seller_profile_id, ProductOffer.landed_price, ProductOffer.currency)
            .where(
                ProductOffer.organization_id == organization_id,
                ProductOffer.scan_result_id == result_id,
            )
            .order_by(ProductOffer.position)
        )
    ).all()
    seller_ids = {r.seller_profile_id for r in offer_rows if r.seller_profile_id}
    seller_ids |= {c.seller_profile_id for _, c in events if c.seller_profile_id}
    sellers = await _sellers(session, organization_id, seller_ids)
    outcome = ScanOutcome(
        result_id=result.id,
        status=result.status,
        error_code=result.error_code,
        unique_seller_count=result.unique_seller_count,
        is_offer_list_truncated=result.is_offer_list_truncated,
        offers=[
            OfferFacts(
                sellers.get(r.seller_profile_id) if r.seller_profile_id else None,
                r.landed_price,
                r.currency,
            )
            for r in offer_rows
        ],
        events=[
            EventFacts(hid, c, sellers.get(c.seller_profile_id) if c.seller_profile_id else None)
            for hid, c in events
        ],
    )
    product = await _product(session, organization_id, product_id)
    decisions = evaluate(rules, product, outcome)
    if not decisions:
        return []
    return await _apply(session, organization_id, product, result_id, decisions, now)


async def safe_alerts_for_scan(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    product_id: uuid.UUID,
    result_id: uuid.UUID,
    events: list[tuple[uuid.UUID, Change]],
    rules: list[Rule],
    now: datetime,
) -> list[uuid.UUID]:
    """Like alerts_for_scan, but a bug in alerting can never lose the scan itself.

    Runs in a savepoint; on error the alert work is rolled back and the error is logged with
    the product and scan ids so it can be investigated (the snapshot still commits).
    """
    if not rules:
        return []
    try:
        async with session.begin_nested():
            return await alerts_for_scan(
                session,
                organization_id=organization_id,
                product_id=product_id,
                result_id=result_id,
                events=events,
                rules=rules,
                now=now,
            )
    except Exception:
        log.exception(
            "alert_evaluation_failed",
            organization_id=str(organization_id),
            product_id=str(product_id),
            result_id=str(result_id),
        )
        return []
