"""M2 acceptance tests: schema, tenant isolation (RLS), append-only snapshots, constraints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from sellerscope.core.ids import uuid7
from sellerscope.db.base import Base
from sellerscope.models import (
    APPEND_ONLY_TABLES,
    Organization,
    OrganizationMember,
    Product,
    ScanJob,
    ScanJobItem,
    ScanResult,
    User,
)
from tests.integration.conftest import APP_ROLE, add, marketplace_id, run_alembic, set_ctx

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


# --------------------------------------------------------------------------- helpers


async def make_org(conn: AsyncConnection, name: str = "Org") -> uuid.UUID:
    return await add(conn, Organization.__table__, name=name, slug=f"{name}-{uuid7().hex[:12]}")


async def make_user(conn: AsyncConnection) -> uuid.UUID:
    uid = uuid.uuid4()
    await add(conn, User.__table__, id=uid, email=f"{uid.hex}@example.test")
    return uid


async def make_product(conn: AsyncConnection, org: uuid.UUID, asin: str | None = None) -> uuid.UUID:
    return await add(
        conn,
        Product.__table__,
        organization_id=org,
        marketplace_id=await marketplace_id(conn),
        external_id=asin or f"B0{uuid7().hex[-8:].upper()}",
    )


async def make_scan_item(
    conn: AsyncConnection, org: uuid.UUID, product: uuid.UUID, status: str = "pending"
) -> uuid.UUID:
    job = await add(conn, ScanJob.__table__, organization_id=org, trigger="manual")
    return await add(
        conn,
        ScanJobItem.__table__,
        organization_id=org,
        scan_job_id=job,
        product_id=product,
        status=status,
    )


async def make_scan_result(conn: AsyncConnection, org: uuid.UUID) -> uuid.UUID:
    product = await make_product(conn, org)
    item = await make_scan_item(conn, org, product, status="completed")
    return await add(
        conn,
        ScanResult.__table__,
        organization_id=org,
        scan_job_item_id=item,
        product_id=product,
        status="ok",
        data_source="test-fixture",
        total_offer_count=3,
        observed_offer_count=3,
        unique_seller_count=2,
        lowest_observed_price=Decimal("10.00"),
        highest_observed_price=Decimal("12.50"),
        currency="INR",
        retrieved_at=NOW,
    )


# --------------------------------------------------------------------------- migrations


async def test_migrations_downgrade_to_base_and_upgrade_again(owner_engine: AsyncEngine) -> None:
    # Downgrading past the seed migration is only possible with no customer data (a trial plan
    # in use by subscriptions must not be deleted), so start from empty tables.
    async with owner_engine.begin() as conn:
        await conn.execute(text("TRUNCATE users, organizations CASCADE"))
    await run_alembic("downgrade", "base")
    async with owner_engine.connect() as conn:
        tables = (
            await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name <> 'alembic_version'"
                )
            )
        ).all()
    assert tables == []
    await run_alembic("upgrade", "head")
    async with owner_engine.connect() as conn:
        count = (
            await conn.execute(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
            )
        ).scalar_one()
    assert count == len(Base.metadata.tables) + 1  # + alembic_version


async def test_models_and_migrations_are_in_sync(owner_engine: AsyncEngine) -> None:
    def diff(sync_conn: object) -> list[object]:
        ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True})  # type: ignore[arg-type]
        return list(compare_metadata(ctx, Base.metadata))

    async with owner_engine.connect() as conn:
        differences = await conn.run_sync(diff)
    assert differences == []


async def test_seed_reference_data(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT external_marketplace_id, currency, identifier_label "
                    "FROM marketplaces WHERE code = 'amazon_in'"
                )
            )
        ).one()
        assert tuple(row) == ("A21TJRUUN4KGV", "INR", "ASIN")
        codes = (await conn.execute(text("SELECT code FROM marketplaces"))).scalars().all()
        assert codes == ["amazon_in"]  # Amazon-only scope
        plan = (
            await conn.execute(text("SELECT features FROM plans WHERE code = 'trial'"))
        ).scalar_one()
        assert plan == {"provisional": True}


# --------------------------------------------------------------------------- role & RLS setup


async def test_every_tenant_table_has_rls_and_a_policy(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        tenant_tables = set(
            (
                await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.columns "
                        "WHERE table_schema='public' AND column_name='organization_id'"
                    )
                )
            ).scalars()
        )
        rows = (
            await conn.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, "
                    "(SELECT count(*) FROM pg_policies p WHERE p.tablename = c.relname) "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname='public' AND c.relkind='r'"
                )
            )
        ).all()
    state = {name: (rls, policies) for name, rls, policies in rows}
    assert len(tenant_tables) == 18
    for table in tenant_tables | {"users", "organizations"}:
        rls, policies = state[table]
        assert rls, f"RLS not enabled on {table}"
        assert policies > 0, f"No RLS policy on {table}"


async def test_app_role_is_restricted(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        role = (
            await conn.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :r"),
                {"r": APP_ROLE},
            )
        ).one()
        assert tuple(role) == (False, False)
        owned = (
            await conn.execute(
                text("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner=:r"),
                {"r": APP_ROLE},
            )
        ).scalar_one()
        assert owned == 0
        for table in APPEND_ONLY_TABLES:
            for priv in ("UPDATE", "DELETE", "TRUNCATE"):
                has = (
                    await conn.execute(
                        text("SELECT has_table_privilege(:r, :t, :p)"),
                        {"r": APP_ROLE, "t": table, "p": priv},
                    )
                ).scalar_one()
                assert not has, f"{APP_ROLE} must not have {priv} on {table}"
        for table in ("marketplaces", "plans"):
            has = (
                await conn.execute(
                    text("SELECT has_table_privilege(:r, :t, 'INSERT')"),
                    {"r": APP_ROLE, "t": table},
                )
            ).scalar_one()
            assert not has


# --------------------------------------------------------------------------- tenant isolation


async def test_rls_isolates_products_between_organizations(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        org_a, org_b = await make_org(conn, "a"), await make_org(conn, "b")
        prod_a = await make_product(conn, org_a)
        prod_b = await make_product(conn, org_b)

    async with app_engine.begin() as conn:
        await set_ctx(conn, org_a, None)
        # No WHERE clause on purpose: RLS alone must filter.
        visible = set((await conn.execute(text("SELECT id FROM products"))).scalars())
        assert prod_a in visible
        assert prod_b not in visible
        # Updating another org's row affects nothing.
        res = await conn.execute(
            text("UPDATE products SET product_name = 'hijack' WHERE id = :id"), {"id": prod_b}
        )
        assert res.rowcount == 0  # type: ignore[attr-defined]

    async with app_engine.begin() as conn:
        await set_ctx(conn, None, None)
        assert (await conn.execute(text("SELECT count(*) FROM products"))).scalar_one() == 0


async def test_rls_rejects_inserting_rows_for_another_organization(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        org_a, org_b = await make_org(conn, "a"), await make_org(conn, "b")
        mkt = await marketplace_id(conn)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with app_engine.begin() as conn:
            await set_ctx(conn, org_a, None)
            await add(
                conn,
                Product.__table__,
                organization_id=org_b,
                marketplace_id=mkt,
                external_id="B0ABCDEFGH",
            )


async def test_tenant_context_does_not_leak_across_transactions(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        org = await make_org(conn)
        await make_product(conn, org)
    async with app_engine.connect() as conn:
        async with conn.begin():
            await set_ctx(conn, org, None)
            assert (await conn.execute(text("SELECT count(*) FROM products"))).scalar_one() == 1
        async with conn.begin():  # same pooled connection, new transaction
            assert (await conn.execute(text("SELECT count(*) FROM products"))).scalar_one() == 0


async def test_user_sees_own_memberships_across_orgs_but_not_others(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        org_a = await make_org(conn, "a")
        org_b = await make_org(conn, "b")
        org_c = await make_org(conn, "c")
        alice, bob = await make_user(conn), await make_user(conn)
        for org in (org_a, org_b):
            await add(
                conn, OrganizationMember.__table__, organization_id=org, user_id=alice, role="admin"
            )
        await add(
            conn, OrganizationMember.__table__, organization_id=org_c, user_id=bob, role="owner"
        )

    async with app_engine.begin() as conn:
        await set_ctx(conn, None, alice)  # no org selected yet: org switcher
        orgs = set((await conn.execute(text("SELECT id FROM organizations"))).scalars())
        assert orgs == {org_a, org_b}
        users = set((await conn.execute(text("SELECT id FROM users"))).scalars())
        assert users == {alice}

    async with app_engine.begin() as conn:
        await set_ctx(conn, org_c, bob)
        users = set((await conn.execute(text("SELECT id FROM users"))).scalars())
        assert users == {bob}
        members = (await conn.execute(text("SELECT user_id FROM organization_members"))).scalars()
        assert set(members) == {bob}


async def test_user_cannot_add_membership_to_another_org(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        org_a, org_b = await make_org(conn, "a"), await make_org(conn, "b")
        mallory = await make_user(conn)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with app_engine.begin() as conn:
            await set_ctx(conn, org_a, mallory)
            await add(
                conn,
                OrganizationMember.__table__,
                organization_id=org_b,
                user_id=mallory,
                role="owner",
            )


async def test_composite_fk_blocks_cross_tenant_references(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        org_a, org_b = await make_org(conn, "a"), await make_org(conn, "b")
        prod_b = await make_product(conn, org_b)
    with pytest.raises(IntegrityError, match="foreign key"):
        async with owner_engine.begin() as conn:  # even the owner (no RLS) is blocked
            await make_scan_item(conn, org_a, prod_b)


# --------------------------------------------------------------------------- append-only


async def test_app_role_cannot_update_or_delete_snapshots(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        org = await make_org(conn)
        result = await make_scan_result(conn, org)
    for stmt in (
        "UPDATE scan_results SET total_offer_count = 99 WHERE id = :id",
        "DELETE FROM scan_results WHERE id = :id",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with app_engine.begin() as conn:
                await set_ctx(conn, org, None)
                await conn.execute(text(stmt), {"id": result})


async def test_trigger_blocks_snapshot_updates_even_for_owner(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        org = await make_org(conn)
        result = await make_scan_result(conn, org)
    with pytest.raises(DBAPIError, match="append-only"):
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE scan_results SET total_offer_count = 99 WHERE id = :id"),
                {"id": result},
            )
    with pytest.raises(DBAPIError, match="append-only"):
        async with owner_engine.begin() as conn:
            await conn.execute(text("DELETE FROM scan_results WHERE id = :id"), {"id": result})
    # Explicit retention purge is the only way to delete.
    async with owner_engine.begin() as conn:
        await conn.execute(text("SET LOCAL app.retention_purge = 'on'"))
        res = await conn.execute(text("DELETE FROM scan_results WHERE id = :id"), {"id": result})
        assert res.rowcount == 1  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- constraints


async def test_duplicate_live_product_rejected_but_soft_deleted_allows_readd(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.begin() as conn:
        org = await make_org(conn)
        first = await make_product(conn, org, "B0DUPL1234")
    with pytest.raises(IntegrityError, match="uq_products_org_marketplace_external_id_live"):
        async with owner_engine.begin() as conn:
            await make_product(conn, org, "B0DUPL1234")
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE products SET deleted_at = now() WHERE id = :id"), {"id": first}
        )
        await make_product(conn, org, "B0DUPL1234")
        other_org = await make_org(conn)
        await make_product(conn, other_org, "B0DUPL1234")  # same ASIN, other tenant: fine


async def test_only_one_active_scan_per_product(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        org = await make_org(conn)
        product = await make_product(conn, org)
        await make_scan_item(conn, org, product, status="completed")
        await make_scan_item(conn, org, product, status="pending")
    with pytest.raises(IntegrityError, match="uq_scan_job_items_product_active"):
        async with owner_engine.begin() as conn:
            await make_scan_item(conn, org, product, status="processing")


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("unique_seller_count", 5, "unique_sellers_valid"),  # > observed (3)
        ("total_offer_count", -1, "total_offers_valid"),
        ("status", "bogus", "status_valid"),
        ("lowest_observed_price", Decimal("99.00"), "price_range_valid"),  # > highest
        ("currency", None, "prices_have_currency"),
    ],
)
async def test_scan_result_check_constraints(
    owner_engine: AsyncEngine, field: str, value: object, constraint: str
) -> None:
    async with owner_engine.begin() as conn:
        org = await make_org(conn)
        product = await make_product(conn, org)
        item = await make_scan_item(conn, org, product, status="completed")
    values: dict[str, object] = {
        "organization_id": org,
        "scan_job_item_id": item,
        "product_id": product,
        "status": "ok",
        "data_source": "test-fixture",
        "total_offer_count": 3,
        "observed_offer_count": 3,
        "unique_seller_count": 2,
        "lowest_observed_price": Decimal("10.00"),
        "highest_observed_price": Decimal("12.50"),
        "currency": "INR",
        "retrieved_at": NOW,
        field: value,
    }
    with pytest.raises(IntegrityError, match=constraint):
        async with owner_engine.begin() as conn:
            await add(conn, ScanResult.__table__, **values)


async def test_unknown_metrics_are_stored_as_null_not_zero(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        org = await make_org(conn)
        product = await make_product(conn, org)
        item = await make_scan_item(conn, org, product, status="unavailable")
        rid = await add(
            conn,
            ScanResult.__table__,
            organization_id=org,
            scan_job_item_id=item,
            product_id=product,
            status="unavailable",
            data_source="test-fixture",
            retrieved_at=NOW,
        )
        row = (
            await conn.execute(
                text(
                    "SELECT total_offer_count, unique_seller_count, lowest_observed_price, "
                    "observed_offer_count FROM scan_results WHERE id = :id"
                ),
                {"id": rid},
            )
        ).one()
    assert tuple(row) == (None, None, None, 0)


async def test_lowercase_asin_rejected(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        org = await make_org(conn)
    with pytest.raises(IntegrityError, match="external_id_normalized"):
        async with owner_engine.begin() as conn:
            await make_product(conn, org, "b0lower123")


async def test_updated_at_trigger(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        org = await make_org(conn)
        product = await make_product(conn, org)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE products SET product_name = 'x' WHERE id = :id"), {"id": product}
        )
        created, updated = (
            await conn.execute(
                text("SELECT created_at, updated_at FROM products WHERE id = :id"), {"id": product}
            )
        ).one()
    assert updated > created
