# 4. Project Folder Structure (monorepo)

Status: **PROPOSAL — awaiting approval.**

```
sellerscope/  (repo: ranvir)
├── README.md
├── CLAUDE.md                      # conventions for AI-assisted development
├── .env.example                   # every variable, no real values
├── .gitignore  .editorconfig  .pre-commit-config.yaml
├── docker-compose.yml             # postgres, redis, minio, mailpit, supabase-auth, api, worker, beat, web
├── docker-compose.test.yml
├── Makefile                       # make dev | test | lint | migrate | gen-client
├── pnpm-workspace.yaml  package.json
├── .github/workflows/ci.yml
│
├── apps/
│   ├── api/                       # FastAPI + Celery (one Python package, two entrypoints)
│   │   ├── pyproject.toml  uv.lock  Dockerfile
│   │   ├── alembic.ini
│   │   ├── migrations/            # Alembic versions (incl. RLS policies, grants)
│   │   ├── src/sellerscope/
│   │   │   ├── main.py            # FastAPI app factory
│   │   │   ├── core/              # config (pydantic-settings), logging, security, crypto, errors, rate_limit
│   │   │   ├── db/                # engine, session, tenant context (SET LOCAL), base model
│   │   │   ├── auth/              # JWT verification (Supabase JWKS), current user, RBAC permissions
│   │   │   ├── models/            # SQLAlchemy ORM models (one module per aggregate)
│   │   │   ├── schemas/           # Pydantic request/response models
│   │   │   ├── api/v1/            # routers: auth, orgs, members, products, uploads, scans,
│   │   │   │                      #   sellers, history, alerts, reports, connections, extension, billing
│   │   │   ├── services/          # business logic (products, uploads, scanning, diff, alerts, reports)
│   │   │   ├── repositories/      # tenant-scoped data access
│   │   │   ├── connectors/
│   │   │   │   ├── base.py        # MarketplaceConnector protocol, capabilities, OfferSnapshot
│   │   │   │   ├── registry.py
│   │   │   │   ├── identifiers.py # ASIN / FSN format validation
│   │   │   │   ├── amazon/        # lwa.py, client.py, pricing.py, catalog.py, parser.py, errors.py
│   │   │   │   ├── flipkart/      # client.py, capabilities.py, parser.py (limited; see report)
│   │   │   │   └── mock/          # dev/test only, refuses to load in production
│   │   │   ├── workers/           # celery_app.py, beat schedule, tasks/{scans,imports,reports,alerts}.py
│   │   │   └── storage/           # S3 abstraction
│   │   └── tests/
│   │       ├── unit/  integration/  tenancy/   # tenancy = cross-org isolation suite
│   │       └── fixtures/           # scrubbed recorded API responses
│   │
│   ├── web/                       # Next.js 15 dashboard
│   │   ├── package.json  next.config.ts  tailwind.config.ts  Dockerfile
│   │   ├── src/
│   │   │   ├── app/
│   │   │   │   ├── (auth)/login | register | forgot-password | reset-password | accept-invite
│   │   │   │   └── (app)/dashboard | upload | products | sellers | history | alerts
│   │   │   │              | reports | team | settings/{organization,connections,billing,extension}
│   │   │   ├── components/        # ui/ (shadcn), data-table/, charts/, layout/, metrics/
│   │   │   ├── lib/               # api client (generated), supabase client, auth, formatting
│   │   │   └── hooks/
│   │   └── tests/                 # vitest + Playwright e2e
│   │
│   └── extension/                 # Chrome MV3 (TypeScript, Vite build)
│       ├── manifest.json
│       ├── src/background/        # service worker: auth token storage, API calls
│       ├── src/content/           # URL-based ASIN/FSN detection only
│       ├── src/popup/             # UI: stored data, timestamp, "Check now", dashboard link
│       └── tests/
│
├── packages/
│   ├── api-client/                # generated TS types from OpenAPI (shared by web + extension)
│   └── config/                    # shared eslint / tsconfig / prettier
│
├── infra/
│   ├── docker/                    # postgres init (roles: owner, app), minio bootstrap
│   └── deploy/                    # IaC (Terraform), added at the deployment milestone
│
└── docs/
    ├── plan/                      # these planning documents
    ├── adr/                       # architecture decision records
    ├── api.md                     # generated endpoint reference + conventions
    ├── connectors/amazon.md  flipkart.md   # live capability/limitation register
    └── runbooks/                  # credential rotation, incident, rate-limit tuning
```
