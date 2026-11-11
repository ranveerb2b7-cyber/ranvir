# SellerScope

Marketplace seller mapping and intelligence SaaS for brand owners and manufacturers. It monitors the sellers offering their products on **Amazon India** and **Flipkart**.

## Current status

**Milestone 0 (planning).** Only design documents exist so far. See [`docs/plan/`](docs/plan/README.md). No application code has been written, and no features are complete.

## Coverage statement

- **Amazon.in:** planned via the official Selling Partner API. It reports total offer count and up to ~20 individual offers per ASIN. Seller names are not provided by the API. *(Pending verification with live credentials.)*
- **Flipkart:** no authorized API currently known to provide competitor seller/offer data. Flipkart seller mapping is **not** offered unless an authorized data source becomes available. See the [feasibility report](docs/plan/07-flipkart-feasibility.md).

SellerScope never fabricates seller counts, prices or seller identities. Unavailable data is shown as unavailable.

## Planned stack

Next.js + TypeScript + Tailwind · FastAPI + SQLAlchemy + PostgreSQL · Celery + Redis · Supabase Auth · Chrome MV3 extension · Docker.
