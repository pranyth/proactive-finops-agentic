"""AI-service routes layered onto the existing background coordinator."""

from __future__ import annotations

import json
import time
from typing import Any

from agents.storage import get_connection
from agents.coordinator import CoordinatorAgent as BaseCoordinator
from ai_finops.storage import init_ai_schema
from events.schemas import (
    EVENT_AI_COST_ANALYZED,
    EVENT_AI_RECOMMENDATION_CREATED,
    EVENT_LAMBDA_ACTION_CREATED,
)
from events.store import publish_event


class CoordinatorAgent(BaseCoordinator):
    """Consumes AI usage and produces cost, recommendation and Lambda events."""

    def _handle_ai_usage(self, event: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        profile = self.ai_analyst.run("Summarize AI service cost").dataset_profile
        publish_event(
            EVENT_AI_COST_ANALYZED,
            source=self.name,
            correlation_id=event["correlation_id"],
            payload={
                "trigger_event_id": event["event_id"],
                "usage_events": profile["usage_events"],
                "requests": profile["requests"],
                "monthly_cost_usd": profile["monthly_cost_usd"],
                "primary_service": profile["primary_service"],
            },
        )
        summary = f"AI usage profiled across {profile['deployments']} deployments; cost analysis published."
        self._audit(summary, profile["usage_events"], ["Token and cost evidence loaded", EVENT_AI_COST_ANALYZED], start)
        return {"status": "processed", "summary": summary, "published": [EVENT_AI_COST_ANALYZED]}

    def _handle_ai_cost(self, event: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        answer = self.ai_analyst.run("How can we optimize Amazon Bedrock cost safely?")
        publish_event(
            EVENT_AI_RECOMMENDATION_CREATED,
            source=self.name,
            correlation_id=event["correlation_id"],
            payload={
                "trigger_event_id": event["event_id"],
                "intent": answer.intent,
                "recommendation_count": len(answer.recommendations),
                "recommendations": answer.recommendations[:5],
                "summary": answer.answer,
            },
        )
        summary = f"Cost evidence converted into {len(answer.recommendations)} Bedrock recommendations."
        self._audit(summary, len(answer.recommendations), ["Quality guardrail applied", EVENT_AI_RECOMMENDATION_CREATED], start)
        return {"status": "processed", "summary": summary, "published": [EVENT_AI_RECOMMENDATION_CREATED]}

    def _handle_ai_recommendation(self, event: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        recs = event["payload"].get("recommendations", [])
        published = []
        for rec in recs[:3]:
            publish_event(
                EVENT_LAMBDA_ACTION_CREATED,
                source=self.name,
                correlation_id=event["correlation_id"],
                payload={
                    "trigger_event_id": event["event_id"],
                    "function_name": rec.get("Lambda Function", "finops-bedrock-review-lambda"),
                    "resource_id": rec.get("Deployment"),
                    "application": rec.get("Application"),
                    "action": rec.get("Recommended Action"),
                    "reason": rec.get("Reason"),
                    "estimated_savings_monthly_usd": rec.get("Estimated Savings Monthly USD", 0),
                    "approval_required": "Yes",
                    "action_payload": rec.get("Action Payload", {}),
                },
            )
            published.append(EVENT_LAMBDA_ACTION_CREATED)
        summary = f"Created {len(published)} approval-gated AWS Lambda action payloads."
        self._audit(summary, len(recs), ["No production change executed", EVENT_LAMBDA_ACTION_CREATED], start)
        return {"status": "processed", "summary": summary, "published": published}

    def _handle_serverless_action(self, event: dict[str, Any]) -> dict[str, Any]:
        result = super()._handle_serverless_action(event)
        payload = event["payload"]
        action_payload = payload.get("action_payload") or {}
        recommendation_key = action_payload.get("recommendation_id")
        if not recommendation_key:
            return result
        with get_connection() as conn:
            init_ai_schema(conn)
            recommendation = conn.execute(
                "SELECT id FROM ai_recommendations WHERE recommendation_key = ?",
                (recommendation_key,),
            ).fetchone()
            if recommendation:
                conn.execute(
                    """INSERT INTO ai_action_history (
                        recommendation_id, lambda_function, action_payload, status, created_at
                    ) VALUES (?, ?, ?, ?, ?)""",
                    (
                        recommendation["id"], payload.get("function_name", "finops-bedrock-review-lambda"),
                        json.dumps(action_payload), "proposed", event["created_at"],
                    ),
                )
                conn.commit()
        return result

