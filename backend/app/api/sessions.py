from time import perf_counter

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.dependencies import get_current_user, get_services
from app.audit import AuditEvent
from app.models import LoginRequest, UserContext

router = APIRouter(prefix="/demo", tags=["demo session"])


@router.get("/users", response_model=list[UserContext])
async def list_demo_users(request: Request) -> list[UserContext]:
    return await get_services(request).users.list_users()


@router.post("/session", response_model=UserContext)
async def create_demo_session(payload: LoginRequest, request: Request) -> UserContext:
    started = perf_counter()
    services = get_services(request)
    user = await services.users.get_user(payload.user_id)
    if user is None:
        services.audit.record(
            AuditEvent(
                request_id=request.state.request_id,
                user_id=payload.user_id,
                action="session.create",
                role=None,
                outcome="denied",
                duration_ms=round((perf_counter() - started) * 1_000, 3),
                row_count=0,
                error_code="unknown_user",
            )
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo user not found.",
        )

    request.session.clear()
    request.session["user_id"] = user.user_id
    services.audit.record(
        AuditEvent(
            request_id=request.state.request_id,
            user_id=user.user_id,
            action="session.create",
            role=user.role.value,
            outcome="success",
            duration_ms=round((perf_counter() - started) * 1_000, 3),
            row_count=1,
        )
    )
    return user


@router.get("/session", response_model=UserContext)
async def read_demo_session(request: Request) -> UserContext:
    return await get_current_user(request)


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def delete_demo_session(request: Request) -> Response:
    user_id = request.session.get("user_id")
    request.session.clear()
    get_services(request).audit.record(
        AuditEvent(
            request_id=request.state.request_id,
            user_id=user_id if isinstance(user_id, str) else None,
            action="session.delete",
            role=None,
            outcome="success",
            duration_ms=0,
            row_count=0,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
