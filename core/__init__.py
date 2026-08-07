"""Shared infrastructure: config, logging, exceptions, utils, domain models.

Every other package in this project (apps, mcp-servers, rag,
connectors) depends on this one -- never the reverse.
"""
from . import config, domain, exceptions, logging, utils  # noqa: F401

__all__ = ["config", "domain", "exceptions", "logging", "utils"]
