"""Browser extension API.

Pairing: a signed-in member approves on the web (`pair/start`, organization-scoped) and the
extension redeems the one-time code with its PKCE verifier (`pair/complete`, public).
Everything else authenticates with the extension token (ExtensionDep), which carries its own
organization, so these routes are not organization-header routes.

The extension sends only the page URL (or an ASIN parsed from it). It never sends page
content, and lookups read only data SellerScope already stored from authorized sources.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import and_, select, text, update

from sellerscope.auth.deps import OrgDep, SessionDep, rate_limit
from sellerscope.auth.permissions import Permission
from sellerscope.connectors.base import ConnectorUnavailableError, Limitation
from sellerscope.connectors.identifiers import ERROR_MESSAGES, MarketplaceCode, parse_identifier
from sellerscope.connectors.registry import ConnectorRegistry
from sellerscope.core.errors import AppError, not_found
from sellerscope.core.rate_limit import RateLimiter, client_ip
from sellerscope.db.tenant import set_tenant_context
from sellerscope.extension.auth import (
    SCOPE_CHECK,
    SCOPE_READ,
    SCOPES,
    ExtensionContext,
    ExtensionDep,
    member_role,
    new_pairing_code,
    new_token,
    normalize_code,
    s256_challenge,
    sha256,
)
from sellerscope.models import (
    ExtensionPairing,
    ExtensionToken,
    Marketplace,
    Organization,
    Product,
    ScanJob,
    ScanJobItem,
    ScanResult,
    User,
)
from sellerscope.models.enums import ActorType, ScanItemStatus, ScanResultStatus, ScanTrigger
from sellerscope.scanning.jobs import create_scan_job
from sellerscope.scanning.runner import utcnow
from sellerscope.schemas.extension import (
    ActiveScan,
    CheckRequest,
    CheckStarted,
    ExtensionMe,
    ExtensionTokenOut,
    LookupAttempt,
    LookupProduct,
    LookupResult,
    LookupSnapshot,
    OrgRef,
    PairComplete,
    PairCompleted,
    PairStart,
    PairStarted,
)
from sellerscope.services import audit
from sellerscope.uploads.dispatch import TaskDispatcher

router = APIRouter(prefix="/extension", tags=["browser extension"])
USABLE = (ScanResultStatus.OK, ScanResultStatus.PARTIAL)


def _invalid_code() -> AppError:
    return AppError(
        400,
        "invalid_pairing_code",
        "Code not accepted",
        "This code is invalid, expired or already used. Get a new code in SellerScope.",
    )


def _require_scope(ctx: ExtensionContext, scope: str) -> None:
    if scope not in ctx.scopes:
        raise AppError(403, "forbidden", "Forbidden", f"This connection lacks the {scope} scope.")


async def _per_token(request: Request, ctx: ExtensionContext, name: str, limit: int) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    await limiter.check(f"{name}:ext:{ctx.token_id}", limit, 3600)


# ------------------------------------------------------------------------------ pairing


@router.post(
    "/pair/start",
    response_model=PairStarted,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("extension-pair-start", limit=20, window_s=3600))],
)
async def pair_start(
    body: PairStart, request: Request, session: SessionDep, ctx: OrgDep
) -> PairStarted:
    """Issued to a signed-in member who approved connecting an extension (web page)."""
    settings = request.app.state.settings
    code = new_pairing_code()
    expires = utcnow() + timedelta(seconds=settings.extension_pairing_ttl_s)
    pairing = ExtensionPairing(
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        code_hash=sha256(code),
        code_challenge=body.code_challenge,
        device_name=body.device_name,
        expires_at=expires,
    )
    session.add(pairing)
    await session.flush()
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="extension.pair_start",
        entity_type="extension_pairing",
        entity_id=pairing.id,
        request=request,
        details={"device_name": body.device_name},
    )
    org_name = (
        await session.execute(
            select(Organization.name).where(Organization.id == ctx.organization_id)
        )
    ).scalar_one()
    await session.commit()
    return PairStarted(pairing_code=code, expires_at=expires, organization_name=org_name)


@router.post("/pair/complete", response_model=PairCompleted)
async def pair_complete(body: PairComplete, request: Request, session: SessionDep) -> PairCompleted:
    """Public: the extension exchanges code + PKCE verifier for a token (shown once)."""
    limiter: RateLimiter = request.app.state.rate_limiter
    await limiter.check(
        f"extension-pair-complete:ip:{client_ip(request)}",
        request.app.state.settings.extension_pair_ip_per_minute,
        60,
    )
    row = (
        await session.execute(
            text("SELECT * FROM redeem_extension_pairing(:h, :c)"),
            {
                "h": sha256(normalize_code(body.pairing_code)),
                "c": s256_challenge(body.code_verifier),
            },
        )
    ).one_or_none()
    if row is None:
        await session.rollback()
        raise _invalid_code()
    org, pairing_id, user_id, device_name = row
    await set_tenant_context(session, organization_id=org, user_id=user_id)
    member = await member_role(session, org, user_id)
    if member is None:
        await session.commit()  # the code is spent either way
        raise _invalid_code()
    _, email, org_name = member
    settings = request.app.state.settings
    raw = new_token()
    token = ExtensionToken(
        organization_id=org,
        user_id=user_id,
        token_hash=sha256(raw),
        name=device_name,
        scopes=list(SCOPES),
        expires_at=utcnow() + timedelta(days=settings.extension_token_days),
    )
    session.add(token)
    await session.flush()
    await session.execute(
        update(ExtensionPairing)
        .where(ExtensionPairing.organization_id == org, ExtensionPairing.id == pairing_id)
        .values(extension_token_id=token.id)
    )
    audit.record(
        session,
        organization_id=org,
        actor_user_id=user_id,
        action="extension.connect",
        entity_type="extension_token",
        entity_id=token.id,
        request=request,
        details={"device_name": device_name},
    )
    expires = token.expires_at
    await session.commit()
    return PairCompleted(
        token=raw,
        expires_at=expires,
        scopes=list(SCOPES),
        organization=OrgRef(id=org, name=org_name),
        user_email=email,
    )


# ------------------------------------------------------------------------------ extension calls


@router.get("/me", response_model=ExtensionMe)
async def me(ctx: ExtensionDep) -> ExtensionMe:
    return ExtensionMe(
        organization=OrgRef(id=ctx.organization_id, name=ctx.organization_name),
        user_email=ctx.email,
        role=ctx.role,
        scopes=list(ctx.scopes),
        can_check=SCOPE_CHECK in ctx.scopes and ctx.can(Permission.SCANS_RUN),
    )


def _parse(marketplace: str, raw: str) -> str:
    parsed = parse_identifier(marketplace, raw)
    if not parsed.valid or parsed.normalized is None:
        assert parsed.error is not None
        raise AppError(
            422,
            "invalid_identifier",
            "Not a product page",
            ERROR_MESSAGES[parsed.error],
            extra={"reason": parsed.error},
        )
    return parsed.normalized


async def _product(
    session: SessionDep, ctx: ExtensionContext, marketplace: str, asin: str
) -> Product | None:
    return (
        await session.execute(
            select(Product)
            .join(Marketplace, Marketplace.id == Product.marketplace_id)
            .where(
                Product.organization_id == ctx.organization_id,
                Marketplace.code == marketplace,
                Product.external_id == asin,
                Product.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


@router.get("/lookup", response_model=LookupResult)
async def lookup(
    request: Request,
    session: SessionDep,
    ctx: ExtensionDep,
    id: Annotated[str, Query(min_length=1, max_length=2000, description="ASIN or page URL")],
    marketplace: MarketplaceCode = MarketplaceCode.AMAZON_IN,
) -> LookupResult:
    """What SellerScope already stored for this product (no marketplace call)."""
    _require_scope(ctx, SCOPE_READ)
    await _per_token(request, ctx, "extension-lookup", 1200)
    asin = _parse(marketplace, id)
    web = request.app.state.settings.web_base_url
    can_check = SCOPE_CHECK in ctx.scopes and ctx.can(Permission.SCANS_RUN)
    product = await _product(session, ctx, marketplace, asin)
    if product is None:
        return LookupResult(
            marketplace=marketplace,
            identifier=asin,
            tracked=False,
            product=None,
            latest=None,
            last_attempt=None,
            active_scan=None,
            can_check=False,
            dashboard_url=f"{web}/products?q={quote(asin)}",
        )
    org = ctx.organization_id
    latest = None
    if product.latest_scan_result_id:
        r = (
            await session.execute(
                select(ScanResult).where(
                    ScanResult.organization_id == org,
                    ScanResult.id == product.latest_scan_result_id,
                )
            )
        ).scalar_one()
        usable = r.status in USABLE
        latest = LookupSnapshot(
            status=r.status,
            data_source=r.data_source,
            is_mock=Limitation.MOCK_DATA in r.limitations or r.data_source == "MOCK",
            retrieved_at=r.retrieved_at,
            total_offer_count=r.total_offer_count if usable else None,
            observed_offer_count=r.observed_offer_count if usable else None,
            unique_seller_count=r.unique_seller_count if usable else None,
            is_offer_list_truncated=r.is_offer_list_truncated if usable else None,
            lowest_observed_price=r.lowest_observed_price if usable else None,
            highest_observed_price=r.highest_observed_price if usable else None,
            buy_box_price=r.buy_box_price if usable else None,
            currency=r.currency if usable else None,
            limitations=list(r.limitations),
        )
    attempt = (
        await session.execute(
            select(ScanResult.status, ScanResult.error_code, ScanResult.retrieved_at)
            .where(ScanResult.organization_id == org, ScanResult.product_id == product.id)
            .order_by(ScanResult.retrieved_at.desc(), ScanResult.id.desc())
            .limit(1)
        )
    ).one_or_none()
    active = (
        await session.execute(
            select(ScanJobItem.scan_job_id, ScanJob.status)
            .join(
                ScanJob,
                and_(
                    ScanJob.id == ScanJobItem.scan_job_id,
                    ScanJob.organization_id == ScanJobItem.organization_id,
                ),
            )
            .where(
                ScanJobItem.organization_id == org,
                ScanJobItem.product_id == product.id,
                ScanJobItem.status.in_((ScanItemStatus.PENDING, ScanItemStatus.PROCESSING)),
            )
            .limit(1)
        )
    ).one_or_none()
    return LookupResult(
        marketplace=marketplace,
        identifier=asin,
        tracked=True,
        product=LookupProduct.model_validate(product),
        latest=latest,
        last_attempt=LookupAttempt(status=attempt[0], error_code=attempt[1], at=attempt[2])
        if attempt
        else None,
        active_scan=ActiveScan(job_id=active[0], status=active[1]) if active else None,
        can_check=can_check,
        dashboard_url=f"{web}/products/{product.id}",
    )


@router.post("/check", response_model=CheckStarted, status_code=status.HTTP_202_ACCEPTED)
async def check_now(
    body: CheckRequest, request: Request, session: SessionDep, ctx: ExtensionDep
) -> CheckStarted:
    """Queues a normal scan through the authorized connector (plan quota applies)."""
    _require_scope(ctx, SCOPE_CHECK)
    if not ctx.can(Permission.SCANS_RUN):
        raise AppError(403, "forbidden", "Forbidden", f"Your role ({ctx.role}) can't start scans.")
    await _per_token(request, ctx, "extension-check", 60)
    asin = _parse(body.marketplace, body.id)
    product = await _product(session, ctx, body.marketplace, asin)
    if product is None:
        raise AppError(
            404,
            "product_not_tracked",
            "Not in your products",
            "Add this product in SellerScope before checking it.",
        )
    registry: ConnectorRegistry = request.app.state.connector_registry
    try:
        await registry.resolve(session, ctx.organization_id, body.marketplace)
    except ConnectorUnavailableError as exc:
        raise AppError(409, "connector_unavailable", "Scanning not available", exc.reason) from exc
    created = await create_scan_job(
        session,
        organization_id=ctx.organization_id,
        requested_by=ctx.user_id,
        product_ids=[product.id],
        trigger=ScanTrigger.EXTENSION,
        now=utcnow(),
    )
    if created.already_running:
        raise AppError(
            409, "already_scanning", "Already being checked", "A scan of this product is running."
        )
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        actor_type=ActorType.EXTENSION,
        action="scan.start",
        entity_type="scan_job",
        entity_id=created.job.id,
        request=request,
        details={"products": 1, "extension_token_id": ctx.token_id},
    )
    job_id, job_status = created.job.id, created.job.status
    await session.commit()
    dispatcher: TaskDispatcher = request.app.state.task_dispatcher
    await dispatcher.run_scan_job(ctx.organization_id, job_id)
    return CheckStarted(job_id=job_id, status=job_status)


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(request: Request, session: SessionDep, ctx: ExtensionDep) -> None:
    """The extension's "Disconnect": revokes its own token."""
    await _revoke(session, ctx.organization_id, ctx.token_id)
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        actor_type=ActorType.EXTENSION,
        action="extension.disconnect",
        entity_type="extension_token",
        entity_id=ctx.token_id,
        request=request,
    )
    await session.commit()


async def _revoke(session: SessionDep, org: uuid.UUID, token_id: uuid.UUID) -> None:
    await session.execute(
        update(ExtensionToken)
        .where(
            ExtensionToken.organization_id == org,
            ExtensionToken.id == token_id,
            ExtensionToken.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )


# ------------------------------------------------------------------------------ web: devices


@router.get("/tokens", response_model=list[ExtensionTokenOut])
async def list_tokens(session: SessionDep, ctx: OrgDep) -> list[ExtensionTokenOut]:
    """Connected browsers. Members see their own; admins see everyone's."""
    stmt = (
        select(ExtensionToken, User.email)
        .outerjoin(User, User.id == ExtensionToken.user_id)
        .where(ExtensionToken.organization_id == ctx.organization_id)
        .order_by(ExtensionToken.created_at.desc(), ExtensionToken.id.desc())
    )
    if not ctx.can(Permission.MEMBERS_MANAGE):
        stmt = stmt.where(ExtensionToken.user_id == ctx.user_id)
    return [
        ExtensionTokenOut(
            id=t.id,
            name=t.name,
            user_id=t.user_id,
            user_email=email,
            scopes=t.scopes,
            created_at=t.created_at,
            last_used_at=t.last_used_at,
            expires_at=t.expires_at,
            revoked_at=t.revoked_at,
            is_current_user=t.user_id == ctx.user_id,
        )
        for t, email in (await session.execute(stmt)).all()
    ]


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: uuid.UUID, request: Request, session: SessionDep, ctx: OrgDep
) -> None:
    token = (
        await session.execute(
            select(ExtensionToken).where(
                ExtensionToken.organization_id == ctx.organization_id,
                ExtensionToken.id == token_id,
            )
        )
    ).scalar_one_or_none()
    if token is None or (token.user_id != ctx.user_id and not ctx.can(Permission.MEMBERS_MANAGE)):
        raise not_found("Connected browser")
    await _revoke(session, ctx.organization_id, token.id)
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="extension.revoke",
        entity_type="extension_token",
        entity_id=token.id,
        request=request,
        details={"owner_user_id": token.user_id},
    )
    await session.commit()
