import asyncio
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.agent.workflow import AgentUnavailableError
from app.api.dependencies import get_current_user, get_services
from app.audit import AuditEvent
from app.models import ChatRequest, ChatResponse, UserContext

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request: Request,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> ChatResponse:
    services = get_services(request)
    started = perf_counter()
    try:
        async with asyncio.timeout(services.agent.request_timeout_seconds):
            return await services.agent.run(
                question=payload.question,
                conversation=payload.conversation,
                user=user,
                include_sql=payload.include_sql,
                request_id=request.state.request_id,
            )
    except TimeoutError as error:
        services.audit.record(
            AuditEvent(
                request_id=request.state.request_id,
                user_id=user.user_id,
                action="agent.query",
                role=user.role.value,
                outcome="error",
                duration_ms=round((perf_counter() - started) * 1_000, 3),
                row_count=0,
                error_code="agent_timeout",
            )
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=("This analysis is taking longer than expected. Please retry the same request."),
        ) from error
    except AgentUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The analytics model is not configured or temporarily unavailable.",
        ) from error
