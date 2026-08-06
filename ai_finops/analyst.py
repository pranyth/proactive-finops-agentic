"""AI FinOps analyst for managed LLM inference services."""

from __future__ import annotations

from typing import Any

from agents.core import AgentAnswer
from ai_finops.llm import LLMReasoner, LLMResult
from ai_finops.storage import deployment_summary, ensure_ai_demo_data, profile, recommendation_rows


class AIFinOpsAnalystAgent:
    """One query entry point backed by structured evidence and optional LLM reasoning."""

    def __init__(self) -> None:
        ensure_ai_demo_data()
        self.llm = LLMReasoner()

    def run(self, question: str, context: dict[str, Any] | None = None) -> AgentAnswer:
        context = context or {"time_window": "latest_30d", "provider": "all"}
        intent = self._classify(question)
        data_profile = profile()
        summaries = deployment_summary()
        recs = recommendation_rows("aws" if intent == "optimize_bedrock" else None)
        selected = self._select(intent, question, recs, summaries)
        baseline, next_action = self._baseline(intent, selected, summaries)
        evidence = self._evidence(intent, selected, summaries, data_profile)
        # A local model takes seconds to write the final paragraph. The console
        # asks for the evidence answer first so decisions render immediately,
        # then re-asks with explain=True to swap in the generated wording.
        llm_result = (
            self.llm.explain(question, evidence, baseline)
            if context.get("explain", True)
            else LLMResult(baseline, "evidence_policy_fallback", "none")
        )
        evidence["reasoning_runtime"] = {
            "mode": llm_result.mode,
            "model": llm_result.model,
            "fallback_reason": llm_result.error,
        }
        return AgentAnswer(
            answer=llm_result.text,
            intent=intent,
            dataset_profile=data_profile,
            requirement_check=self._requirements(intent, data_profile),
            recommendations=[self._public_row(row) for row in selected],
            evidence=evidence,
            tools_used=[
                "AI Dataset Profiler",
                "Cost and Token Analytics",
                "Quality Guardrail",
                "Recommendation Policy",
                "LLM Explanation Service" if llm_result.mode == "llm" else "Evidence Explanation Fallback",
                "AWS Lambda Action Builder",
            ],
            next_action=next_action,
            context=context,
        )

    def _classify(self, question: str) -> str:
        q = question.lower()
        if "lambda" in q or "automate" in q or "action payload" in q:
            return "lambda_actions"
        if "why" in q or "explain" in q:
            return "explain_recommendation"
        if "bedrock" in q or "aws ai" in q:
            return "optimize_bedrock"
        if "smaller" in q or "cheaper model" in q or "switch model" in q:
            return "model_rightsizing"
        if "token" in q or "cache" in q or "prompt" in q or "output" in q:
            return "token_efficiency"
        if "quality" in q or "risk" in q or "reliable" in q:
            return "quality_risk"
        if "cost" in q or "spend" in q or "expensive" in q or "saving" in q:
            return "cost_optimization"
        if "provider" in q or "service" in q or "model" in q:
            return "service_overview"
        return "ai_finops_overview"

    def _select(
        self,
        intent: str,
        question: str,
        recs: list[dict[str, Any]],
        summaries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        actionable = [row for row in recs if row["action"] != "NO_ACTION"]
        if intent == "model_rightsizing":
            return [row for row in actionable if row["action"] in {"SWITCH_TO_SMALLER_MODEL", "REDUCE_OUTPUT_TOKENS"}][:8]
        if intent == "token_efficiency":
            return [row for row in actionable if row["action"] in {"ENABLE_PROMPT_CACHING", "REDUCE_OUTPUT_TOKENS", "BATCH_REQUESTS"}][:8]
        if intent == "quality_risk":
            high_risk = [row for row in recs if row["criticality"] == "high" or row["quality_risk"] == "medium"]
            return high_risk[:8]
        if intent == "lambda_actions":
            return actionable[:8]
        if intent == "explain_recommendation":
            q = question.lower()
            matched = [row for row in recs if row["deployment_key"].lower() in q or row["application"].lower() in q]
            return (matched or actionable)[:1]
        if intent == "service_overview":
            return recs[:8]
        return actionable[:8]

    def _baseline(self, intent: str, rows: list[dict[str, Any]], summaries: list[dict[str, Any]]) -> tuple[str, str]:
        savings = sum(float(row["estimated_monthly_savings_usd"]) for row in rows)
        if intent == "optimize_bedrock":
            text = f"Amazon Bedrock is the primary AI-service test case. I found {len(rows)} actionable Bedrock decisions worth about ${savings:,.2f} per month, led by model rightsizing, prompt caching, and removal of idle reserved capacity."
        elif intent == "model_rightsizing":
            text = f"I found {len(rows)} workloads that can test a smaller model or output limit, with estimated savings of ${savings:,.2f} per month. Each production change requires a canary quality evaluation first."
        elif intent == "token_efficiency":
            text = f"I found {len(rows)} token-efficiency opportunities worth approximately ${savings:,.2f} per month. The strongest options are prompt caching, output-token limits, and batch inference."
        elif intent == "quality_risk":
            text = f"I found {len(rows)} decisions where quality or business criticality must constrain cost optimization. High-criticality workloads remain protected even when a cheaper model exists."
        elif intent == "lambda_actions":
            text = f"There are {len(rows)} proposed actions ready to be converted into AWS Lambda payloads. Lambda performs the approved configuration change; it does not make the FinOps decision itself."
        elif intent == "explain_recommendation" and rows:
            row = rows[0]
            text = f"{row['deployment_key']} received {row['action']} because {row['reason']} Estimated savings are ${row['estimated_monthly_savings_usd']:,.2f} per month with {row['quality_risk']} quality risk."
        elif intent == "service_overview":
            text = "The platform currently analyzes managed LLM inference across Amazon Bedrock, Azure OpenAI, and Vertex AI. Amazon Bedrock is the primary demo service and the schema supports additional AI categories later."
        else:
            text = f"Across managed AI services, I found {len(rows)} actionable cost decisions worth about ${savings:,.2f} per month. Recommendations balance token cost, latency, quality, application criticality, and operating tier."
        return text, "Review evidence and quality risk, then approve an AWS Lambda action only for validated recommendations."

    def _evidence(
        self,
        intent: str,
        rows: list[dict[str, Any]],
        summaries: list[dict[str, Any]],
        data_profile: dict[str, Any],
    ) -> dict[str, Any]:
        by_provider: dict[str, dict[str, float]] = {}
        for row in summaries:
            bucket = by_provider.setdefault(row["provider_name"], {"cost_usd": 0.0, "requests": 0})
            bucket["cost_usd"] += float(row["monthly_cost_usd"])
            bucket["requests"] += int(row["requests_30d"])
        for bucket in by_provider.values():
            bucket["cost_usd"] = round(bucket["cost_usd"], 2)
        return {
            "intent": intent,
            "service_category": "managed_llm_inference",
            "primary_service": "Amazon Bedrock",
            "provider_summary": by_provider,
            "selected_recommendations": len(rows),
            "estimated_monthly_savings_usd": round(sum(float(row["estimated_monthly_savings_usd"]) for row in rows), 2),
            "total_monthly_cost_usd": data_profile["monthly_cost_usd"],
            "quality_rule": "A cheaper option is never auto-approved when expected quality is below the application's configured floor.",
            "automation_rule": "Lambda payloads are proposals until human approval; production changes are not executed by this demo.",
            "top_evidence": [
                {
                    "deployment": row["deployment_key"],
                    "action": row["action"],
                    "savings_usd": row["estimated_monthly_savings_usd"],
                    "confidence": row["confidence"],
                    "quality_risk": row["quality_risk"],
                    **row["evidence"],
                }
                for row in rows[:5]
            ],
        }

    def _requirements(self, intent: str, data_profile: dict[str, Any]) -> list[dict[str, str]]:
        requirements = [
            ("AI invocation count", "Available"),
            ("Input/output tokens", "Available"),
            ("Model and provider", "Available"),
            ("Cost rates", "Available - illustrative reference rates"),
            ("Latency, errors and throttles", "Available"),
            ("Application criticality", "Available - synthetic business context"),
            ("Quality evaluation", "Available - synthetic evaluation score"),
            ("CoreStack AI billing", "Not available and not required for demo"),
            ("Raw prompts or customer content", "Not required and intentionally excluded"),
            ("Real LLM API key", "Optional for generated explanation; policy fallback remains functional"),
        ]
        return [{"Requirement": name, "Status": status} for name, status in requirements]

    def _public_row(self, row: dict[str, Any]) -> dict[str, Any]:
        evidence = row["evidence"]
        payload = {
            "recommendation_id": row["recommendation_key"],
            "deployment": row["deployment_key"],
            "provider": row["provider_name"],
            "service": row["ai_service"],
            "current_model": row["current_model"],
            "target_model": row["target_model_key"],
            "action": row["action"],
            "region": row["region"],
            "approval_required": True,
            "evidence": evidence,
        }
        return {
            "Recommendation ID": row["recommendation_key"],
            "Deployment": row["deployment_key"],
            "Application": row["application"],
            "Provider": row["provider_name"],
            "AI Service": row["ai_service"],
            "Current Model": row["current_model"],
            "Recommended Action": row["action"],
            "Target Model": row["target_model_key"] or "No model change",
            "Environment": row["environment"],
            "Business Criticality": row["criticality"],
            "Region": row["region"],
            "Service Tier": row["service_tier"],
            "Confidence": row["confidence"],
            "Estimated Savings Monthly USD": row["estimated_monthly_savings_usd"],
            "Quality Risk": row["quality_risk"],
            "Business Impact": row["business_impact"],
            "Reason": row["reason"],
            "Evidence": evidence,
            "Lambda Function": row["lambda_function"],
            "Action Payload": payload,
        }

