from fastapi import APIRouter

from sellerscope.api.v1 import (
    dashboard,
    health,
    invitations,
    me,
    organizations,
    products,
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
