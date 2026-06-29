"""Shared agent contract and Meeting 1 agent catalog."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class AgentResult:
    """Standard output shape for every operational agent."""

    agent_name: str
    status: str
    summary: str
    records_processed: int = 0
    generated_insights: list[str] = field(default_factory=list)
    duration_ms: int = 0
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


AGENT_CATALOG = [
    {
        "agent": "Ingestion Agent",
        "input": "CoreStack BSON exports / augmented VM CSV",
        "output": "Validated VM inventory and metric summaries",
        "current_asset": "tools/extract_vm_metrics.py, ingestion/schema.py",
        "meeting": "Meeting 1/2",
    },
    {
        "agent": "Synthetic Data Agent",
        "input": "Real CPU/network patterns and missing metric columns",
        "output": "AI-style augmented CPU, memory, disk, network, and DB signal",
        "current_asset": "tools/augment_metrics.py, tools/generate_db_metrics.py",
        "meeting": "Meeting 1/2",
    },
    {
        "agent": "Forecasting Agent",
        "input": "VM telemetry with 48-hour lookback windows",
        "output": "Spike predictions, thresholds, MAE/RMSE, proactive accuracy",
        "current_asset": "dashboard.py::run_model",
        "meeting": "Future",
    },
    {
        "agent": "Recommendation Agent",
        "input": "Recent VM telemetry, workload class, application tags",
        "output": "SCALE_UP, SCALE_DOWN, SHUTDOWN_LOW_PEAK, KEEP_RUNNING",
        "current_asset": "dashboard.py::get_recommendations",
        "meeting": "Meeting 2 seed / Meeting 3 full",
    },
    {
        "agent": "Application Health Agent",
        "input": "VM metrics, DB metrics, application tag mapping",
        "output": "Application risk and DB health summaries",
        "current_asset": "DbDashboard.py",
        "meeting": "Meeting 2 seed / Meeting 4 full",
    },
    {
        "agent": "Pipeline Monitor Agent",
        "input": "Agent and pipeline execution events",
        "output": "Daily executions, failures, success rate, failure reasons",
        "current_asset": "New storage-backed monitor",
        "meeting": "Meeting 2 seed / Meeting 4 full",
    },
    {
        "agent": "Serverless Action Agent",
        "input": "Recommendations and pipeline failures",
        "output": "Lambda/Azure Function payloads and execution logs",
        "current_asset": "dashboard.py/DbDashboard.py simulated action logs",
        "meeting": "Meeting 2 seed / Meeting 5 full",
    },
    {
        "agent": "Query Agent",
        "input": "User FinOps question plus stored agent outputs",
        "output": "Explainable operational answer",
        "current_asset": "New natural-language query layer",
        "meeting": "Future",
    },
]
