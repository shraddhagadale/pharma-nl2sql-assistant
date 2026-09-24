from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.agent.workflow import AgentUnavailableError
from app.api.dependencies import get_current_user, get_services
from app.models import ChatRequest, ChatResponse, UserContext

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request: Request,
    user: Annotated[UserContext, Depends(get_current_user)],
) -> ChatResponse:
    try:
        return await get_services(request).agent.run(
            question=payload.question,
            conversation=payload.conversation,
            user=user,
            include_sql=payload.include_sql,
            request_id=request.state.request_id,
        )
    except AgentUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The analytics model is not configured or temporarily unavailable.",
        ) from error
