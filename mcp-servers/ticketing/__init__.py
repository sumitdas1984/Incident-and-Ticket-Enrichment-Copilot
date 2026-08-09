"""Ticketing MCP server (Feature 6.1).

Boots a candidate-developed MCP server that exposes ticket
search and draft-generation tools to the orchestrator over
Streamable HTTP. The MCP protocol is provided by the official
Python SDK. The candidate-developed surface mirrors the
alarm-management MCP server's structure: typed tool
registration, liveness/readiness probes, structured logging,
and a shared HTTP client for the ticket-mock service.
"""
