"""FastAPI entry point for the Agentic FinOps platform demo.

This is the production-style path that replaces Streamlit as the main user
entry point: the browser calls APIs, and APIs call the FinOps Analyst Agent.
Phase 4 adds a lightweight event bus and coordinator worker so agent execution
can be demonstrated as event-driven instead of manually chained by the UI.
"""

from __future__ import annotations

import math
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents.analyst import FinOpsAnalystAgent, PREPARED_QUESTIONS
from agents.core import AGENT_CATALOG
from agents.meeting2 import bootstrap_meeting2
from agents.storage import DB_PATH, fetch_df, get_connection, init_db, table_count
from events.schemas import EVENT_PIPELINE_FAILED, EVENT_TELEMETRY_RECEIVED
from events.store import event_summary, fetch_events, get_coordinator_state, init_event_store, publish_event
from events.worker import EventWorker

APP_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = APP_ROOT / "frontend"

analyst = FinOpsAnalystAgent()
event_worker = EventWorker(interval_seconds=2.0)


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3)
    time_window: str = "latest_48h"
    cloud: str = "azure"


class RefreshRequest(BaseModel):
    force: bool = False


class TelemetryEventRequest(BaseModel):
    source: str = "telemetry-api"
    dataset: str = "current_demo_data"
    rows_seen: int | None = None
    vm_count: int | None = None
    note: str = "Demo telemetry batch arrived"


class PipelineFailureEventRequest(BaseModel):
    source: str = "pipeline-monitor"
    pipeline_name: str = "forecast_generation"
    stage: str = "model_training"
    failure_reason: str = "VM had insufficient history for 48-hour lookback"
    records_processed: int = 0


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_audit_data(force=False)
    await event_worker.start()
    try:
        yield
    finally:
        await event_worker.stop()


app = FastAPI(
    title="Agentic Proactive FinOps Multi-Cloud API",
    version="0.5.0",
    description="API gateway for multi-cloud telemetry, the FinOps Analyst Agent, event bus, coordinator, and operational dashboard.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def json_safe(value: Any) -> Any:
    """Convert pandas/numpy values into JSON-safe primitives."""
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except ValueError:
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def records(query: str, limit: int | None = None) -> list[dict[str, Any]]:
    df = fetch_df(query)
    if limit is not None:
        df = df.head(limit)
    return json_safe(df.to_dict("records"))


def ensure_audit_data(force: bool = False) -> int:
    with get_connection(DB_PATH) as conn:
        init_db(conn)
        init_event_store(conn)
        before = table_count(conn, "agent_runs")
        bootstrap_meeting2(conn, force=force)
        after = table_count(conn, "agent_runs")
    return after - before


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "agentic-finops-api",
        "database": str(DB_PATH),
        "frontend_available": FRONTEND_DIR.exists(),
        "event_worker": "running",
        "events": event_summary(),
        "coordinator": get_coordinator_state(),
    }


@app.get("/api/questions")
def questions() -> dict[str, Any]:
    return {"questions": PREPARED_QUESTIONS}


@app.get("/api/architecture")
def architecture() -> dict[str, Any]:
    return {
        "entry_point": "Browser dashboard + FastAPI event/API gateway",
        "visible_agent": "FinOps Analyst Agent",
        "coordinator": "Coordinator Agent consumes persisted events and routes internal tools.",
        "components": AGENT_CATALOG,
        "flow": [
            "Telemetry/Event API",
            "SQLite Event Bus",
            "Coordinator Agent",
            "Internal Agent Tools",
            "Downstream Events",
            "Stored Results",
            "Browser visualizes state",
        ],
        "event_flow": [
            "telemetry.received",
            "forecast.completed",
            "recommendation.created",
            "serverless.action.created",
            "action log stored",
        ],
    }


@app.get("/api/dataset-profile")
def dataset_profile() -> dict[str, Any]:
    return json_safe(analyst.profiler.profile())


@app.post("/api/query")
def query(request: QueryRequest) -> dict[str, Any]:
    answer = analyst.run(
        request.question,
        {"time_window": request.time_window, "cloud": request.cloud},
    )
    return json_safe(answer.to_dict())


@app.get("/api/recommendations/low-peak")
def low_peak_recommendations() -> dict[str, Any]:
    answer = analyst.run("Which VMs can be shut down during low peak hours?")
    return json_safe(answer.to_dict())


@app.get("/api/events")
def events(limit: int = 100) -> dict[str, Any]:
    return json_safe({
        "summary": event_summary(),
        "coordinator": get_coordinator_state(),
        "events": fetch_events(limit=limit),
    })


@app.post("/api/events/telemetry")
def publish_telemetry_event(request: TelemetryEventRequest) -> dict[str, Any]:
    profile = analyst.profiler.profile()
    event = publish_event(
        EVENT_TELEMETRY_RECEIVED,
        source=request.source,
        payload={
            "dataset": request.dataset,
            "rows_seen": request.rows_seen or profile["vm_rows"],
            "vm_count": request.vm_count or profile["vm_count"],
            "provider_count": profile.get("provider_count", 0),
            "providers": profile.get("providers", {}),
            "schema_version": (profile.get("schema_versions") or ["unknown"])[0],
            "note": request.note,
        },
    )
    decisions = event_worker.process_pending(limit=8)
    return json_safe({"published_event": event, "decisions": decisions, "events": fetch_events(limit=25)})


@app.post("/api/events/pipeline-failure")
def publish_pipeline_failure_event(request: PipelineFailureEventRequest) -> dict[str, Any]:
    event = publish_event(
        EVENT_PIPELINE_FAILED,
        source=request.source,
        payload={
            "pipeline_name": request.pipeline_name,
            "stage": request.stage,
            "failure_reason": request.failure_reason,
            "records_processed": request.records_processed,
        },
    )
    decisions = event_worker.process_pending(limit=8)
    return json_safe({"published_event": event, "decisions": decisions, "events": fetch_events(limit=25)})


@app.post("/api/events/demo-run")
def run_event_demo() -> dict[str, Any]:
    profile = analyst.profiler.profile()
    telemetry = publish_event(
        EVENT_TELEMETRY_RECEIVED,
        source="demo-telemetry-api",
        payload={
            "dataset": profile["dataset_name"],
            "rows_seen": profile["vm_rows"],
            "vm_count": profile["vm_count"],
            "provider_count": profile.get("provider_count", 0),
            "providers": profile.get("providers", {}),
            "schema_version": (profile.get("schema_versions") or ["unknown"])[0],
            "note": "Demo multi-cloud telemetry batch pushed into the event bus",
        },
    )
    pipeline = publish_event(
        EVENT_PIPELINE_FAILED,
        source="demo-pipeline-monitor",
        payload={
            "pipeline_name": "forecast_generation",
            "stage": "model_training",
            "failure_reason": "Synthetic demo failure: VM had insufficient history for 48-hour lookback",
            "records_processed": 0,
        },
    )
    decisions = event_worker.process_pending(limit=20)
    return json_safe({
        "published_events": [telemetry, pipeline],
        "decisions": decisions,
        "summary": event_summary(),
        "coordinator": get_coordinator_state(),
        "events": fetch_events(limit=50),
    })


@app.get("/api/operational/summary")
def operational_summary() -> dict[str, Any]:
    ensure_audit_data(force=False)
    agent_runs = fetch_df("SELECT * FROM agent_runs ORDER BY created_at DESC")
    pipeline_runs = fetch_df("SELECT * FROM pipeline_runs ORDER BY created_at DESC")
    actions = fetch_df("SELECT * FROM serverless_action_logs ORDER BY created_at DESC")
    status_counts = agent_runs["status"].value_counts().to_dict() if not agent_runs.empty else {}
    pipeline_counts = pipeline_runs["status"].value_counts().to_dict() if not pipeline_runs.empty else {}
    action_counts = actions["status"].value_counts().to_dict() if not actions.empty else {}
    events_info = event_summary()
    return json_safe({
        "agent_runs": int(len(agent_runs)),
        "successful_agent_runs": int(status_counts.get("success", 0)),
        "failed_agent_runs": int(status_counts.get("failed", 0)),
        "pipeline_runs": int(len(pipeline_runs)),
        "failed_pipeline_runs": int(pipeline_counts.get("failed", 0)),
        "serverless_actions": int(len(actions)),
        "failed_serverless_actions": int(action_counts.get("failed", 0)),
        "events": events_info["total_events"],
        "pending_events": events_info["pending_events"],
        "processed_events": events_info["processed_events"],
    })


@app.get("/api/operational/audit")
def operational_audit() -> dict[str, Any]:
    ensure_audit_data(force=False)
    return {
        "agent_runs": records(
            "SELECT created_at, agent_name, status, duration_ms, records_processed, summary FROM agent_runs ORDER BY created_at DESC",
            limit=50,
        ),
        "pipeline_runs": records(
            "SELECT created_at, pipeline_name, stage, status, duration_ms, records_processed, failure_reason FROM pipeline_runs ORDER BY created_at DESC",
            limit=50,
        ),
        "serverless_actions": records(
            "SELECT created_at, function_name, trigger_type, resource_id, application, status, duration_ms, response_message FROM serverless_action_logs ORDER BY created_at DESC",
            limit=50,
        ),
        "events": fetch_events(limit=50),
        "storage": records("SELECT * FROM data_storage_summary ORDER BY dataset"),
    }


@app.post("/api/operational/refresh")
def refresh_operational_demo(request: RefreshRequest) -> dict[str, Any]:
    created = ensure_audit_data(force=request.force)
    return {"created_runs": created, "force": request.force}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")
