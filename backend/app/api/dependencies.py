from fastapi import HTTPException, Request, status

from app.models import UserContext
from app.services.container import Services


def get_services(request: Request) -> Services:
    return request.app.state.services


async def get_current_user(request: Request) -> UserContext:
    user_id = request.session.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A demo user session is required.",
        )

    services = get_services(request)
    user = await services.users.get_user(user_id)
    if user is None:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The selected user is no longer available.",
        )
    return user
