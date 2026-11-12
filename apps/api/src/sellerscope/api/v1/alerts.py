"""Alert rules (who gets told about what) and the alert inbox."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sellerscope.alerts.rules import DEFAULT_SEVERITY, ParamsError, RuleScope, parse_params
from sellerscope.auth.deps import OrgContext, OrgDep, SessionDep, rate_limit, require
from sellerscope.auth.permissions import Permission
from sellerscope.core.errors import AppError, not_found
from sellerscope.models import (
    Alert,
    AlertDelivery,
    AlertRule,
    OrganizationMember,
    Product,
    SellerProfile,
    User,
)
from sellerscope.models.enums import (
    AlertRuleType,
    AlertSeverity,
    AlertStatus,
    DeliveryStatus,
    MemberStatus,
)
from sellerscope.scanning.runner import utcnow
from sellerscope.schemas.alerts import (
    AlertBulkAction,
    AlertBulkResult,
    AlertOut,
    AlertPage,
    AlertRuleCreate,
    AlertRuleList,
    AlertRuleOut,
    AlertRuleUpdate,
    AlertStatusLit,
    AlertSummary,
    DeliveryOut,
    Severity,
)
from sellerscope.schemas.intel import ProductRef, SellerRef
from sellerscope.services import audit
from sellerscope.uploads.dispatch import TaskDispatcher

router = APIRouter(tags=["alerts"])
ManageAlerts = Annotated[OrgContext, Depends(require(Permission.ALERTS_MANAGE))]
MAX_RULES = 50


def _invalid(detail: str, errors: list[dict[str, Any]]) -> AppError:
    return AppError(422, "validation_error", "Invalid alert rule", detail, extra={"errors": errors})


def _check_params(rule_type: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        return parse_params(rule_type, params).model_dump(mode="json")
    except ParamsError as exc:
        errors = [
            {"loc": ["body", "params", str(e["field"])], "msg": e["message"], "type": "value_error"}
            for e in exc.errors
        ]
        raise _invalid("Some rule settings are not valid.", errors) from exc


async def _check_scope(session: AsyncSession, org: uuid.UUID, scope: RuleScope) -> dict[str, Any]:
    if scope.product_ids:
        found = set(
            (
                await session.execute(
                    select(Product.id).where(
                        Product.organization_id == org,
                        Product.id.in_(scope.product_ids),
                        Product.deleted_at.is_(None),
                    )
                )
            ).scalars()
        )
        missing = [str(p) for p in scope.product_ids if p not in found]
        if missing:
            raise _invalid(
                "Some selected products don't exist.",
                [
                    {
                        "loc": ["body", "scope", "product_ids"],
                        "msg": f"Unknown: {', '.join(missing)}",
                        "type": "value_error",
                    }
                ],
            )
    return scope.model_dump(mode="json")


async def _check_recipients(
    session: AsyncSession, org: uuid.UUID, ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    ids = list(dict.fromkeys(ids))
    if not ids:
        return ids
    found = set(
        (
            await session.execute(
                select(OrganizationMember.user_id).where(
                    OrganizationMember.organization_id == org,
                    OrganizationMember.user_id.in_(ids),
                    OrganizationMember.status == MemberStatus.ACTIVE,
                )
            )
        ).scalars()
    )
    if len(found) != len(ids):
        raise _invalid(
            "Email recipients must be active members of this organization.",
            [
                {
                    "loc": ["body", "recipient_user_ids"],
                    "msg": "Not an active member",
                    "type": "value_error",
                }
            ],
        )
    return ids


async def _get_rule(session: AsyncSession, org: uuid.UUID, rule_id: uuid.UUID) -> AlertRule:
    rule = (
        await session.execute(
            select(AlertRule).where(AlertRule.organization_id == org, AlertRule.id == rule_id)
        )
    ).scalar_one_or_none()
    if rule is None:
        raise not_found("Alert rule")
    return rule


async def _open_counts(session: AsyncSession, org: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = (
        await session.execute(
            select(Alert.alert_rule_id, func.count())
            .where(
                Alert.organization_id == org,
                Alert.alert_rule_id.is_not(None),
                Alert.status != AlertStatus.RESOLVED,
            )
            .group_by(Alert.alert_rule_id)
        )
    ).all()
    return {r[0]: r[1] for r in rows if r[0] is not None}


def _rule_out(rule: AlertRule, open_alerts: int = 0) -> AlertRuleOut:
    out = AlertRuleOut.model_validate(rule)
    out.open_alerts = open_alerts
    return out


# ------------------------------------------------------------------------------ rules


@router.get("/alert-rules", response_model=AlertRuleList)
async def list_rules(session: SessionDep, ctx: OrgDep) -> AlertRuleList:
    rules = (
        await session.execute(
            select(AlertRule)
            .where(AlertRule.organization_id == ctx.organization_id)
            .order_by(AlertRule.created_at, AlertRule.id)
        )
    ).scalars()
    counts = await _open_counts(session, ctx.organization_id)
    return AlertRuleList(items=[_rule_out(r, counts.get(r.id, 0)) for r in rules], limit=MAX_RULES)


@router.post(
    "/alert-rules",
    response_model=AlertRuleOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("alert-rule-write", limit=120, window_s=3600))],
)
async def create_rule(
    body: AlertRuleCreate, request: Request, session: SessionDep, ctx: ManageAlerts
) -> AlertRuleOut:
    org = ctx.organization_id
    count = (
        await session.execute(
            select(func.count()).select_from(AlertRule).where(AlertRule.organization_id == org)
        )
    ).scalar_one()
    if count >= MAX_RULES:
        raise AppError(
            409,
            "rule_limit_reached",
            "Too many alert rules",
            f"An organization can have up to {MAX_RULES} alert rules.",
            extra={"limit": MAX_RULES},
        )
    rule = AlertRule(
        organization_id=org,
        name=body.name,
        rule_type=body.rule_type,
        params=_check_params(body.rule_type, body.params),
        scope=await _check_scope(session, org, body.scope),
        severity=body.severity or DEFAULT_SEVERITY[AlertRuleType(body.rule_type)],
        channels=body.channels,
        recipient_user_ids=await _check_recipients(session, org, body.recipient_user_ids),
        is_enabled=body.is_enabled,
        created_by=ctx.user_id,
    )
    session.add(rule)
    await session.flush()
    audit.record(
        session,
        organization_id=org,
        actor_user_id=ctx.user_id,
        action="alert_rule.create",
        entity_type="alert_rule",
        entity_id=rule.id,
        request=request,
        details={"rule_type": rule.rule_type, "channels": rule.channels},
    )
    await session.flush()
    await session.refresh(rule)
    out = _rule_out(rule)
    await session.commit()  # tenant context is transaction-local: build the response first
    return out


@router.get("/alert-rules/{rule_id}", response_model=AlertRuleOut)
async def get_rule(rule_id: uuid.UUID, session: SessionDep, ctx: OrgDep) -> AlertRuleOut:
    rule = await _get_rule(session, ctx.organization_id, rule_id)
    counts = await _open_counts(session, ctx.organization_id)
    return _rule_out(rule, counts.get(rule.id, 0))


@router.patch(
    "/alert-rules/{rule_id}",
    response_model=AlertRuleOut,
    dependencies=[Depends(rate_limit("alert-rule-write", limit=120, window_s=3600))],
)
async def update_rule(
    rule_id: uuid.UUID,
    body: AlertRuleUpdate,
    request: Request,
    session: SessionDep,
    ctx: ManageAlerts,
) -> AlertRuleOut:
    org = ctx.organization_id
    rule = await _get_rule(session, org, rule_id)
    fields = body.model_fields_set
    if "name" in fields and body.name is not None:
        rule.name = body.name
    if "params" in fields and body.params is not None:
        rule.params = _check_params(rule.rule_type, body.params)
    if "scope" in fields and body.scope is not None:
        rule.scope = await _check_scope(session, org, body.scope)
    if "severity" in fields and body.severity is not None:
        rule.severity = body.severity
    if "channels" in fields and body.channels is not None:
        rule.channels = list(body.channels)
    if "recipient_user_ids" in fields and body.recipient_user_ids is not None:
        rule.recipient_user_ids = await _check_recipients(session, org, body.recipient_user_ids)
    if "is_enabled" in fields and body.is_enabled is not None:
        rule.is_enabled = body.is_enabled
    if "email" in rule.channels and not rule.recipient_user_ids:
        raise _invalid(
            "Choose at least one email recipient, or turn email off.",
            [
                {
                    "loc": ["body", "recipient_user_ids"],
                    "msg": "Required for email",
                    "type": "value_error",
                }
            ],
        )
    audit.record(
        session,
        organization_id=org,
        actor_user_id=ctx.user_id,
        action="alert_rule.update",
        entity_type="alert_rule",
        entity_id=rule.id,
        request=request,
        details={"fields": sorted(fields)},
    )
    await session.flush()
    await session.refresh(rule)
    counts = await _open_counts(session, org)
    out = _rule_out(rule, counts.get(rule.id, 0))
    await session.commit()
    return out


@router.delete(
    "/alert-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("alert-rule-write", limit=120, window_s=3600))],
)
async def delete_rule(
    rule_id: uuid.UUID, request: Request, session: SessionDep, ctx: ManageAlerts
) -> None:
    """Deletes the rule. Its past alerts stay (they keep the rule's name)."""
    org = ctx.organization_id
    rule = await _get_rule(session, org, rule_id)
    await session.execute(
        update(Alert)
        .where(Alert.organization_id == org, Alert.alert_rule_id == rule.id)
        .values(alert_rule_id=None)
    )
    audit.record(
        session,
        organization_id=org,
        actor_user_id=ctx.user_id,
        action="alert_rule.delete",
        entity_type="alert_rule",
        entity_id=rule.id,
        request=request,
        details={"name": rule.name, "rule_type": rule.rule_type},
    )
    await session.delete(rule)
    await session.commit()


# ------------------------------------------------------------------------------ alerts


async def _alerts_out(session: AsyncSession, org: uuid.UUID, alerts: list[Alert]) -> list[AlertOut]:
    if not alerts:
        return []
    product_ids = {a.product_id for a in alerts if a.product_id}
    seller_ids = {a.seller_profile_id for a in alerts if a.seller_profile_id}
    products = (
        {
            p.id: p
            for p in (
                await session.execute(
                    select(Product).where(
                        Product.organization_id == org, Product.id.in_(product_ids)
                    )
                )
            ).scalars()
        }
        if product_ids
        else {}
    )
    sellers = (
        {
            s.id: s
            for s in (
                await session.execute(
                    select(SellerProfile).where(
                        SellerProfile.organization_id == org, SellerProfile.id.in_(seller_ids)
                    )
                )
            ).scalars()
        }
        if seller_ids
        else {}
    )
    deliveries: dict[uuid.UUID, list[DeliveryOut]] = defaultdict(list)
    rows = (
        await session.execute(
            select(AlertDelivery, User.email)
            .outerjoin(User, User.id == AlertDelivery.recipient_user_id)
            .where(
                AlertDelivery.organization_id == org,
                AlertDelivery.alert_id.in_([a.id for a in alerts]),
            )
            .order_by(AlertDelivery.created_at, AlertDelivery.id)
        )
    ).all()
    for d, email in rows:
        deliveries[d.alert_id].append(
            DeliveryOut(
                channel=d.channel,
                recipient_user_id=d.recipient_user_id,
                recipient_email=email,
                status=d.status,
                attempt_count=d.attempt_count,
                last_error=d.last_error,
                next_attempt_at=d.next_attempt_at if d.status == DeliveryStatus.PENDING else None,
                sent_at=d.sent_at,
            )
        )
    out: list[AlertOut] = []
    for a in alerts:
        p = products.get(a.product_id) if a.product_id else None
        s = sellers.get(a.seller_profile_id) if a.seller_profile_id else None
        out.append(
            AlertOut(
                id=a.id,
                alert_rule_id=a.alert_rule_id,
                rule_name=a.rule_name,
                rule_type=a.rule_type,
                severity=a.severity,
                status=a.status,
                title=a.title,
                body=a.body,
                details=a.details,
                product=ProductRef(
                    id=p.id,
                    external_id=p.external_id,
                    product_name=p.product_name,
                    brand_name=p.brand_name,
                )
                if p
                else None,
                seller=SellerRef.model_validate(s) if s else None,
                scan_result_id=a.scan_result_id,
                scan_history_id=a.scan_history_id,
                created_at=a.created_at,
                acknowledged_by=a.acknowledged_by,
                acknowledged_at=a.acknowledged_at,
                resolved_by=a.resolved_by,
                resolved_at=a.resolved_at,
                resolved_automatically=a.resolved_at is not None and a.resolved_by is None,
                delivered_channels=a.delivered_channels,
                deliveries=deliveries.get(a.id, []),
            )
        )
    return out


async def _get_alert(session: AsyncSession, org: uuid.UUID, alert_id: uuid.UUID) -> Alert:
    alert = (
        await session.execute(
            select(Alert).where(Alert.organization_id == org, Alert.id == alert_id)
        )
    ).scalar_one_or_none()
    if alert is None:
        raise not_found("Alert")
    return alert


@router.get("/alerts", response_model=AlertPage)
async def list_alerts(
    session: SessionDep,
    ctx: OrgDep,
    status_: Annotated[AlertStatusLit | None, Query(alias="status")] = None,
    active: Annotated[bool, Query(description="open + acknowledged")] = False,
    severity: Severity | None = None,
    rule_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> AlertPage:
    org = ctx.organization_id
    conditions = [Alert.organization_id == org]
    if status_:
        conditions.append(Alert.status == status_)
    elif active:
        conditions.append(Alert.status != AlertStatus.RESOLVED)
    if severity:
        conditions.append(Alert.severity == severity)
    if rule_id:
        conditions.append(Alert.alert_rule_id == rule_id)
    if product_id:
        conditions.append(Alert.product_id == product_id)
    where = and_(*conditions)
    total = (
        await session.execute(select(func.count()).select_from(Alert).where(where))
    ).scalar_one()
    alerts = list(
        (
            await session.execute(
                select(Alert)
                .where(where)
                .order_by(Alert.created_at.desc(), Alert.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars()
    )
    return AlertPage(
        items=await _alerts_out(session, org, alerts),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/alerts/summary", response_model=AlertSummary)
async def alert_summary(session: SessionDep, ctx: OrgDep) -> AlertSummary:
    org = ctx.organization_id
    rows = (
        await session.execute(
            select(Alert.status, Alert.severity, func.count())
            .where(Alert.organization_id == org, Alert.status != AlertStatus.RESOLVED)
            .group_by(Alert.status, Alert.severity)
        )
    ).all()
    by_severity: dict[str, int] = {s.value: 0 for s in AlertSeverity}
    open_, acked = 0, 0
    for st, sev, n in rows:
        if st == AlertStatus.OPEN:
            open_ += n
            by_severity[sev] += n
        else:
            acked += n
    failed = (
        await session.execute(
            select(func.count())
            .select_from(AlertDelivery)
            .where(
                AlertDelivery.organization_id == org,
                AlertDelivery.status == DeliveryStatus.FAILED,
            )
        )
    ).scalar_one()
    return AlertSummary(
        open=open_, acknowledged=acked, open_by_severity=by_severity, failed_deliveries=failed
    )


@router.get("/alerts/{alert_id}", response_model=AlertOut)
async def get_alert(alert_id: uuid.UUID, session: SessionDep, ctx: OrgDep) -> AlertOut:
    alert = await _get_alert(session, ctx.organization_id, alert_id)
    return (await _alerts_out(session, ctx.organization_id, [alert]))[0]


async def _transition(
    session: AsyncSession, ctx: OrgContext, ids: list[uuid.UUID], action: str
) -> int:
    now = utcnow()
    org = ctx.organization_id
    if action == "acknowledge":
        stmt = (
            update(Alert)
            .where(
                Alert.organization_id == org,
                Alert.id.in_(ids),
                Alert.status == AlertStatus.OPEN,
            )
            .values(
                status=AlertStatus.ACKNOWLEDGED, acknowledged_by=ctx.user_id, acknowledged_at=now
            )
        )
    else:
        stmt = (
            update(Alert)
            .where(
                Alert.organization_id == org,
                Alert.id.in_(ids),
                Alert.status != AlertStatus.RESOLVED,
            )
            .values(status=AlertStatus.RESOLVED, resolved_by=ctx.user_id, resolved_at=now)
        )
    result = await session.execute(stmt)
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def _commit_and_return(session: AsyncSession, ctx: OrgContext, alert: Alert) -> AlertOut:
    """Builds the response inside the transaction (the tenant context ends at commit)."""
    await session.refresh(alert)
    out = (await _alerts_out(session, ctx.organization_id, [alert]))[0]
    await session.commit()
    return out


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
async def acknowledge(alert_id: uuid.UUID, session: SessionDep, ctx: OrgDep) -> AlertOut:
    """Marks an open alert as seen. Resolved alerts can't be acknowledged."""
    alert = await _get_alert(session, ctx.organization_id, alert_id)
    if alert.status == AlertStatus.RESOLVED:
        raise AppError(409, "alert_resolved", "Alert already resolved")
    await _transition(session, ctx, [alert.id], "acknowledge")
    return await _commit_and_return(session, ctx, alert)


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut)
async def resolve(alert_id: uuid.UUID, session: SessionDep, ctx: OrgDep) -> AlertOut:
    alert = await _get_alert(session, ctx.organization_id, alert_id)
    await _transition(session, ctx, [alert.id], "resolve")
    return await _commit_and_return(session, ctx, alert)


@router.post("/alerts/bulk", response_model=AlertBulkResult)
async def bulk(body: AlertBulkAction, session: SessionDep, ctx: OrgDep) -> AlertBulkResult:
    """Acknowledges or resolves several alerts. Ids from other organizations are ignored."""
    updated = await _transition(session, ctx, list(dict.fromkeys(body.ids)), body.action)
    await session.commit()
    return AlertBulkResult(updated=updated)


@router.post(
    "/alerts/{alert_id}/retry-delivery",
    response_model=AlertOut,
    dependencies=[Depends(rate_limit("alert-retry", limit=60, window_s=3600))],
)
async def retry_delivery(
    alert_id: uuid.UUID, request: Request, session: SessionDep, ctx: ManageAlerts
) -> AlertOut:
    """Re-queues this alert's emails that gave up after all retries."""
    alert = await _get_alert(session, ctx.organization_id, alert_id)
    result = await session.execute(
        update(AlertDelivery)
        .where(
            AlertDelivery.organization_id == ctx.organization_id,
            AlertDelivery.alert_id == alert.id,
            AlertDelivery.status == DeliveryStatus.FAILED,
        )
        .values(status=DeliveryStatus.PENDING, attempt_count=0, next_attempt_at=utcnow())
    )
    if not result.rowcount:  # type: ignore[attr-defined]
        raise AppError(409, "nothing_to_retry", "No failed emails", "No failed emails to retry.")
    out = await _commit_and_return(session, ctx, alert)
    dispatcher: TaskDispatcher = request.app.state.task_dispatcher
    await dispatcher.deliver_alerts(ctx.organization_id)
    return out
