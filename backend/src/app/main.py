from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.cors import allowed_origins
from app.database_ext import init_app_db
from app.health import router as health_router
from app.realtime import create_realtime_router
from app.routes import agent_threads, agents, chat, dashboard, discussions, notebooks, plans, proposals, repositories, scripts, step_types
from app.services.agent_runtime import start_desktop_event_listener


def create_app() -> FastAPI:
    app = FastAPI(
        title="Vibe API",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def on_startup() -> None:
        init_app_db()
        app.state.desktop_event_listener = start_desktop_event_listener()

    @app.on_event("shutdown")
    def on_shutdown() -> None:
        task = getattr(app.state, "desktop_event_listener", None)
        if task:
            task.cancel()

    @app.exception_handler(ValueError)
    async def value_error_handler(_request, exc: ValueError):  # type: ignore[no-untyped-def]
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.include_router(health_router, prefix="/api")
    app.include_router(dashboard.router)
    app.include_router(repositories.router)
    app.include_router(agents.router)
    app.include_router(step_types.router)
    app.include_router(scripts.router)
    app.include_router(plans.router)
    app.include_router(chat.router)
    app.include_router(proposals.router)
    app.include_router(discussions.router)
    app.include_router(notebooks.router)
    app.include_router(agent_threads.router)
    app.include_router(create_realtime_router(allow_channel=_allow_realtime_channel))
    return app


def _allow_realtime_channel(channel: str) -> bool:
    return channel.startswith(("plans:", "chat:", "agent_threads:"))


app = create_app()
