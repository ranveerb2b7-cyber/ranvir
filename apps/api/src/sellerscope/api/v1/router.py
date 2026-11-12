from fastapi import APIRouter

from sellerscope.api.v1 import (
    alerts,
    dashboard,
    extension,
    health,
    intel,
    invitations,
    me,
    meta,
    organizations,
    products,
    reports,
    scans,
    uploads,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(me.router)
api_router.include_router(organizations.router)
api_router.include_router(invitations.router)
api_router.include_router(products.router)
api_router.include_router(dashboard.router)
api_router.include_router(uploads.router)
api_router.include_router(scans.router)
api_router.include_router(meta.router)
api_router.include_router(intel.router)
api_router.include_router(alerts.router)
api_router.include_router(reports.router)
api_router.include_router(extension.router)
