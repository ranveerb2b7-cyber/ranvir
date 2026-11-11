"""The application's tenant-context helper drives RLS through an ORM session."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from sellerscope.db.tenant import set_tenant_context
from sellerscope.models import Product
from tests.integration.test_schema import make_org, make_product

pytestmark = pytest.mark.integration


async def test_set_tenant_context_scopes_orm_queries(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        org_a, org_b = await make_org(conn, "a"), await make_org(conn, "b")
        for _ in range(2):
            await make_product(conn, org_a)
        await make_product(conn, org_b)

    sessions = async_sessionmaker(app_engine)
    async with sessions() as session, session.begin():
        await set_tenant_context(session, organization_id=org_a, user_id=None)
        orgs = (await session.execute(select(Product.organization_id).distinct())).scalars().all()
        assert orgs == [org_a]
        count = (await session.execute(select(func.count()).select_from(Product))).scalar_one()
        assert count == 2

    async with sessions() as session, session.begin():
        await set_tenant_context(session, organization_id=None, user_id=None)
        count = (await session.execute(select(func.count()).select_from(Product))).scalar_one()
        assert count == 0
