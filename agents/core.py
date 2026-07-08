"""Shared contracts and catalog for the agentic FinOps demo."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class AgentResult:
    """Operational audit record for internal tools and pipelines."""

    agent_name: str
    status: str
    summary: str
    records_processed: int = 0
    generated_insights: list[str] = field(default_factory=list)
    duration_ms: int = 0
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentAnswer:
    """Public answer contract for the visible FinOps Analyst Agent."""

    answer: str
    intent: str
    dataset_profile: dict[str, Any]
    requirement_check: list[dict[str, str]]
    recommendations: list[dict[str, Any]]
    evidence: dict[str, Any]
    tools_used: list[str]
    next_action: str
    context: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


AGENT_CATALOG = [
    {
        "component": "SQLite Event Bus",
        "role": "Event transport layer",
        "input": "telemetry.received, pipeline.failed, forecast.completed, recommendation.created events",
        "output": "Persisted event stream with pending/processed/failed status",
        "how_it_runs": "FastAPI event endpoints publish events; EventWorker claims pending events",
    },
    {
        "component": "Coordinator Agent",
        "role": "Event orchestrator",
        "input": "Pending event envelopes from the event bus",
        "output": "Downstream events, audit records, and serverless action payloads",
        "how_it_runs": "Background EventWorker calls CoordinatorAgent.handle_event(event)",
    },
    {
        "component": "FinOps Analyst Agent",
        "role": "Visible question entry point",
        "input": "User question + selected dataset context",
        "output": "Answer, recommendation table, requirement check, evidence, next action",
        "how_it_runs": "FastAPI /api/query handles direct questions; event flow reaches the analyst through Coordinator Agent routes",
    },
    {
        "component": "Dataset Profiler",
        "role": "Internal tool",
        "input": "Current demo CSV/JSON data",
        "output": "Dataset type, rows, VMs, date range, available/missing fields",
        "how_it_runs": "Called automatically by the FinOps Analyst Agent behind the API",
    },
    {
        "component": "Requirement Checker",
        "role": "Internal tool",
        "input": "Detected intent + dataset profile",
        "output": "Available / optional / missing / not required checklist",
        "how_it_runs": "Called automatically before answering",
    },
    {
        "component": "Recommendation Tool",
        "role": "Internal tool",
        "input": "VM metrics, workload class, tags, latest 48h utilization, enterprise context",
        "output": "Shutdown, scale-down, risk, savings, and explanation rows",
        "how_it_runs": "Called for recommendation questions and forecast-completed events",
    },
    {
        "component": "App/DB Health Tool",
        "role": "Internal tool",
        "input": "DB metrics + application mapping",
        "output": "Application health and degradation summary",
        "how_it_runs": "Called only for application health questions",
    },
    {
        "component": "Serverless Action Router",
        "role": "Action orchestration tool",
        "input": "recommendation.created or pipeline.failed events",
        "output": "Lambda-style payloads and serverless action logs",
        "how_it_runs": "Coordinator publishes serverless.action.created events; EventWorker logs action results",
    },
    {
        "component": "Data Ingestion Pipeline",
        "role": "Data preparation pipeline",
        "input": "CoreStack raw/processed telemetry",
        "output": "Normalized metric files used by the agent",
        "how_it_runs": "Offline pipeline; not the main user-facing agent",
    },
    {
        "component": "Synthetic Data Generator",
        "role": "Data preparation pipeline",
        "input": "Real VM patterns + missing memory/disk/DB signals",
        "output": "Augmented demo datasets for prediction/testing",
        "how_it_runs": "Offline pipeline; not manually called during the agent demo",
    },
    {
        "component": "Operational Audit Trail",
        "role": "Observability layer",
        "input": "Internal tool/pipeline execution events",
        "output": "Run history, pipeline status, event stream, action logs",
        "how_it_runs": "Returned by operational API endpoints and visualized below the main answer",
    },
]
