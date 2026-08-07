"""Alarm Management API simulator.

Implements every endpoint defined in
postman/Alarm-API-Simulator.postman_collection.json, the chaining
collection, and the scenarios collection. The MCP server (Epic 3)
and any other client calls this service via the bearer token
configured in core.config.Settings.
"""
from . import app, auth, errors, models, seed, store  # noqa: F401

__all__ = ["app", "auth", "errors", "models", "seed", "store"]
