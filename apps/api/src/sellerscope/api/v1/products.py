"""Product management (Amazon.in ASINs)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from sellerscope.auth.deps import OrgContext, OrgDep, SessionDep, require
from sellerscope.auth.permissions import Permission
from sellerscope.connectors.identifiers import (
    ERROR_MESSAGES,
    WARNING_MESSAGES,
    parse_identifier,
)
from sellerscope.core.errors import AppError, not_found
from sellerscope.core.ids import uuid7
from sellerscope.models import Product
from sellerscope.schemas.products import (
    BrandCount,
    BulkAction,
    BulkResult,
    IdentifierCheckBatch,
    IdentifierCheckOut,
    ProductCreate,
    ProductOut,
    ProductPage,
    ProductUpdate,
    ScanStatus,
    SortField,
)
from sellerscope.services import audit
from sellerscope.services.products import (
    ProductFilters,
    apply_filters,
    apply_sort,
    base_query,
    clean_text,
    ensure_product_quota,
    existing_products,
    get_product_out,
    marketplace_by_code,
    to_out,
)

router = APIRouter(tags=["products"])
WriteProducts = Annotated[OrgContext, Depends(require(Permission.PRODUCTS_WRITE))]


@router.get("/products", response_model=ProductPage)
async def list_products(
    session: SessionDep,
    ctx: OrgDep,
    q: Annotated[
        str | None, Query(max_length=200, description="ASIN prefix, name or brand")
    ] = None,
    marketplace: Annotated[str | None, Query(max_length=40)] = None,
    brand: Annotated[
        str | None, Query(max_length=120, description="Exact brand; `__none__` = no brand")
    ] = None,
    scan_status: ScanStatus | None = None,
    multiple_sellers: Annotated[
        bool | None, Query(description="Products with unknown seller counts match neither value")
    ] = None,
    monitoring: bool | None = None,
    sort: SortField = "created_at",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> ProductPage:
    filters = ProductFilters(q, marketplace, brand, scan_status, multiple_sellers, monitoring)
    filtered = apply_filters(base_query(ctx.organization_id), filters)
    total = (
        await session.execute(select(func.count()).select_from(filtered.subquery()))
    ).scalar_one()
    rows = (
        await session.execute(
            apply_sort(filtered, sort, order == "desc")
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).all()
    return ProductPage(
        items=[to_out(*row) for row in rows], total=total, page=page, page_size=page_size
    )


@router.post(
    "/products/validate",
    response_model=list[IdentifierCheckOut],
    summary="Check identifiers (format + duplicates) without saving",
)
async def validate_identifiers(
    body: IdentifierCheckBatch, session: SessionDep, ctx: OrgDep
) -> list[IdentifierCheckOut]:
    results = [(item, parse_identifier(item.marketplace, item.identifier)) for item in body.items]
    existing: dict[tuple[str, str], uuid.UUID] = {}
    for code in {item.marketplace for item in body.items}:
        marketplace = await marketplace_by_code(session, code)
        found = await existing_products(
            session,
            ctx.organization_id,
            marketplace.id,
            [r.normalized for i, r in results if i.marketplace == code and r.normalized],
        )
        existing.update({(code, ext): pid for ext, pid in found.items()})
    return [
        IdentifierCheckOut(
            input=item.identifier,
            normalized=r.normalized,
            valid=r.valid,
            error=r.error,
            message=ERROR_MESSAGES[r.error] if r.error else None,
            warnings=list(r.warnings),
            warning_messages=[WARNING_MESSAGES[w] for w in r.warnings],
            existing_product_id=existing.get((item.marketplace, r.normalized or "")),
        )
        for item, r in results
    ]


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    body: ProductCreate, request: Request, session: SessionDep, ctx: WriteProducts
) -> ProductOut:
    parsed = parse_identifier(body.marketplace, body.identifier)
    if not parsed.valid or parsed.normalized is None:
        assert parsed.error is not None
        raise AppError(
            422,
            "identifier_invalid",
            "Invalid identifier",
            ERROR_MESSAGES[parsed.error],
            extra={"reason": parsed.error},
        )
    marketplace = await marketplace_by_code(session, body.marketplace)
    duplicate = (
        await existing_products(session, ctx.organization_id, marketplace.id, [parsed.normalized])
    ).get(parsed.normalized)
    if duplicate:
        raise AppError(
            409,
            "product_exists",
            "Already added",
            f"{parsed.normalized} is already in your products.",
            extra={"existing_product_id": str(duplicate)},
        )
    await ensure_product_quota(session, ctx.organization_id, 1)

    product = Product(
        id=uuid7(),
        organization_id=ctx.organization_id,
        marketplace_id=marketplace.id,
        external_id=parsed.normalized,
        product_name=clean_text(body.product_name),
        brand_name=clean_text(body.brand_name),
        created_by=ctx.user_id,
    )
    session.add(product)
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="product.create",
        entity_type="product",
        entity_id=product.id,
        request=request,
        details={"external_id": parsed.normalized, "marketplace": body.marketplace},
    )
    try:
        await session.flush()
    except IntegrityError as exc:  # concurrent insert of the same ASIN
        await session.rollback()
        raise AppError(
            409,
            "product_exists",
            "Already added",
            f"{parsed.normalized} is already in your products.",
        ) from exc
    out = await get_product_out(session, ctx.organization_id, product.id)
    assert out is not None
    await session.commit()
    return out


@router.post("/products/bulk", response_model=BulkResult)
async def bulk_update(
    body: BulkAction, request: Request, session: SessionDep, ctx: WriteProducts
) -> BulkResult:
    if body.action == "set_brand" and "brand_name" not in body.model_fields_set:
        raise AppError(422, "brand_required", "brand_name is required for set_brand")
    ids = list(dict.fromkeys(body.ids))
    products = (
        (
            await session.execute(
                select(Product).where(
                    Product.organization_id == ctx.organization_id,
                    Product.id.in_(ids),
                    Product.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    found = {p.id for p in products}
    now = datetime.now(UTC)
    for product in products:
        if body.action == "delete":
            product.deleted_at = now
        elif body.action == "enable_monitoring":
            product.monitoring_enabled = True
        elif body.action == "disable_monitoring":
            product.monitoring_enabled = False
        else:
            product.brand_name = clean_text(body.brand_name)
    if products:
        audit.record(
            session,
            organization_id=ctx.organization_id,
            actor_user_id=ctx.user_id,
            action=f"product.bulk_{body.action}",
            entity_type="product",
            request=request,
            details={"count": len(products), "ids": [str(i) for i in list(found)[:100]]},
        )
    await session.commit()
    return BulkResult(affected=len(products), not_found=[i for i in ids if i not in found])


@router.get("/products/{product_id}", response_model=ProductOut)
async def get_product(product_id: uuid.UUID, session: SessionDep, ctx: OrgDep) -> ProductOut:
    out = await get_product_out(session, ctx.organization_id, product_id)
    if out is None:
        raise not_found("Product")
    return out


async def _live_product(session: SessionDep, ctx: OrgContext, product_id: uuid.UUID) -> Product:
    product = (
        await session.execute(
            select(Product).where(
                Product.id == product_id,
                Product.organization_id == ctx.organization_id,
                Product.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if product is None:
        raise not_found("Product")
    return product


@router.patch("/products/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: uuid.UUID,
    body: ProductUpdate,
    request: Request,
    session: SessionDep,
    ctx: WriteProducts,
) -> ProductOut:
    product = await _live_product(session, ctx, product_id)
    changes: dict[str, object] = {}
    for field in ("product_name", "brand_name"):
        if field in body.model_fields_set:
            value = clean_text(getattr(body, field))
            if value != getattr(product, field):
                changes[field] = value
                setattr(product, field, value)
    if (
        body.monitoring_enabled is not None
        and body.monitoring_enabled != product.monitoring_enabled
    ):
        changes["monitoring_enabled"] = body.monitoring_enabled
        product.monitoring_enabled = body.monitoring_enabled
    if changes:
        audit.record(
            session,
            organization_id=ctx.organization_id,
            actor_user_id=ctx.user_id,
            action="product.update",
            entity_type="product",
            entity_id=product.id,
            request=request,
            details=changes,
        )
    await session.flush()
    out = await get_product_out(session, ctx.organization_id, product.id)
    assert out is not None
    await session.commit()
    return out


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: uuid.UUID, request: Request, session: SessionDep, ctx: WriteProducts
) -> Response:
    """Soft delete: the product leaves all lists; its scan history is retained."""
    product = await _live_product(session, ctx, product_id)
    product.deleted_at = datetime.now(UTC)
    audit.record(
        session,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="product.delete",
        entity_type="product",
        entity_id=product.id,
        request=request,
        details={"external_id": product.external_id},
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/brands", response_model=list[BrandCount])
async def list_brands(session: SessionDep, ctx: OrgDep) -> list[BrandCount]:
    rows = (
        await session.execute(
            select(Product.brand_name, func.count())
            .where(Product.organization_id == ctx.organization_id, Product.deleted_at.is_(None))
            .group_by(Product.brand_name)
            .order_by(Product.brand_name.asc().nulls_last())
        )
    ).all()
    return [BrandCount(brand_name=b, products=n) for b, n in rows]
