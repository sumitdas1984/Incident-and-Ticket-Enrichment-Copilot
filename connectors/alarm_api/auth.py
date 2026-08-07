"""Bearer-token dependency: 401 if missing or invalid."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import get_settings

_bearer = HTTPBearer(auto_error=False)


def require_bearer(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
) -> None:
    """Reject the request with 401 if the bearer token is missing or wrong.

    The expected token comes from Settings.alarm_api_token (SecretStr).
    Local dev defaults to 'replace-me'; override via the ALARM_API_TOKEN
    env var to match what the Postman collection sends ('demo-token').
    """
    expected = get_settings().alarm_api_token.get_secret_value()
    if creds is None or creds.scheme.lower() != "bearer" or creds.credentials != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Missing or invalid bearer token"},
        )
