"""Coordinator Agent for event-driven FinOps orchestration.

The coordinator is intentionally small for Phase 4. It consumes event envelopes,
chooses the internal tool/agent path, publishes downstream events, and writes an
audit trail. In production this boundary can move to LangGraph + Celery/Redis.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from agents.analyst import FinOpsAnalystAgent
from agents.core import AgentResult, infra_lambda_function
from agents.forecasting import fleet_forecast
from agents.storage import get_connection, init_db, insert_agent_run
from ai_finops.analyst import AIFinOpsAnalystAgent
from events.schemas import (
    EVENT_AI_COST_ANALYZED,
    EVENT_AI_RECOMMENDATION_CREATED,
    EVENT_AI_USAGE_RECEIVED,
    EVENT_FORECAST_COMPLETED,
    EVENT_LAMBDA_ACTION_CREATED,
    EVENT_PIPELINE_FAILED,
    EVENT_RECOMMENDATION_CREATED,
    EVENT_SERVERLESS_ACTION_CREATED,
    EVENT_TELEMETRY_RECEIVED,
)
from events.store import publish_event


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def duration_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class CoordinatorAgent:
    name = "Coordinator Agent"

    def __init__(self) -> None:
        self.analyst = FinOpsAnalystAgent()
        self.ai_analyst = AIFinOpsAnalystAgent()

    def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        event_type = event["event_type"]
        if event_type == EVENT_TELEMETRY_RECEIVED:
            return self._handle_telemetry(event)
        if event_type == EVENT_FORECAST_COMPLETED:
            return self._handle_forecast(event)
        if event_type == EVENT_RECOMMENDATION_CREATED:
            return self._handle_recommendation(event)
        if event_type == EVENT_PIPELINE_FAILED:
            return self._handle_pipeline_failure(event)
        if event_type == EVENT_SERVERLESS_ACTION_CREATED:
            return self._handle_serverless_action(event)
        if event_type == EVENT_AI_USAGE_RECEIVED:
            return self._handle_ai_usage(event)
        if event_type == EVENT_AI_COST_ANALYZED:
            return self._handle_ai_cost(event)
        if event_type == EVENT_AI_RECOMMENDATION_CREATED:
            return self._handle_ai_recommendation(event)
        if event_type == EVENT_LAMBDA_ACTION_CREATED:
            return self._handle_serverless_action(event)
        return self._ignore_event(event)

    def _handle_telemetry(self, event: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        profile = self.analyst.profiler.profile()
        payload = event["payload"]

        # This used to publish "forecasting stage completed for demo scope" with
        # no model behind it. It now carries the real projection, or says
        # plainly that the forecast is still training.
        forecast = fleet_forecast()
        if forecast.get("forecasts"):
            breaches = forecast["predicted_breaches"]
            forecast_summary = (
                f"Forecast complete for {forecast['covered']} of {forecast['total']} machines "
                f"({forecast['selection']}); {breaches} predicted to breach within 24 hours."
            )
        else:
            forecast_summary = "Forecast models are still training; projection unavailable this cycle."

        publish_event(
            EVENT_FORECAST_COMPLETED,
            source=self.name,
            correlation_id=event["correlation_id"],
            payload={
                "trigger_event_id": event["event_id"],
                "dataset": profile["dataset_name"],
                "vm_count": profile["vm_count"],
                "rows_seen": payload.get("rows_seen", profile["vm_rows"]),
                "forecast_scope": "24h_peak_cpu",
                "machines_forecast": forecast.get("covered", 0),
                "predicted_breaches": forecast.get("predicted_breaches", 0),
                "at_risk": [row["resource"] for row in forecast.get("forecasts", []) if row["will_breach"]],
                "summary": forecast_summary,
            },
        )
        summary = f"Telemetry event accepted for {profile['vm_count']} VMs; {forecast_summary}"
        self._audit(summary, profile["vm_rows"], ["Dataset profile refreshed", forecast_summary], start)
        return {"status": "processed", "summary": summary, "published": [EVENT_FORECAST_COMPLETED]}

    def _handle_forecast(self, event: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        answer = self.analyst.run("Which VMs can be shut down during low peak hours?")
        recommendations = answer.recommendations[:5]
        publish_event(
            EVENT_RECOMMENDATION_CREATED,
            source=self.name,
            correlation_id=event["correlation_id"],
            payload={
                "trigger_event_id": event["event_id"],
                "intent": answer.intent,
                "recommendation_count": len(answer.recommendations),
                "top_recommendations": recommendations,
                "evidence": answer.evidence,
                "summary": answer.answer,
            },
        )
        summary = f"Forecast event converted into {len(answer.recommendations)} recommendation candidates."
        self._audit(summary, len(answer.recommendations), ["Recommendation event published", answer.answer], start)
        return {"status": "processed", "summary": summary, "published": [EVENT_RECOMMENDATION_CREATED]}

    def _handle_recommendation(self, event: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        recs = event["payload"].get("top_recommendations", [])
        published = []
        for rec in recs[:3]:
            if rec.get("Recommended Action") in {"SCHEDULE_SHUTDOWN", "SCALE_DOWN", "APPLICATION_REVIEW"}:
                publish_event(
                    EVENT_SERVERLESS_ACTION_CREATED,
                    source=self.name,
                    correlation_id=event["correlation_id"],
                    payload={
                        "trigger_event_id": event["event_id"],
                        "function_name": self._function_name(rec.get("Recommended Action")),
                        "resource_id": rec.get("VM"),
                        "application": rec.get("Application"),
                        "action": rec.get("Recommended Action"),
                        "reason": rec.get("Reason"),
                        "estimated_savings_monthly_usd": rec.get("Estimated Savings Monthly USD", 0),
                        "approval_required": rec.get("Approval Required"),
                    },
                )
                published.append(EVENT_SERVERLESS_ACTION_CREATED)
        summary = f"Recommendation event routed to {len(published)} serverless action payloads."
        self._audit(summary, len(recs), ["Serverless action events published", f"Actions created: {len(published)}"], start)
        return {"status": "processed", "summary": summary, "published": published}

    def _handle_pipeline_failure(self, event: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        payload = event["payload"]
        publish_event(
            EVENT_SERVERLESS_ACTION_CREATED,
            source=self.name,
            correlation_id=event["correlation_id"],
            payload={
                "trigger_event_id": event["event_id"],
                "function_name": "finops-pipeline-alert-lambda",
                "resource_id": payload.get("pipeline_name", "pipeline"),
                "application": "platform-ops",
                "action": "PIPELINE_INVESTIGATION",
                "reason": payload.get("failure_reason", "Pipeline failed"),
                "estimated_savings_monthly_usd": 0,
                "approval_required": "No",
            },
        )
        summary = f"Pipeline failure routed to alert action: {payload.get('pipeline_name', 'unknown pipeline')}."
        self._audit(summary, 1, ["pipeline.failed event handled", "serverless alert event published"], start)
        return {"status": "processed", "summary": summary, "published": [EVENT_SERVERLESS_ACTION_CREATED]}

    def _handle_serverless_action(self, event: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        payload = event["payload"]
        status = "success" if payload.get("approval_required") != "blocked" else "failed"
        response = self._response_message(payload, status)
        with get_connection() as conn:
            init_db(conn)
            conn.execute(
                """
                INSERT INTO serverless_action_logs (
                    function_name, trigger_type, resource_id, application,
                    status, duration_ms, payload, response_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.get("function_name", "finops-action-lambda"),
                    "event_bus",
                    payload.get("resource_id"),
                    payload.get("application"),
                    status,
                    duration_ms(start),
                    json.dumps(payload),
                    response,
                    utc_now(),
                ),
            )
            conn.commit()
        summary = f"Serverless action logged for {payload.get('resource_id', 'unknown resource')}."
        self._audit(summary, 1, [payload.get("function_name", "finops-action-lambda"), response], start)
        return {"status": "processed", "summary": summary, "published": []}

    def _ignore_event(self, event: dict[str, Any]) -> dict[str, Any]:
        summary = f"No coordinator route configured for {event['event_type']}."
        return {"status": "ignored", "summary": summary, "published": []}

    def _audit(self, summary: str, records: int, insights: list[str], start: float) -> None:
        result = AgentResult(
            agent_name=self.name,
            status="success",
            summary=summary,
            records_processed=records,
            generated_insights=insights,
            duration_ms=duration_ms(start),
        )
        with get_connection() as conn:
            init_db(conn)
            insert_agent_run(conn, result)

    def _function_name(self, action: str | None) -> str:
        return infra_lambda_function(action)

    def _response_message(self, payload: dict[str, Any], status: str) -> str:
        if status == "failed":
            return "Action failed and requires manual review."
        action = payload.get("action", "ACTION")
        resource = payload.get("resource_id", "resource")
        return f"{action} payload accepted for {resource}."
