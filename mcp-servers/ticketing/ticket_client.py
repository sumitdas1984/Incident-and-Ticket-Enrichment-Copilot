"""Async HTTP client for the ticket-mock service.

The two tools (``search_tickets`` and ``create_ticket_draft``)
talk to the ticket-mock service through this single client.
Mirrors the ``AlarmApiClient`` shape used by the alarm-management
MCP server: token, bearer header, per-request timeout. No retry
policy here — the orchestrator's chain is sequential and the
ticket service is on the local docker network.

Hard constraint #1 ("MCP-only via the wire") is satisfied by
the fact that the only place outside ``connectors/ticket_mock``
(the service itself) that opens an ``httpx.AsyncClient`` for
this base URL is this module — every tool handler in
``tools.py`` imports ``TicketClient`` and goes through
``server.ticket_client``.
"""
from __future__ import annotations

from typing import Any

import httpx
from pydantic import SecretStr

from core.config import Settings


class TicketClient:
    """Async client for the ticket-mock service."""

    def __init__(
        self,
        *,
        base_url: str,
        token: SecretStr,
        timeout_seconds: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Accept": "application/json"},
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> TicketClient:
        """Build a client from the app's central `Settings`.

        Reads ``TICKETING_API_URL`` and ``TICKETING_API_TOKEN``.
        """
        return cls(
            base_url=settings.ticketing_api_url,
            token=settings.ticketing_api_token,
        )

    async def get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue ``GET <base_url><path>`` and return the parsed JSON."""
        try:
            response = await self._client.get(
                path, params=params, headers=self._headers()
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TicketClientError(f"Ticket-mock GET failed: {exc}") from exc
        return response.json()

    async def post_json(self, path: str, *, json: dict[str, Any]) -> dict[str, Any]:
        """Issue ``POST <base_url><path>`` with a JSON body."""
        try:
            response = await self._client.post(
                path, json=json, headers=self._headers()
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TicketClientError(f"Ticket-mock POST failed: {exc}") from exc
        return response.json()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token.get_secret_value()}",
        }


class TicketClientError(RuntimeError):
    """Raised when the ticket-mock call fails.

    The MCP transport maps this to an ``isError`` JSON-RPC
    response. The message is sanitised — no token, no URL.
    """


__all__ = ["TicketClient", "TicketClientError"]
