"""Alarm Management MCP server package.

Feature 3.1 lands the scaffolding + tool registration; concrete Alarm
tools (``search_assets``, ``get_alarm``, ``summarize_alarms``,
``recommend_actions``) land in Feature 3.2.
"""
from __future__ import annotations

from .registry import ToolInvocationError, register_tool

__all__ = ["ToolInvocationError", "register_tool"]
