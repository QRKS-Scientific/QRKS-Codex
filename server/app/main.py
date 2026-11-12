from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Request

from .config import Settings
from .db import make_engine, make_sessionmaker
from .deps import RateLimiter
from .models import Base
from .routers import auth, meta, runs
from .security import Security


def create_app(settings: Settings | None = None, clock: Callable[[], float] = time.time) -> FastAPI:
    settings = settings or Settings()
    if settings.database_url.startswith("sqlite:///") and not settings.database_url.startswith("sqlite:///:memory:"):
        Path(settings.database_url.replace("sqlite:///", "", 1)).parent.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="QRKSDock server", version="0.1.0", docs_url="/docs" if settings.debug else None,
                  redoc_url=None, openapi_url="/openapi.json" if settings.debug else None)
    app.state.settings = settings
    app.state.clock = clock
    app.state.security = Security(settings)
    app.state.limiter = RateLimiter(clock)
    app.state.engine = make_engine(settings.database_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    Base.metadata.create_all(app.state.engine)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    for r in (auth.router, runs.router, meta.router):
        app.include_router(r)
    return app


def app_from_env() -> FastAPI:                       # uvicorn app.main:app_from_env --factory
    return create_app()
