"""The single question entry point for the whole platform.

Two analysts exist: one reasons about virtual machines (CPU, memory, disk,
network, cost, incidents), the other about managed LLM inference (tokens, model
tier, quality, caching). A user should not have to know which one owns their
question, so this module routes a plain-English question to one or both, then
flattens their very different result rows into a single `Decision` shape that
the console renders the same way regardless of origin.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from agents.analyst import FinOpsAnalystAgent
from agents.core import action_label, action_tone, infra_lambda_function
from ai_finops.analyst import AIFinOpsAnalystAgent
from ai_finops.llm import LLMReasoner

INFRASTRUCTURE = "infrastructure"
AI_SERVICES = "ai_services"
BOTH = "all"

DOMAIN_LABELS = {
    INFRASTRUCTURE: "Infrastructure",
    AI_SERVICES: "AI services",
    BOTH: "Whole estate",
}

# Routing vocabulary. Multi-word phrases are matched first so "scale up" is not
# scored as a bare "scale", and every term is matched on word boundaries so
# "vm" never fires inside an unrelated word.
INFRA_TERMS = [
    "virtual machine", "virtual machines", "scale up", "scale down", "scale-up", "scale-down",
    "shut down", "shutdown", "power off", "low peak", "off hours", "off-hours", "right size",
    "rightsize", "right-size", "downsize", "instance type", "machine type", "vm sku", "sku",
    # "estate" and "cloud bill" are deliberately absent: they span both domains.
    "vm", "vms", "server", "servers", "host", "hosts", "node", "nodes", "fleet",
    "cpu", "memory", "ram", "disk", "storage", "network", "bandwidth", "utilization",
    "utilisation", "idle", "underutilized", "underutilised", "oversized", "compute",
    "ec2", "instance", "instances", "workload class", "database", "db", "degraded",
    "application health", "infrastructure", "capacity",
]

AI_TERMS = [
    "amazon bedrock", "bedrock", "azure openai", "vertex ai", "prompt caching", "prompt cache",
    "smaller model", "cheaper model", "switch model", "output token", "input token",
    "batch inference", "quality floor", "quality risk", "model tier", "llm", "llms",
    "genai", "gen ai", "token", "tokens", "prompt", "prompts", "inference", "model",
    "models", "openai", "anthropic", "claude", "gpt", "gemini", "nova", "haiku", "sonnet",
    "vertex", "deployment", "deployments", "ai service", "ai services", "ai workload",
    "ai workloads", "caching", "cache",
]

# Offered to the user as starting points. Each one is a question the router can
# answer well, so the chips double as documentation of what the agent knows.
SUGGESTIONS = [
    {"label": "Idle machines to shut down", "question": "Which VMs can be shut down during low peak hours?", "domain": INFRASTRUCTURE},
    {"label": "Oversized machines", "question": "Which VMs need scale down?", "domain": INFRASTRUCTURE},
    {"label": "Machines under pressure", "question": "Which VMs need scale up?", "domain": INFRASTRUCTURE},
    {"label": "Reliability risk", "question": "Which VMs are risky?", "domain": INFRASTRUCTURE},
    {"label": "Degraded applications", "question": "Which applications are degraded?", "domain": INFRASTRUCTURE},
    {"label": "Optimize Bedrock safely", "question": "How can we optimize Amazon Bedrock cost safely?", "domain": AI_SERVICES},
    {"label": "Smaller model candidates", "question": "Which workloads can use a smaller model?", "domain": AI_SERVICES},
    {"label": "Token waste", "question": "Where are we wasting input or output tokens?", "domain": AI_SERVICES},
    {"label": "AI quality risk", "question": "Which AI workloads have quality risk?", "domain": AI_SERVICES},
    {"label": "Total savings available", "question": "Where can we save the most money across the estate?", "domain": BOTH},
    {"label": "What runs automatically", "question": "What will AWS Lambda do with an approved recommendation?", "domain": BOTH},
]


@dataclass
class Decision:
    """One proposal, identical in shape whether it came from a VM or an LLM."""

    id: str
    domain: str
    domain_label: str
    resource: str
    resource_kind: str
    application: str
    provider: str
    environment: str
    action: str
    action_label: str
    tone: str
    savings_usd: float
    monthly_cost_usd: float
    confidence: float
    risk: str
    reason: str
    business_impact: str
    metrics: list[dict[str, Any]] = field(default_factory=list)
    lambda_function: str = ""
    action_payload: dict[str, Any] = field(default_factory=dict)
    approval_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_domain(question: str) -> str:
    """Route on keyword evidence; an ambiguous or generic question hits both."""
    text = question.lower()
    infra = _score(text, INFRA_TERMS)
    ai = _score(text, AI_TERMS)
    if infra and infra > ai:
        return INFRASTRUCTURE
    if ai and ai > infra:
        return AI_SERVICES
    # Tied-but-present means the question genuinely spans both; tied-at-zero is a
    # broad question like "where can we save money" that also deserves both.
    return BOTH


def _score(text: str, terms: list[str]) -> int:
    matched: set[str] = set()
    for term in terms:
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text):
            matched.add(term)
    return len(matched)


class UnifiedFinOpsAgent:
    """Fans a question out to the domain analysts and merges their answers."""

    def __init__(self) -> None:
        self.infra = FinOpsAnalystAgent()
        self.ai = AIFinOpsAnalystAgent()

    def ask(self, question: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = context or {}
        requested = (context.get("domain") or "auto").lower()
        domain = requested if requested in {INFRASTRUCTURE, AI_SERVICES, BOTH} else classify_domain(question)

        routes: list[dict[str, Any]] = []
        decisions: list[Decision] = []

        if domain in {INFRASTRUCTURE, BOTH}:
            answer = self.infra.run(question, {"time_window": context.get("time_window", "latest_48h")})
            rows = [_infra_decision(row, index) for index, row in enumerate(answer.recommendations)]
            decisions.extend(row for row in rows if row is not None)
            routes.append(_route(INFRASTRUCTURE, answer))

        explain = bool(context.get("explain", True))
        if domain in {AI_SERVICES, BOTH}:
            answer = self.ai.run(question, {
                "time_window": context.get("time_window", "latest_30d"),
                "provider": "all",
                "explain": explain,
            })
            decisions.extend(_ai_decision(row, index) for index, row in enumerate(answer.recommendations))
            routes.append(_route(AI_SERVICES, answer))

        decisions.sort(key=lambda item: (item.savings_usd, item.confidence), reverse=True)
        totals = _totals(decisions)

        return {
            "question": question,
            "domain": domain,
            "domain_label": DOMAIN_LABELS[domain],
            "routing": "explicit" if requested in {INFRASTRUCTURE, AI_SERVICES, BOTH} else "auto",
            "answer": _headline(domain, routes, totals),
            "intent": "+".join(route["intent"] for route in routes),
            "decisions": [decision.to_dict() for decision in decisions],
            "totals": totals,
            "routes": routes,
            "tools_used": _dedupe(tool for route in routes for tool in route["tools_used"]),
            "next_action": routes[0]["next_action"] if routes else "",
            "requirement_check": [row for route in routes for row in route["requirement_check"]],
            "suggestions": suggestions_for(domain),
            "reasoning_mode": LLMReasoner().status(),
            "explained": explain,
        }


def suggestions_for(domain: str) -> list[dict[str, str]]:
    """Chips for the ask bar: the active domain first, then the rest."""
    if domain == BOTH:
        return SUGGESTIONS
    preferred = [item for item in SUGGESTIONS if item["domain"] in {domain, BOTH}]
    return preferred + [item for item in SUGGESTIONS if item not in preferred]


def _route(domain: str, answer: Any) -> dict[str, Any]:
    return {
        "domain": domain,
        "domain_label": DOMAIN_LABELS[domain],
        "intent": answer.intent,
        "answer": answer.answer,
        "tools_used": list(answer.tools_used),
        "next_action": answer.next_action,
        "requirement_check": list(answer.requirement_check),
        "evidence": answer.evidence,
    }


def _totals(decisions: list[Decision]) -> dict[str, Any]:
    infra = [item for item in decisions if item.domain == INFRASTRUCTURE]
    ai = [item for item in decisions if item.domain == AI_SERVICES]
    return {
        "decisions": len(decisions),
        "savings_usd": round(sum(item.savings_usd for item in decisions), 2),
        "infrastructure_decisions": len(infra),
        "infrastructure_savings_usd": round(sum(item.savings_usd for item in infra), 2),
        "ai_decisions": len(ai),
        "ai_savings_usd": round(sum(item.savings_usd for item in ai), 2),
    }


def _headline(domain: str, routes: list[dict[str, Any]], totals: dict[str, Any]) -> str:
    """The lead paragraph only.

    When a question spans both domains the per-analyst wording stays on its own
    route so the console can show it as a labelled breakdown, rather than three
    paragraphs concatenated into one wall of text.
    """
    if not routes:
        return "I could not route that question to an analyst."
    if domain != BOTH:
        return routes[0]["answer"]
    return (
        f"Across the whole estate I found {totals['decisions']} decisions worth about "
        f"${totals['savings_usd']:,.2f} per month — ${totals['infrastructure_savings_usd']:,.2f} from "
        f"{totals['infrastructure_decisions']} infrastructure changes and "
        f"${totals['ai_savings_usd']:,.2f} from {totals['ai_decisions']} AI-service changes."
    )


def _dedupe(values: Any) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)


def _metric(label: str, value: Any, detail: str = "") -> dict[str, Any]:
    return {"label": label, "value": value, "detail": detail}


def _infra_decision(row: dict[str, Any], index: int) -> Decision | None:
    """The VM analyst returns three different row shapes; handle each."""
    if "VM" in row:
        return _vm_decision(row, index)
    if "Health Score" in row:
        return _app_health_decision(row, index)
    if "Question Type" in row:
        return _guidance_decision(row, index)
    return None


def _vm_decision(row: dict[str, Any], index: int) -> Decision:
    action = row.get("Recommended Action", "NO_ACTION")
    resource = row["VM"]
    payload = {
        "recommendation_id": f"infra-{resource}",
        "resource_id": resource,
        "resource_type": row.get("Resource Type", "virtual_machine"),
        "provider": row.get("Provider", "azure"),
        "region": row.get("Region", "unknown"),
        "instance_type": row.get("Instance Type", "unknown"),
        "action": action,
        "environment": row.get("Environment", "unknown"),
        "owner": row.get("Owner", "unknown"),
        "approval_required": row.get("Approval Required", "Yes") == "Yes",
        "evidence": {
            "avg_cpu_48h": row.get("Avg CPU 48h"),
            "max_cpu_48h": row.get("Max CPU 48h"),
            "avg_network_48h": row.get("Avg Network 48h"),
            "dynamic_threshold": row.get("Dynamic Threshold"),
            "workload_class": row.get("Workload Class"),
            "incident_count": row.get("Incident Count"),
        },
    }
    return Decision(
        id=f"infra-{index}-{resource}",
        domain=INFRASTRUCTURE,
        domain_label=DOMAIN_LABELS[INFRASTRUCTURE],
        resource=resource,
        resource_kind="Virtual machine",
        application=row.get("Application", "untagged"),
        provider=row.get("Provider", "azure"),
        environment=row.get("Environment", "unknown"),
        action=action,
        action_label=action_label(action),
        tone=action_tone(action),
        savings_usd=float(row.get("Estimated Savings Monthly USD") or 0.0),
        monthly_cost_usd=float(row.get("Estimated Monthly Cost USD") or 0.0),
        confidence=float(row.get("Confidence") or 0.0),
        risk=_infra_risk(row),
        reason=row.get("Reason", ""),
        business_impact=row.get("Business Impact", ""),
        metrics=[
            _metric("Avg CPU (48h)", f"{row.get('Avg CPU 48h', 0):.1f}%", f"threshold {row.get('Dynamic Threshold', 0):.1f}%"),
            _metric("Peak CPU (48h)", f"{row.get('Max CPU 48h', 0):.1f}%"),
            _metric("Avg network (48h)", f"{row.get('Avg Network 48h', 0):.1f}%"),
            _metric("Monthly cost", f"${row.get('Estimated Monthly Cost USD', 0):,.2f}"),
            _metric("Workload class", str(row.get("Workload Class", "unknown")).replace("_", " ")),
            _metric("Incidents", row.get("Incident Count", 0)),
            _metric("Instance type", row.get("Instance Type", "unknown")),
            _metric("Confidence", f"{row.get('Confidence', 0):.0f}%"),
        ],
        lambda_function=infra_lambda_function(action),
        action_payload=payload,
        approval_required=row.get("Approval Required", "Yes") == "Yes",
    )


def _infra_risk(row: dict[str, Any]) -> str:
    if row.get("Risky") or row.get("Business Criticality") == "high":
        return "high"
    if row.get("Environment") == "prod" or row.get("Incident Count", 0):
        return "medium"
    return "low"


def _app_health_decision(row: dict[str, Any], index: int) -> Decision:
    """Application/DB health rows describe an application, not a machine."""
    degraded = row.get("Status") == "Degraded"
    action = "DB_INVESTIGATION" if degraded else "NO_ACTION"
    application = row.get("Application", "unknown")
    return Decision(
        id=f"app-{index}-{application}",
        domain=INFRASTRUCTURE,
        domain_label=DOMAIN_LABELS[INFRASTRUCTURE],
        resource=application,
        resource_kind="Application",
        application=application,
        provider="azure",
        environment="prod",
        action=action,
        action_label=action_label(action),
        tone="serious" if degraded else "good",
        savings_usd=0.0,
        monthly_cost_usd=0.0,
        confidence=float(row.get("Health Score") or 0.0),
        risk="high" if degraded else "low",
        reason=row.get("Reason", ""),
        business_impact=f"Health score {row.get('Health Score', 0)} across {row.get('VM Count', 0)} machines.",
        metrics=[
            _metric("Health score", row.get("Health Score", 0), "0-100, higher is better"),
            _metric("Status", row.get("Status", "unknown")),
            _metric("Avg query latency", f"{row.get('Avg Latency ms', 0):.1f} ms"),
            _metric("Peak query latency", f"{row.get('Max Latency ms', 0):.1f} ms"),
            _metric("Min DB connections", row.get("Min DB Connections", 0)),
            _metric("Avg reads/sec", row.get("Avg Reads/sec", 0)),
            _metric("Machines", row.get("VM Count", 0)),
            _metric("Related incidents", row.get("Related Incidents", 0)),
        ],
        lambda_function=infra_lambda_function(action),
        action_payload={
            "recommendation_id": f"app-{application}",
            "application": application,
            "action": action,
            "health_score": row.get("Health Score"),
            "approval_required": True,
        },
    )


def _guidance_decision(row: dict[str, Any], index: int) -> Decision:
    """"Do I need DB data for this?" returns guidance rows, not resources."""
    question_type = row.get("Question Type", "")
    return Decision(
        id=f"guidance-{index}",
        domain=INFRASTRUCTURE,
        domain_label=DOMAIN_LABELS[INFRASTRUCTURE],
        resource=question_type,
        resource_kind="Data requirement",
        application="platform",
        provider="platform",
        environment="n/a",
        action="NO_ACTION",
        action_label=f"DB required: {row.get('DB Required', 'unknown')}",
        tone="neutral",
        savings_usd=0.0,
        monthly_cost_usd=0.0,
        confidence=0.0,
        risk="low",
        reason=row.get("Why", ""),
        business_impact=row.get("Other Required Context", ""),
        metrics=[
            _metric("DB required", row.get("DB Required", "unknown")),
            _metric("Other context needed", row.get("Other Required Context", "")),
        ],
        lambda_function="",
        action_payload={},
        approval_required=False,
    )


def _ai_decision(row: dict[str, Any], index: int) -> Decision:
    action = row.get("Recommended Action", "NO_ACTION")
    evidence = row.get("Evidence") or {}
    quality = float(evidence.get("quality_score") or 0.0)
    floor = float(evidence.get("quality_floor") or 0.0)
    return Decision(
        id=f"ai-{index}-{row.get('Deployment', 'deployment')}",
        domain=AI_SERVICES,
        domain_label=DOMAIN_LABELS[AI_SERVICES],
        resource=row.get("Deployment", "deployment"),
        resource_kind="AI deployment",
        application=row.get("Application", "unknown"),
        provider=str(row.get("Provider", "AWS")).lower().replace("microsoft ", "").replace("google ", "").split()[0],
        environment=row.get("Environment", "unknown"),
        action=action,
        action_label=action_label(action),
        tone=action_tone(action),
        savings_usd=float(row.get("Estimated Savings Monthly USD") or 0.0),
        monthly_cost_usd=float(evidence.get("monthly_cost_usd") or 0.0),
        confidence=float(row.get("Confidence") or 0.0),
        risk=str(row.get("Quality Risk", "low")),
        reason=row.get("Reason", ""),
        business_impact=row.get("Business Impact", ""),
        metrics=[
            _metric("Monthly cost", f"${evidence.get('monthly_cost_usd', 0):,.2f}"),
            _metric("Requests (30d)", f"{int(evidence.get('requests_30d') or 0):,}"),
            _metric("Input tokens (30d)", f"{int(evidence.get('input_tokens_30d') or 0):,}"),
            _metric("Output tokens (30d)", f"{int(evidence.get('output_tokens_30d') or 0):,}"),
            _metric("Quality", f"{quality:.2f}", f"floor {floor:.2f}"),
            _metric("P95 latency", f"{float(evidence.get('latency_p95_ms') or 0):.0f} ms"),
            _metric("Error rate", f"{float(evidence.get('error_rate_pct') or 0):.2f}%"),
            _metric("Current model", row.get("Current Model", "unknown")),
        ],
        lambda_function=row.get("Lambda Function", ""),
        action_payload=row.get("Action Payload") or {},
    )
