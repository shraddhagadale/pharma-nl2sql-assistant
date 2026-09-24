from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import get_current_user, get_services
from app.models import AnalyticsOverview, UserContext

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverview)
async def analytics_overview(
    request: Request,
    user: Annotated[UserContext, Depends(get_current_user)],
    months: Annotated[int, Query(ge=1, le=12)] = 3,
) -> AnalyticsOverview:
    return await get_services(request).analytics.overview(
        user=user,
        months=months,
        request_id=request.state.request_id,
    )
