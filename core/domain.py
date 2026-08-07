"""Shared Pydantic domain models. Imported by every other package."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Asset(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    name: str
    site: str
    unit: str | None = None
    asset_class: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class Alarm(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    asset_id: str
    severity: Severity
    message: str
    raised_at: datetime
    acknowledged: bool = False


class AlarmSummary(BaseModel):
    site: str | None = None
    asset_id: str | None = None
    severity: Severity | None = None
    since: datetime | None = None
    until: datetime | None = None
    items: list[Alarm] = Field(default_factory=list)
    total: int = 0


class OperatorRecommendation(BaseModel):
    alarm_id: str
    priority_score: int = Field(ge=0, le=100)
    actions: list[str] = Field(default_factory=list)
    rationale: str | None = None


class Citation(BaseModel):
    doc_id: str
    section: str | None = None
    page: int | None = None
    score: float | None = None
    excerpt: str | None = None


class Incident(BaseModel):
    id: str
    title: str
    summary: str
    severity: Severity
    likely_cause: str | None = None
    recommended_actions: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    similar_tickets: list[str] = Field(default_factory=list)
    created_at: datetime


class TicketDraft(BaseModel):
    title: str
    body: str
    severity: Severity
    incident_id: str | None = None
    assignee: str | None = None
    labels: list[str] = Field(default_factory=list)


class TraceStep(BaseModel):
    """One row of the MCP execution trace surfaced in every response."""

    server: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    output: Any | None = None
    duration_ms: int
    outcome: Literal["success", "error", "timeout"] = "success"
    error: str | None = None
    retry_count: int = 0
    api_status_code: int | None = None
