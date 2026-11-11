# SellerScope — Planning Documents (Milestone 0)

Status: **Approved 2026-11-11 with scope changes (see Decisions log).**

1. [System architecture](01-architecture.md)
2. [Technical implementation plan](02-implementation-plan.md)
3. [Database ER design](03-database-design.md)
4. [Project folder structure](04-folder-structure.md)
5. [API endpoint plan](05-api-endpoints.md)
6. [Amazon integration feasibility](06-amazon-feasibility.md)
7. [Flipkart integration feasibility](07-flipkart-feasibility.md)
8. [Development milestones](08-milestones.md)
9. [Security & compliance](09-security-compliance.md)

## Decisions log

| Date | Decision |
|---|---|
| 2026-11-11 | **Amazon.in only for now.** Flipkart (milestone M9 and Flipkart parts of other milestones) is deferred. The connector interface stays marketplace-agnostic so Flipkart can be added later without reworking the engine. |
| 2026-11-11 | **Target customers are Amazon.in sellers with Seller Central accounts.** Each organization connects its own seller account (feasibility §6.4 options A/B). Option C (one shared SellerScope account) is rejected. |
| 2026-11-11 | **Auth:** hosted Supabase Auth (Mumbai region) for staging/production; self-hosted GoTrue container in docker-compose for local development (approved). Billing provider decided at M13. |
| 2026-11-11 | **Web data fetching:** TanStack Query, as listed in the architecture, adopted in M3. |
