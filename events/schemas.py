"""Event contracts for the Phase 4 event-driven FinOps demo."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

EVENT_TELEMETRY_RECEIVED = "telemetry.received"
EVENT_FORECAST_COMPLETED = "forecast.completed"
EVENT_RECOMMENDATION_CREATED = "recommendation.created"
EVENT_PIPELINE_FAILED = "pipeline.failed"
EVENT_SERVERLESS_ACTION_CREATED = "serverless.action.created"
EVENT_COORDINATOR_UPDATED = "coordinator.state.updated"

EVENT_TYPES = [
    EVENT_TELEMETRY_RECEIVED,
    EVENT_FORECAST_COMPLETED,
    EVENT_RECOMMENDATION_CREATED,
    EVENT_PIPELINE_FAILED,
    EVENT_SERVERLESS_ACTION_CREATED,
    EVENT_COORDINATOR_UPDATED,
]


@dataclass
class FinOpsEvent:
    """Persisted event envelope used by the event bus simulation."""

    event_type: str
    source: str
    payload: dict[str, Any]
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    event_id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "pending"
    attempts: int = 0
    result_summary: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")
