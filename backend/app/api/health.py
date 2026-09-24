from fastapi import APIRouter, Request

from app.api.dependencies import get_services
from app.models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
async def ready(request: Request) -> HealthResponse:
    await get_services(request).pools.check()
    return HealthResponse(status="ready")
