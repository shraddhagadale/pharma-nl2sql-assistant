import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware

from app.api import analytics, health, sessions
from app.config import Settings, get_settings
from app.services.container import Services


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    services = Services.build(resolved_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        await services.pools.check()
        application.state.services = services
        yield
        await services.pools.dispose()

    application = FastAPI(
        title="Pharma NL-to-SQL API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.services = services
    application.add_middleware(
        SessionMiddleware,
        secret_key=resolved_settings.session_secret.get_secret_value(),
        session_cookie=resolved_settings.session_cookie_name,
        max_age=resolved_settings.session_max_age_seconds,
        same_site="lax",
        https_only=resolved_settings.cookie_secure,
    )

    @application.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    application.include_router(health.router)
    application.include_router(sessions.router, prefix=resolved_settings.api_prefix)
    application.include_router(analytics.router, prefix=resolved_settings.api_prefix)
    return application


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = create_app()
