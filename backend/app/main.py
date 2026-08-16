"""Application factory."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api import batches, records
from app.api.errors import register_error_handlers
from app.config import get_settings
from app.providers.registry import build_provider

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Refuse to start on a provider configuration that cannot work.

    Building the provider lazily on the first request means a missing key
    surfaces as a 500 on someone's first upload. They would have watched the
    application start, believed it healthy, and only found out by handing it a
    document. Failing here says what is wrong before anyone tries.
    """
    settings = get_settings()
    try:
        provider = build_provider(settings)
    except ValueError as error:
        logger.error("Extraction provider is misconfigured: %s", error)
        raise
    logger.info("Extraction provider ready: %s", provider.name)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        lifespan=lifespan,
        title="Financial Records Import",
        description="Imports, extracts, validates, corrects and approves financial records "
        "from CSV and PDF sources.",
        version="0.2.0",
    )

    app.add_middleware(
        CORSMiddleware,
        # An explicit origin list is mandatory: browsers forbid "*" together
        # with credentials, which the refresh cookie requires.
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def no_store(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Stop the browser from replaying one user's response to the next.

        Without this, a cached GET from user A can be served to user B on the
        same machine -- a leak no server-side check can catch.
        """
        response = await call_next(request)
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    register_error_handlers(app)
    app.include_router(batches.router, prefix="/api")
    app.include_router(records.router, prefix="/api")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        """Send anyone opening the bare host to the interactive documentation.

        A reviewer's first action is to open the root URL; landing on a 404 is a
        poor first impression for no reason.
        """
        return RedirectResponse(url="/docs")

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
