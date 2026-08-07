"""Standard error envelope, exception -> HTTP mapping, and trace header echo."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from core.logging import get_logger
from core.utils import new_id


class AlarmAPIError(Exception):
    """Base for simulator-raised errors that should produce a structured response."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 500,
        details: dict | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class NotFoundError(AlarmAPIError):
    def __init__(self, message: str = "Resource not found", details: dict | None = None) -> None:
        super().__init__("not_found", message, status_code=404, details=details)


def envelope(code: str, message: str, request: Request, details: dict | None = None) -> dict:
    """Build the standard error envelope with the request's trace id (or a fresh one)."""
    trace_id = request.headers.get("trace_id") or new_id()
    return {
        "code": code,
        "message": message,
        "trace_id": trace_id,
        "details": details or {},
    }


def install_handlers(app: FastAPI) -> None:
    log = get_logger(__name__)

    @app.middleware("http")
    async def _echo_trace_header(request: Request, call_next):
        """Echo the request's trace_id (if any) back as a response header.

        Spec: 'the request's trace_id, if present, is echoed back in the
        response'. This is critical for the Postman chaining collection
        to verify trace propagation across hops.
        """
        response = await call_next(request)
        trace_id = request.headers.get("trace_id")
        if trace_id is not None:
            response.headers["trace_id"] = trace_id
        return response

    @app.exception_handler(AlarmAPIError)
    async def _api_error(request: Request, exc: AlarmAPIError) -> JSONResponse:  # type: ignore[unused-ignore]
        body = envelope(exc.code, exc.message, request, exc.details)
        log.warning(
            "api_error",
            error_code=exc.code,
            status=exc.status_code,
            trace_id=body["trace_id"],
        )
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:  # type: ignore[unused-ignore]
        body = envelope("bad_request", "Request validation failed", request, {"errors": exc.errors()})
        log.info("validation_error", trace_id=body["trace_id"])
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(404)
    async def _not_found(request: Request, _exc) -> JSONResponse:
        body = envelope("not_found", "Resource not found", request)
        return JSONResponse(status_code=404, content=body)
