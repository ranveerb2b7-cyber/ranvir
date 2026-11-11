from fastapi import APIRouter

from sellerscope.api.v1 import health, invitations, me, organizations

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(me.router)
api_router.include_router(organizations.router)
api_router.include_router(invitations.router)
