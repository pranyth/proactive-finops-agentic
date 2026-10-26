"""FastAPI gateway for the agentic FinOps decision platform.

Serves one question endpoint covering both domains (infrastructure telemetry and
managed AI services) plus the read models the console renders.
"""

from __future__ import annotations

import math
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents import capacity, datacache, fleet, forecasting
from agents.meeting2 import bootstrap_meeting2
from agents.storage import DB_PATH, get_connection, init_db, table_count
from agents.unified import UnifiedFinOpsAgent, suggestions_for
from ai_finops.llm import LLMReasoner
from ai_finops.storage import deployment_summary, ensure_ai_demo_data, profile, recommendation_rows
from events.schemas import EVENT_AI_USAGE_RECEIVED, EVENT_TELEMETRY_RECEIVED
from events.store import event_summary, fetch_events, get_coordinator_state, init_event_store, publish_event
from events.worker import EventWorker

APP_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = APP_ROOT / "frontend"
agent = UnifiedFinOpsAgent()
event_worker = EventWorker(interval_seconds=2.0)


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3)
    time_window: str = "latest_30d"
    provider: str = "all"
    domain: str = "auto"
    explain: bool = True


class RefreshRequest(BaseModel):
    force: bool = False


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_ai_demo_data()
    ensure_audit_data()
    warm_caches()
    await event_worker.start()
    try:
        yield
    finally:
        await event_worker.stop()


def warm_caches() -> None:
    """Build the VM telemetry frames now so the first question is not the slow one.

    Reading ~200k rows of CSV takes over a second; paying it during startup is
    better than paying it on the user's first click.
    """
    try:
        fleet.summary()
    except Exception as exc:  # noqa: BLE001 - a cold cache must never block startup
        print(f"[warm-up] skipped infrastructure cache: {exc}")
    # Each forecast fits two models and takes ~20s, so this runs on a background
    # thread. The endpoint reports `warming` until it lands.
    forecasting.warm_fleet_forecast()
    capacity.warm_fleet_capacity()


app = FastAPI(
    title="Agentic FinOps for Cloud Infrastructure and AI Services",
    version="2.0.0",
    description="One agent for VM utilization governance and managed LLM cost governance.",
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
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
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


def ensure_audit_data(force: bool = False) -> int:
    with get_connection(DB_PATH) as conn:
        init_db(conn)
        init_event_store(conn)
        before = table_count(conn, "agent_runs")
        bootstrap_meeting2(conn, force=force)
        return table_count(conn, "agent_runs") - before


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "agentic-finops-api",
        "domains": ["infrastructure", "ai_services"],
        "llm": LLMReasoner().status(),
        "event_worker": "running",
        "events": event_summary(),
        "coordinator": get_coordinator_state(),
    }


@app.post("/api/query")
@app.post("/api/ai-finops/query")
def query(request: QueryRequest) -> dict[str, Any]:
    """Ask anything. The router picks the domain unless the caller pins one."""
    return json_safe(
        agent.ask(
            request.question,
            {
                "time_window": request.time_window,
                "provider": request.provider,
                "domain": request.domain,
                "explain": request.explain,
            },
        )
    )


@app.get("/api/suggestions")
def suggestions(domain: str = "all") -> dict[str, Any]:
    return {"suggestions": suggestions_for(domain)}


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    """Merged estate KPIs: virtual machines and AI deployments side by side."""
    infra = fleet.summary()
    ai_profile = profile()
    deployments = deployment_summary()

    provider_cost: dict[str, float] = {}
    for row in deployments:
        name = row["provider_name"]
        provider_cost[name] = round(provider_cost.get(name, 0.0) + row["monthly_cost_usd"], 2)

    infra_cost = infra["kpi"]["monthly_cost_usd"]
    infra_savings = infra["kpi"]["savings_usd"]
    ai_cost = ai_profile["monthly_cost_usd"]
    ai_savings = ai_profile["savings_opportunity_usd"]
    total_cost = round(infra_cost + ai_cost, 2)
    total_savings = round(infra_savings + ai_savings, 2)

    return json_safe({
        "estate": {
            "monthly_cost_usd": total_cost,
            "savings_usd": total_savings,
            "savings_pct": round(100 * total_savings / total_cost, 1) if total_cost else 0.0,
            "resources": infra["kpi"]["resources"] + ai_profile["deployments"],
            "providers": max(infra["kpi"]["providers"], ai_profile["providers"]),
        },
        "infrastructure": {
            "monthly_cost_usd": infra_cost,
            "savings_usd": infra_savings,
            "resources": infra["kpi"]["resources"],
            "actionable": infra["kpi"]["actionable"],
            "idle_resources": infra["kpi"]["idle_resources"],
            "avg_cpu": infra["kpi"]["avg_cpu"],
            "avg_memory": infra["kpi"]["avg_memory"],
            "avg_disk": infra["kpi"]["avg_disk"],
            "avg_network": infra["kpi"]["avg_network"],
            "providers": infra["providers"],
        },
        "ai_services": {
            "monthly_cost_usd": ai_cost,
            "savings_usd": ai_savings,
            "deployments": ai_profile["deployments"],
            "requests": ai_profile["requests"],
            "input_tokens": ai_profile["input_tokens"],
            "output_tokens": ai_profile["output_tokens"],
            "provider_cost": provider_cost,
        },
        "reasoning_mode": LLMReasoner().status(),
        "events": event_summary(),
    })


@app.get("/api/infra/summary")
def infra_summary() -> dict[str, Any]:
    return json_safe(fleet.summary())


@app.get("/api/infra/resource/{resource_id}")
def infra_resource(resource_id: str) -> dict[str, Any]:
    detail = fleet.resource_detail(resource_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Unknown resource: {resource_id}")
    return json_safe(detail)


@app.get("/api/forecast/summary")
def forecast_summary(limit: int = 10) -> dict[str, Any]:
    """Which machines are predicted to breach their threshold in the next day."""
    if forecasting.is_warming():
        return {"warming": True, "forecasts": [], "covered": 0, "predicted_breaches": 0}
    return json_safe({"warming": False, **forecasting.fleet_forecast(limit)})


@app.get("/api/forecast/{resource_id}")
def forecast_resource(resource_id: str) -> dict[str, Any]:
    """Backtest plus 24-hour projection for one machine."""
    result = forecasting.forecast_resource(resource_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"No forecast available for {resource_id}")
    return json_safe(result)


@app.get("/api/capacity/summary")
def capacity_summary() -> dict[str, Any]:
    """Every machine's p90 demand 1 week, 1 month, 3 months and 6 months out."""
    if capacity.is_warming():
        return {"warming": True, "machines": [], "covered": 0}
    return json_safe({"warming": False, **capacity.fleet_capacity()})


@app.get("/api/capacity/{resource_id}")
def capacity_resource(resource_id: str) -> dict[str, Any]:
    """History, p10/p50/p90 bands per horizon, and the decisions they feed."""
    plan = capacity.capacity_plan(resource_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"No capacity history for {resource_id}")
    return json_safe(plan)


@app.get("/api/ai-finops/summary")
def ai_summary() -> dict[str, Any]:
    data = profile()
    deployments = deployment_summary()
    provider_cost: dict[str, float] = {}
    for row in deployments:
        provider_cost[row["provider_name"]] = round(
            provider_cost.get(row["provider_name"], 0) + row["monthly_cost_usd"], 2
        )
    return json_safe({
        "profile": data,
        "provider_cost": provider_cost,
        "deployments": deployments,
        "recommendations": recommendation_rows(),
        "llm": LLMReasoner().status(),
    })


@app.get("/api/dataset-profile")
def dataset_profile() -> dict[str, Any]:
    return json_safe({
        "ai_services": profile(),
        "infrastructure": agent.infra.profiler.profile(),
    })


@app.get("/api/ai-finops/recommendations")
def recommendations(provider: str | None = None) -> dict[str, Any]:
    return json_safe({"recommendations": recommendation_rows(provider)})


@app.get("/api/architecture")
def architecture() -> dict[str, Any]:
    return {
        "main_use_case": "Govern cloud spend across virtual machines and managed AI services without breaking the applications that depend on them.",
        "domains": [
            {
                "key": "infrastructure",
                "name": "Infrastructure FinOps",
                "signals": "CPU, memory, disk, network, workload class, cost, incidents, ownership policy",
                "actions": "Schedule shutdown, scale down, scale up, application review",
            },
            {
                "key": "ai_services",
                "name": "AI service FinOps",
                "signals": "Requests, input/output tokens, cache ratio, latency, errors, quality score",
                "actions": "Smaller model, prompt caching, output limits, batching, tier change, shutdown",
            },
        ],
        "flow": [
            "Cloud telemetry and AI usage metrics",
            "FastAPI ingestion gateway",
            "Persisted event bus",
            "Coordinator agent",
            "Domain analysts and evidence tools",
            "LLM explanation service",
            "Recommendation with evidence",
            "Approval-gated AWS Lambda payload",
        ],
        "service_roles": [
            {"name": "CoreStack / Azure Monitor", "role": "Virtual machine utilization telemetry"},
            {"name": "Amazon Bedrock", "role": "Primary managed AI inference service being analyzed"},
            {"name": "AWS CloudWatch", "role": "Future real source for invocations, tokens, latency and throttles"},
            {"name": "FinOps analysts", "role": "Turn evidence into an explained decision per domain"},
            {"name": "AWS Lambda", "role": "Executes an approved shutdown, resize, model or tier change"},
            {"name": "SQLite", "role": "Normalized demo storage; replaceable with PostgreSQL"},
        ],
    }


@app.get("/api/events")
def events(limit: int = 100) -> dict[str, Any]:
    return json_safe({
        "summary": event_summary(),
        "coordinator": get_coordinator_state(),
        "events": fetch_events(limit=limit),
    })


@app.post("/api/demo-run")
@app.post("/api/ai-finops/demo-run")
def run_demo_events() -> dict[str, Any]:
    """Push one event through each domain so the audit trail shows both paths."""
    ai_profile = profile()
    infra_profile = agent.infra.profiler.profile()

    published = [
        publish_event(
            EVENT_TELEMETRY_RECEIVED,
            source="corestack-vm-adapter",
            payload={
                "dataset": infra_profile["dataset_name"],
                "vm_count": infra_profile["vm_count"],
                "rows_seen": infra_profile["vm_rows"],
                "providers": infra_profile.get("providers", {}),
                "source_type": "corestack_derived_plus_open_trace_patterns",
            },
        ),
        publish_event(
            EVENT_AI_USAGE_RECEIVED,
            source="bedrock-cloudwatch-adapter",
            payload={
                "dataset": ai_profile["dataset_name"],
                "primary_service": "Amazon Bedrock",
                "usage_events": ai_profile["usage_events"],
                "requests": ai_profile["requests"],
                "input_tokens": ai_profile["input_tokens"],
                "output_tokens": ai_profile["output_tokens"],
                "source_type": "synthetic_from_open_trace_patterns",
            },
        ),
    ]
    decisions = event_worker.process_pending(limit=24)
    return json_safe({
        "published_events": published,
        "decisions": decisions,
        "summary": event_summary(),
        "coordinator": get_coordinator_state(),
        "events": fetch_events(limit=40),
    })


@app.post("/api/ai-finops/regenerate")
def regenerate(request: RefreshRequest) -> dict[str, Any]:
    counts = ensure_ai_demo_data(force=request.force)
    datacache.clear()
    return {"regenerated": request.force, "counts": counts}


@app.get("/api/operational/summary")
def operational_summary() -> dict[str, Any]:
    ensure_audit_data()
    with get_connection() as conn:
        agent_runs = int(conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0])
        pipelines = int(conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0])
        actions = int(conn.execute("SELECT COUNT(*) FROM serverless_action_logs").fetchone()[0])
    events_info = event_summary()
    return {
        "agent_runs": agent_runs,
        "pipeline_runs": pipelines,
        "serverless_actions": actions,
        "events": events_info["total_events"],
        "processed_events": events_info["processed_events"],
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")
