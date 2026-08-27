from fastapi import APIRouter

from app.api.v1 import api_keys, auth, dashboard, placement, plan, practices, reports, topics, users, vocab, ws

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
api_router.include_router(topics.router, prefix="/topics", tags=["topics"])
api_router.include_router(practices.router, prefix="/practices", tags=["practices"])
api_router.include_router(reports.router, prefix="", tags=["reports"])
api_router.include_router(vocab.router, prefix="/vocab-words", tags=["vocab"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(placement.router, prefix="/placement", tags=["placement"])
api_router.include_router(plan.router, prefix="/plan", tags=["plan"])
api_router.include_router(ws.router, prefix="", tags=["ws"])
