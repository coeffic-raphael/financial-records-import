"""One error shape for the whole API.

Business validation errors (FieldError, persisted on a record) and API errors
(4xx/5xx transport) are two different notions and are never conflated. This
module owns the second one only.
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class APIError(Exception):
    """Raised by services; turned into a uniform JSON body by the handlers."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def not_found(resource: str) -> APIError:
    """404 for a resource belonging to another tenant, never 403.

    A 403 would confirm the resource exists, which leaks information across
    tenants.
    """
    return APIError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", f"{resource} not found.")


def _body(code: str, message: str, details: dict | None = None) -> dict:
    return {"code": code, "message": message, "details": details}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error(_: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_body(
                "INVALID_REQUEST",
                "The request body is invalid.",
                {"errors": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_body("HTTP_ERROR", str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Never leak a stack trace, a table name or a query fragment to a client.
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_body("INTERNAL_ERROR", "An unexpected error occurred."),
        )
