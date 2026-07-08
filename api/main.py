"""FastAPI entry point for the Agentic FinOps platform demo.

This is the production-style path that replaces Streamlit as the main user
entry point: the browser calls APIs, and APIs call the FinOps Analyst Agent.
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

APP_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = APP_ROOT / "frontend"

@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_audit_data(force=False)
    yield


app = FastAPI(
    title="Agentic Proactive FinOps API",
    version="0.4.0",
    description="API gateway for the FinOps Analyst Agent and operational dashboard.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

analyst = FinOpsAnalystAgent()


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3)
    time_window: str = "latest_48h"
    cloud: str = "azure"


class RefreshRequest(BaseModel):
    force: bool = False


def json_safe(value: Any) -> Any:
    """Convert pandas/numpy values into JSON-safe primitives."""
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp,)):
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
    }


@app.get("/api/questions")
def questions() -> dict[str, Any]:
    return {"questions": PREPARED_QUESTIONS}


@app.get("/api/architecture")
def architecture() -> dict[str, Any]:
    return {
        "entry_point": "FastAPI /api/query",
        "visible_agent": "FinOps Analyst Agent",
        "components": AGENT_CATALOG,
        "flow": [
            "Browser dashboard",
            "FastAPI API Gateway",
            "FinOps Analyst Agent",
            "Dataset Profiler",
            "Requirement Checker",
            "Internal Tools",
            "Answer + Recommendations + Evidence",
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


@app.get("/api/operational/summary")
def operational_summary() -> dict[str, Any]:
    ensure_audit_data(force=False)
    agent_runs = fetch_df("SELECT * FROM agent_runs ORDER BY created_at DESC")
    pipeline_runs = fetch_df("SELECT * FROM pipeline_runs ORDER BY created_at DESC")
    actions = fetch_df("SELECT * FROM serverless_action_logs ORDER BY created_at DESC")
    status_counts = agent_runs["status"].value_counts().to_dict() if not agent_runs.empty else {}
    pipeline_counts = pipeline_runs["status"].value_counts().to_dict() if not pipeline_runs.empty else {}
    action_counts = actions["status"].value_counts().to_dict() if not actions.empty else {}
    return json_safe({
        "agent_runs": int(len(agent_runs)),
        "successful_agent_runs": int(status_counts.get("success", 0)),
        "failed_agent_runs": int(status_counts.get("failed", 0)),
        "pipeline_runs": int(len(pipeline_runs)),
        "failed_pipeline_runs": int(pipeline_counts.get("failed", 0)),
        "serverless_actions": int(len(actions)),
        "failed_serverless_actions": int(action_counts.get("failed", 0)),
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

