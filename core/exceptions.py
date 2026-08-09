"""Project-wide exception hierarchy."""


class CopilotError(Exception):
    """Base for every exception this project raises."""


class ConfigError(CopilotError):
    """Configuration invalid or missing."""


class AlarmAPIError(CopilotError):
    """Alarm Management API returned an error or was unreachable."""


class MCPError(CopilotError):
    """MCP server returned an error or was unreachable."""


class RAGError(CopilotError):
    """Retrieval failed (low confidence, broken index, etc.)."""


class LLMError(CopilotError):
    """LLM provider returned an error or a malformed response."""""


class TicketApprovalRequired(CopilotError):  # noqa: N818 -- not an "Error" in the conventional sense, it's a control-flow signal
    """Write operation attempted without explicit user approval."""


class TicketError(CopilotError):
    """Ticket service returned an error or was unreachable."""
