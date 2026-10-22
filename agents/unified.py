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

from agents import capacity
from agents.analyst import FinOpsAnalystAgent
from agents.core import action_label, action_tone, infra_lambda_function
from ai_finops.analyst import AIFinOpsAnalystAgent
from ai_finops.llm import LLMReasoner

INFRASTRUCTURE = "infrastructure"
AI_SERVICES = "ai_services"
BOTH = "all"
CAPACITY = "capacity"

DOMAIN_LABELS = {
    INFRASTRUCTURE: "Infrastructure",
    AI_SERVICES: "AI services",
    BOTH: "Whole estate",
    CAPACITY: "Capacity plan",
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

# A question about the future goes to the capacity forecaster, whatever else it
# mentions: "which VMs will run out of CPU in 3 months" is a forecast, not a
# rightsizing question.
FORECAST_TERMS = [
    "forecast", "forecasts", "predict", "predicted", "prediction", "projected", "projection",
    "next week", "next month", "next quarter", "next year", "coming months", "1 week", "one week",
    "1 month", "one month", "3 months", "three months", "6 months", "six months", "run out",
    "running out", "will need", "capacity plan", "capacity planning", "growth", "trend", "trending",
    "savings plan", "reserved instance", "reserved instances", "commit", "commitment", "commitments",
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
    {"label": "Running out of capacity", "question": "Which machines will run out of capacity in the next 3 months?", "domain": CAPACITY},
    {"label": "Safe commitments", "question": "Where is it safe to commit to a 1-year savings plan?", "domain": CAPACITY},
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
    if _score(text, FORECAST_TERMS):
        return CAPACITY
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
        domain = requested if requested in DOMAIN_LABELS else classify_domain(question)

        routes: list[dict[str, Any]] = []
        decisions: list[Decision] = []

        explain = bool(context.get("explain", True))
        # A whole-estate question is summarised once at the end, so the analysts
        # run in evidence mode and the single LLM call is spent on the headline.
        explain_route = explain and domain != BOTH

        if domain in {INFRASTRUCTURE, BOTH}:
            answer = self.infra.run(question, {
                "time_window": context.get("time_window", "latest_48h"),
                "explain": explain_route,
            })
            rows = [_infra_decision(row, index) for index, row in enumerate(answer.recommendations)]
            decisions.extend(row for row in rows if row is not None)
            routes.append(_route(INFRASTRUCTURE, answer))

        if domain in {AI_SERVICES, BOTH}:
            answer = self.ai.run(question, {
                "time_window": context.get("time_window", "latest_30d"),
                "provider": "all",
                "explain": explain_route,
            })
            decisions.extend(_ai_decision(row, index) for index, row in enumerate(answer.recommendations))
            routes.append(_route(AI_SERVICES, answer))

        if domain == CAPACITY:
            route, rows = _capacity_route(question, explain)
            routes.append(route)
            # Already ordered by urgency; a scale-up saves nothing but outranks any commitment.
            decisions.extend(rows)
        else:
            decisions.sort(key=lambda item: (item.savings_usd, item.confidence), reverse=True)
        totals = _totals(decisions)
        headline, headline_mode = _headline(domain, routes, totals, question, explain)
        tools = _dedupe(tool for route in routes for tool in route["tools_used"])
        if domain == BOTH and headline_mode == "llm":
            # The analysts ran in evidence mode for a merged question; the model
            # wrote the paragraph the user actually reads, so label it that way.
            tools = [t for t in tools if t != "Evidence Explanation Fallback"]
            if "LLM Explanation Service" not in tools:
                tools.append("LLM Explanation Service")

        return {
            "question": question,
            "domain": domain,
            "domain_label": DOMAIN_LABELS[domain],
            "routing": "explicit" if requested in DOMAIN_LABELS else "auto",
            "answer": headline,
            "intent": "+".join(route["intent"] for route in routes),
            "decisions": [decision.to_dict() for decision in decisions],
            "totals": totals,
            "routes": routes,
            "tools_used": tools,
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
    planned = [item for item in decisions if item.domain == CAPACITY]
    return {
        "capacity_decisions": len(planned),
        "capacity_savings_usd": round(sum(item.savings_usd for item in planned), 2),
        "decisions": len(decisions),
        "savings_usd": round(sum(item.savings_usd for item in decisions), 2),
        "infrastructure_decisions": len(infra),
        "infrastructure_savings_usd": round(sum(item.savings_usd for item in infra), 2),
        "ai_decisions": len(ai),
        "ai_savings_usd": round(sum(item.savings_usd for item in ai), 2),
    }


def _headline(domain: str, routes: list[dict[str, Any]], totals: dict[str, Any],
              question: str = "", explain: bool = True) -> tuple[str, str]:
    """The lead paragraph only.

    When a question spans both domains the per-analyst wording stays on its own
    route so the console can show it as a labelled breakdown, rather than three
    paragraphs concatenated into one wall of text. A single-domain question is
    already worded by its analyst; only the merged case needs writing here.
    """
    if not routes:
        return "I could not route that question to an analyst.", "none"
    if domain != BOTH:
        mode = "llm" if "LLM Explanation Service" in routes[0]["tools_used"] else "evidence_policy_fallback"
        return routes[0]["answer"], mode
    baseline = (
        f"Across the whole estate I found {totals['decisions']} decisions worth about "
        f"${totals['savings_usd']:,.2f} per month — ${totals['infrastructure_savings_usd']:,.2f} from "
        f"{totals['infrastructure_decisions']} infrastructure changes and "
        f"${totals['ai_savings_usd']:,.2f} from {totals['ai_decisions']} AI-service changes."
    )
    if not explain:
        return baseline, "evidence_policy_fallback"
    evidence = {
        "totals": totals,
        "per_domain": [
            {"domain": route["domain_label"], "finding": route["answer"]} for route in routes
        ],
    }
    result = LLMReasoner().explain(question, evidence, baseline)
    return result.text, result.mode


def _capacity_route(question: str, explain: bool) -> tuple[dict[str, Any], list[Decision]]:
    """Forecast every machine 1 week to 6 months out and turn the bands into decisions."""
    tools = ["Capacity Forecaster (trend + quantile boosting)", "Decision Mapper"]
    if capacity.is_warming():
        answer = "The capacity models are still training; ask again in a minute."
        return _capacity_route_dict(answer, tools, {}), []
    fleet = capacity.fleet_capacity()
    inventory = capacity.inventory()
    decisions = [
        _capacity_decision(machine, decision, inventory.get(machine["resource"], {}), index)
        for index, (machine, decision) in enumerate(
            (machine, decision) for machine in fleet["machines"] for decision in machine["decisions"])
    ]
    # A commitment question leads with commitments; anything else leads with risk.
    wants_commitments = _score(question.lower(), ["commit", "commitment", "savings plan", "reserved instance",
                                                  "reserved instances"]) > 0
    decisions.sort(key=lambda d: (d.action == "COMMIT_CAPACITY") != wants_commitments)
    breaching = fleet["breaching"]
    upcoming = sum(v for k, v in breaching.items() if k != "now")
    baseline = (
        f"{breaching['now']} of {fleet['covered']} machines are already over {capacity.BREACH_PCT:.0f}% of "
        f"capacity and need scaling now. The forecast flags {upcoming} more that are fine today but cross the "
        f"line at the 90th percentile: {breaching['1 week']} within a week, {breaching['1 month']} within a "
        f"month, {breaching['3 months']} within three months and {breaching['6 months']} within six. "
        f"Separately, machines whose six-month demand floor is stable can go on 1-year savings plans for "
        f"about ${fleet['commitment_savings_usd']:,.2f} per month."
    )
    evidence = {
        "machines_total": fleet["covered"],
        "already_over_80_pct_today": breaching["now"],
        "fine_today_but_cross_80_pct": {
            "within_1_week": breaching["1 week"], "within_1_month": breaching["1 month"],
            "within_3_months": breaching["3 months"], "within_6_months": breaching["6 months"],
        },
        "unrelated_saving_from_1_year_savings_plans_usd_per_month": fleet["commitment_savings_usd"],
    }
    answer, mode = baseline, "evidence_policy_fallback"
    if explain:
        result = LLMReasoner().explain(question, evidence, baseline)
        answer, mode = result.text, result.mode
    tools.append("LLM Explanation Service" if mode == "llm" else "Evidence Explanation Fallback")
    return _capacity_route_dict(answer, tools, evidence), decisions


def _capacity_route_dict(answer: str, tools: list[str], evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "domain": CAPACITY, "domain_label": DOMAIN_LABELS[CAPACITY], "intent": "capacity_forecast",
        "answer": answer, "tools_used": tools, "evidence": evidence, "requirement_check": [],
        "next_action": "Open the Capacity tab to see each machine's 1-week to 6-month band.",
    }


def _capacity_decision(machine: dict[str, Any], decision: dict[str, Any], inv: dict[str, Any],
                       index: int) -> Decision:
    action = decision["action"]
    urgent = machine["first_breach"] in {"now", "1 week", "1 month"}
    payload = {
        "recommendation_id": f"capacity-{machine['resource']}-{action.lower()}",
        "resource_id": machine["resource"],
        "action": action,
        "horizon": decision["horizon"],
        "owner": inv.get("app_owner") or inv.get("owner_team", "unknown"),
        "approval_required": True,
        "evidence": {
            "current_weekly_peak_pct": machine["current_peak"],
            "p90_demand_pct_by_horizon": machine["p90"],
            "trend_pct_per_month": machine["trend_per_month"],
            "days_to_breach": machine["days_to_breach"],
        },
    }
    return Decision(
        id=f"capacity-{index}",
        domain=CAPACITY,
        domain_label=DOMAIN_LABELS[CAPACITY],
        resource=machine["resource"],
        resource_kind="virtual_machine",
        application=inv.get("application", "unknown"),
        provider=inv.get("cloud_provider", "unknown"),
        environment=inv.get("environment", "unknown"),
        action=action,
        action_label=action_label(action),
        tone=action_tone(action),
        savings_usd=decision["savings_usd"],
        monthly_cost_usd=machine["monthly_cost_usd"],
        # Both decisions read a 90% bound: p90 for a breach, p10 for a floor.
        confidence=0.9,
        risk="high" if action != "COMMIT_CAPACITY" and urgent else "medium" if action == "PLAN_SCALE_UP" else "low",
        reason=decision["reason"],
        business_impact=("Outage risk if nothing changes." if action in {"PLAN_SCALE_UP", "SCALE_UP"}
                         else "Lower unit price on capacity the forecast says will be used."),
        metrics=[_metric("Peak now", f"{machine['current_peak']}%")]
        + [_metric(f"p90 in {label}", f"{value}%") for label, value in machine["p90"].items()]
        + [_metric("Trend", f"{machine['trend_per_month']:+} pts/month")],
        lambda_function=infra_lambda_function(action),
        action_payload=payload,
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
            "p95_cpu_7d": row.get("P95 CPU 7d"),
            "p50_cpu_7d": row.get("P50 CPU 7d"),
            "p95_memory_7d": row.get("P95 Memory 7d"),
            "cpu_headroom": row.get("CPU Headroom"),
            "avg_network_48h": row.get("Avg Network 48h"),
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
            _metric("Peak CPU (p95, 7d)", f"{row.get('P95 CPU 7d', 0):.0f}%", f"{row.get('CPU Headroom', 0):.0f}% headroom"),
            _metric("Median CPU (7d)", f"{row.get('P50 CPU 7d', 0):.0f}%"),
            _metric("Peak memory (p95, 7d)", f"{row.get('P95 Memory 7d', 0):.0f}%", "the rightsizing guard"),
            _metric("Avg network (48h)", f"{row.get('Avg Network 48h', 0):.1f}%"),
            _metric("Monthly cost", f"${row.get('Estimated Monthly Cost USD', 0):,.2f}"),
            _metric("Instance type", row.get("Instance Type", "unknown")),
            _metric("Incidents", row.get("Incident Count", 0)),
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
