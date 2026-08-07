"""Shared infrastructure: config, logging, exceptions, utils, domain models.

Every other package in this project (apps, mcp-servers, rag,
connectors) depends on this one -- never the reverse.
"""
from . import config, exceptions, logging, utils  # noqa: F401

# core.domain lands in Story 1.2.2; once present, add 'domain' to this
# import list and __all__.
__all__ = ["config", "exceptions", "logging", "utils"]
