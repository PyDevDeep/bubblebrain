from fastapi import APIRouter

from app.api.v1.endpoints.chat import chat_router
from app.api.v1.endpoints.health import health_router
from app.api.v1.endpoints.ingest import ingest_router
from app.api.v1.endpoints.leads import leads_router

api_v1_router = APIRouter()

api_v1_router.include_router(health_router, tags=["health"])
api_v1_router.include_router(ingest_router, prefix="/ingest", tags=["ingestion"])
api_v1_router.include_router(chat_router, prefix="/chat", tags=["chat"])
api_v1_router.include_router(leads_router, prefix="/leads", tags=["leads"])
