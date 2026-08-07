"""Alarm Management MCP server package.

Feature 3.1 lands the scaffolding + tool registration. Feature 3.2
adds the four production-quality Alarm Management tools
(``search_assets``, ``get_alarm``, ``summarize_alarms``,
``recommend_actions``) wired through a single
:class:`AlarmApiClient`.

Public surface
--------------

* :class:`AlarmApiClient` — async HTTP client for the Alarm API
* :class:`AlarmNotFoundError` — distinct 404 envelope
* :func:`register_tool` — decorator for typed tool handlers
* :func:`register_tools` — registers all four Alarm tools on a
  given ``MCPServer`` instance
* :func:`get_alarm_api_client` — accessor used by tests / handlers
  to fetch the live client off the server
* :class:`ToolInvocationError` — base sanitised MCP error envelope
"""
from __future__ import annotations

from .alarm_api_client import AlarmApiClient, AlarmNotFoundError
from .registry import ToolInvocationError, register_tool
from .tools import get_alarm_api_client, register_tools

__all__ = [
    "AlarmApiClient",
    "AlarmNotFoundError",
    "ToolInvocationError",
    "get_alarm_api_client",
    "register_tool",
    "register_tools",
]
