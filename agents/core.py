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
        "component": "FinOps Analyst Agent",
        "role": "Visible entry point",
        "input": "User question + selected dataset context",
        "output": "Answer, recommendation table, requirement check, evidence, next action",
        "how_it_runs": "agentic_command_center.py calls FinOpsAnalystAgent.run(question, context)",
    },
    {
        "component": "Dataset Profiler",
        "role": "Internal tool",
        "input": "Current demo CSV/JSON data",
        "output": "Dataset type, rows, VMs, date range, available/missing fields",
        "how_it_runs": "Called automatically by FinOps Analyst Agent",
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
        "input": "VM metrics, workload class, tags, latest 48h utilization",
        "output": "Shutdown, scale-down, risk, and explanation rows",
        "how_it_runs": "Called only for recommendation questions",
    },
    {
        "component": "App/DB Health Tool",
        "role": "Internal tool",
        "input": "DB metrics + application mapping",
        "output": "Application health and degradation summary",
        "how_it_runs": "Called only for application health questions",
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
        "output": "Run history, pipeline status, action logs",
        "how_it_runs": "Shown below the main agent demo for traceability",
    },
]