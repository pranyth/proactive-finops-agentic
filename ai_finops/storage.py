"""Normalized SQLite data foundation for FinOps on managed AI services."""

from __future__ import annotations

import json
import math
import random
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from agents.storage import get_connection


SCHEMA_VERSION = "ai-finops-v1"
GENERATOR_SEED = 42


def init_ai_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ai_cloud_providers (
            id INTEGER PRIMARY KEY,
            provider_key TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ai_services (
            id INTEGER PRIMARY KEY,
            provider_id INTEGER NOT NULL REFERENCES ai_cloud_providers(id),
            service_key TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            category TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ai_models (
            id INTEGER PRIMARY KEY,
            service_id INTEGER NOT NULL REFERENCES ai_services(id),
            model_key TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            model_tier TEXT NOT NULL,
            input_cost_per_million REAL NOT NULL,
            output_cost_per_million REAL NOT NULL,
            quality_index REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ai_applications (
            id INTEGER PRIMARY KEY,
            app_key TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            owner TEXT NOT NULL,
            environment TEXT NOT NULL,
            criticality TEXT NOT NULL,
            monthly_budget_usd REAL NOT NULL,
            quality_floor REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ai_deployments (
            id INTEGER PRIMARY KEY,
            deployment_key TEXT NOT NULL UNIQUE,
            application_id INTEGER NOT NULL REFERENCES ai_applications(id),
            model_id INTEGER NOT NULL REFERENCES ai_models(id),
            region TEXT NOT NULL,
            service_tier TEXT NOT NULL,
            status TEXT NOT NULL,
            max_output_tokens INTEGER NOT NULL,
            prompt_cache_enabled INTEGER NOT NULL DEFAULT 0,
            lambda_function TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ai_usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deployment_id INTEGER NOT NULL REFERENCES ai_deployments(id),
            observed_at TEXT NOT NULL,
            request_count INTEGER NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cache_read_tokens INTEGER NOT NULL,
            latency_p95_ms REAL NOT NULL,
            error_count INTEGER NOT NULL,
            throttle_count INTEGER NOT NULL,
            quality_score REAL NOT NULL,
            cacheable_input_ratio REAL NOT NULL,
            source_type TEXT NOT NULL,
            provenance_id INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ai_cost_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usage_event_id INTEGER NOT NULL UNIQUE REFERENCES ai_usage_events(id),
            input_cost_usd REAL NOT NULL,
            output_cost_usd REAL NOT NULL,
            total_cost_usd REAL NOT NULL,
            pricing_basis TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ai_incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deployment_id INTEGER NOT NULL REFERENCES ai_deployments(id),
            opened_at TEXT NOT NULL,
            severity TEXT NOT NULL,
            incident_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ai_recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recommendation_key TEXT NOT NULL UNIQUE,
            deployment_id INTEGER NOT NULL REFERENCES ai_deployments(id),
            action TEXT NOT NULL,
            target_model_key TEXT,
            reason TEXT NOT NULL,
            confidence REAL NOT NULL,
            estimated_monthly_savings_usd REAL NOT NULL,
            business_impact TEXT NOT NULL,
            quality_risk TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ai_action_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recommendation_id INTEGER NOT NULL REFERENCES ai_recommendations(id),
            lambda_function TEXT NOT NULL,
            action_payload TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ai_data_provenance (
            id INTEGER PRIMARY KEY,
            dataset_name TEXT NOT NULL UNIQUE,
            source_type TEXT NOT NULL,
            source_url TEXT NOT NULL,
            license TEXT NOT NULL,
            transformation TEXT NOT NULL,
            seed INTEGER,
            notes TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ai_usage_deployment_time
            ON ai_usage_events(deployment_id, observed_at);
        CREATE INDEX IF NOT EXISTS idx_ai_recommendations_action
            ON ai_recommendations(action, status);
        """
    )
    conn.commit()


def ensure_ai_demo_data(force: bool = False) -> dict[str, int]:
    with get_connection() as conn:
        init_ai_schema(conn)
        count = int(conn.execute("SELECT COUNT(*) FROM ai_usage_events").fetchone()[0])
        if count and not force:
            return table_counts(conn)
        _clear_ai_data(conn)
        _seed_reference_data(conn)
        _generate_usage(conn)
        _generate_recommendations(conn)
        conn.commit()
        return table_counts(conn)


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [
        "ai_cloud_providers", "ai_services", "ai_models", "ai_applications",
        "ai_deployments", "ai_usage_events", "ai_cost_records", "ai_incidents",
        "ai_recommendations", "ai_action_history", "ai_data_provenance",
    ]
    return {table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}


def _clear_ai_data(conn: sqlite3.Connection) -> None:
    for table in [
        "ai_action_history", "ai_recommendations", "ai_incidents", "ai_cost_records",
        "ai_usage_events", "ai_deployments", "ai_applications", "ai_models",
        "ai_services", "ai_cloud_providers", "ai_data_provenance",
    ]:
        conn.execute(f"DELETE FROM {table}")


def _seed_reference_data(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO ai_cloud_providers VALUES (?, ?, ?)",
        [(1, "aws", "AWS"), (2, "azure", "Microsoft Azure"), (3, "gcp", "Google Cloud")],
    )
    conn.executemany(
        "INSERT INTO ai_services VALUES (?, ?, ?, ?, ?)",
        [
            (1, 1, "amazon-bedrock", "Amazon Bedrock", "managed_llm_inference"),
            (2, 2, "azure-openai", "Azure OpenAI", "managed_llm_inference"),
            (3, 3, "vertex-ai", "Vertex AI", "managed_llm_inference"),
        ],
    )
    models = [
        (1, 1, "bedrock-sonnet", "Claude Sonnet on Bedrock", "premium", 6.00, 30.00, 0.94),
        (2, 1, "bedrock-haiku", "Claude Haiku on Bedrock", "efficient", 0.80, 4.00, 0.86),
        (3, 1, "bedrock-nova-lite", "Amazon Nova Lite", "efficient", 0.30, 2.50, 0.83),
        (4, 2, "azure-gpt-premium", "GPT Premium on Azure", "premium", 5.00, 15.00, 0.93),
        (5, 2, "azure-gpt-mini", "GPT Mini on Azure", "efficient", 0.20, 0.80, 0.85),
        (6, 3, "vertex-gemini-pro", "Gemini Pro on Vertex", "premium", 2.50, 10.00, 0.92),
        (7, 3, "vertex-gemini-flash", "Gemini Flash on Vertex", "efficient", 0.25, 1.00, 0.84),
    ]
    conn.executemany("INSERT INTO ai_models VALUES (?, ?, ?, ?, ?, ?, ?, ?)", models)
    apps = [
        (1, "customer-support", "Customer Support Copilot", "CX Platform", "prod", "high", 4200, 0.88),
        (2, "document-summary", "Document Summarizer", "Operations AI", "prod", "medium", 1800, 0.80),
        (3, "ticket-routing", "Ticket Classification", "Service Desk", "prod", "medium", 900, 0.78),
        (4, "developer-copilot", "Developer Copilot", "Engineering", "nonprod", "low", 750, 0.76),
        (5, "risk-review", "Risk Review Assistant", "Risk Office", "prod", "high", 2600, 0.90),
        (6, "batch-insights", "Nightly Batch Insights", "Data Platform", "prod", "medium", 1200, 0.80),
        (7, "marketing-copy", "Marketing Content Studio", "Marketing", "nonprod", "low", 600, 0.75),
        (8, "legacy-poc", "Legacy AI Proof of Concept", "Innovation Lab", "nonprod", "low", 150, 0.70),
    ]
    conn.executemany("INSERT INTO ai_applications VALUES (?, ?, ?, ?, ?, ?, ?, ?)", apps)
    deployments = [
        (1, "bedrock-support-prod", 1, 1, "us-east-1", "standard", "active", 1800, 0, "finops-bedrock-optimize-lambda"),
        (2, "bedrock-summary-prod", 2, 1, "ap-south-1", "standard", "active", 2400, 0, "finops-bedrock-model-switch-lambda"),
        (3, "bedrock-ticket-prod", 3, 1, "us-east-1", "standard", "active", 900, 0, "finops-bedrock-model-switch-lambda"),
        (4, "bedrock-dev-nonprod", 4, 1, "us-west-2", "reserved", "active", 1200, 0, "finops-bedrock-tier-change-lambda"),
        (5, "azure-risk-prod", 5, 4, "central-india", "standard", "active", 1600, 1, "finops-ai-review-lambda"),
        (6, "vertex-batch-prod", 6, 6, "asia-south1", "standard", "active", 2200, 0, "finops-ai-batch-lambda"),
        (7, "azure-marketing-dev", 7, 4, "east-us", "standard", "active", 3000, 0, "finops-ai-model-switch-lambda"),
        (8, "bedrock-legacy-poc", 8, 1, "us-east-1", "reserved", "active", 1500, 0, "finops-bedrock-disable-lambda"),
        (9, "bedrock-support-haiku-canary", 1, 2, "us-east-1", "standard", "active", 1200, 1, "finops-bedrock-promote-canary-lambda"),
        (10, "vertex-routing-canary", 3, 7, "asia-south1", "standard", "active", 700, 1, "finops-ai-promote-canary-lambda"),
    ]
    conn.executemany("INSERT INTO ai_deployments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", deployments)
    provenance = [
        (1, "corestack-enterprise-context", "original", "local CoreStack export", "internal-demo", "Application labels and cloud context only; no AI billing was supplied.", None, "Only original enterprise input in this AI FinOps dataset."),
        (2, "azure-llm-inference-trace-patterns", "open_source_reference", "https://github.com/Azure/AzurePublicDataset", "CC-BY-4.0", "Token and request-arrival distributions used as workload-shape references; no source rows are presented as CoreStack data.", None, "Research reference for LLM inference token patterns."),
        (3, "aws-bedrock-cloudwatch-schema", "official_schema_reference", "https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-runtime-metrics.html", "AWS documentation", "Metric names mapped to provider-neutral usage fields.", None, "Invocations, latency, input/output tokens, cache tokens, errors and throttles."),
        (4, "synthetic-multicloud-ai-usage-v1", "synthetic", "generated locally", "project-generated", "Deterministic scenario generator using public trace shapes and explicitly synthetic business context.", GENERATOR_SEED, "Suitable for demos and reproducible experiments, not a real customer bill."),
    ]
    conn.executemany("INSERT INTO ai_data_provenance VALUES (?, ?, ?, ?, ?, ?, ?, ?)", provenance)


def _generate_usage(conn: sqlite3.Connection) -> None:
    rng = random.Random(GENERATOR_SEED)
    end = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=30)
    configs = {
        1: (190, 1100, 720, 1350, 0.91, 0.42, 0.015),
        2: (72, 2400, 1250, 2100, 0.86, 0.58, 0.020),
        3: (310, 620, 110, 720, 0.84, 0.74, 0.010),
        4: (35, 1250, 540, 1650, 0.82, 0.50, 0.022),
        5: (88, 1750, 690, 1800, 0.92, 0.38, 0.012),
        6: (22, 5200, 1500, 4200, 0.85, 0.66, 0.018),
        7: (28, 900, 1450, 2300, 0.81, 0.48, 0.026),
        8: (2, 1000, 420, 1900, 0.76, 0.40, 0.030),
        9: (18, 1050, 610, 980, 0.88, 0.42, 0.012),
        10: (45, 600, 95, 510, 0.83, 0.72, 0.009),
    }
    model_prices = {row[0]: (row[5], row[6]) for row in conn.execute("SELECT * FROM ai_models").fetchall()}
    deployment_models = {row[0]: row[3] for row in conn.execute("SELECT * FROM ai_deployments").fetchall()}
    usage_rows: list[tuple[Any, ...]] = []
    cursor = start
    while cursor <= end:
        hour_factor = 0.35 if cursor.hour < 7 or cursor.hour > 21 else (1.35 if 10 <= cursor.hour <= 17 else 0.75)
        weekend = 0.58 if cursor.weekday() >= 5 else 1.0
        for deployment_id, cfg in configs.items():
            requests, in_avg, out_avg, latency, quality, cacheable, error_rate = cfg
            if deployment_id == 6:
                hour_factor_local = 3.5 if cursor.hour in {1, 2, 3} else 0.05
            elif deployment_id in {4, 7, 8}:
                hour_factor_local = hour_factor * weekend * 0.65
            else:
                hour_factor_local = hour_factor * weekend
            req = max(0, int(requests * hour_factor_local * rng.uniform(0.78, 1.24)))
            input_tokens = int(req * in_avg * rng.uniform(0.88, 1.12))
            output_tokens = int(req * out_avg * rng.uniform(0.84, 1.18))
            cache_read = 0
            if deployment_id in {5, 9, 10}:
                cache_read = int(input_tokens * cacheable * rng.uniform(0.55, 0.82))
            errors = int(req * error_rate * rng.uniform(0.5, 1.6))
            throttles = int(req * (0.018 if deployment_id == 1 and 11 <= cursor.hour <= 15 else 0.002) * rng.random())
            observed_quality = max(0.55, min(0.98, quality + rng.uniform(-0.035, 0.025)))
            observed_latency = latency * rng.uniform(0.78, 1.28) * (1.25 if throttles else 1.0)
            usage_rows.append((
                deployment_id, cursor.isoformat(timespec="seconds"), req, input_tokens,
                output_tokens, cache_read, round(observed_latency, 2), errors, throttles,
                round(observed_quality, 4), cacheable, "synthetic_from_open_trace_patterns", 4,
            ))
        cursor += timedelta(hours=1)
    conn.executemany(
        """INSERT INTO ai_usage_events (
            deployment_id, observed_at, request_count, input_tokens, output_tokens,
            cache_read_tokens, latency_p95_ms, error_count, throttle_count,
            quality_score, cacheable_input_ratio, source_type, provenance_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        usage_rows,
    )
    event_rows = conn.execute("SELECT id, deployment_id, input_tokens, output_tokens, cache_read_tokens FROM ai_usage_events").fetchall()
    costs = []
    for event in event_rows:
        model_id = deployment_models[event["deployment_id"]]
        input_rate, output_rate = model_prices[model_id]
        billable_input = max(0, event["input_tokens"] - event["cache_read_tokens"])
        cache_cost = event["cache_read_tokens"] * input_rate * 0.10 / 1_000_000
        input_cost = billable_input * input_rate / 1_000_000 + cache_cost
        output_cost = event["output_tokens"] * output_rate / 1_000_000
        costs.append((event["id"], round(input_cost, 6), round(output_cost, 6), round(input_cost + output_cost, 6), "illustrative_token_rates_v1"))
    conn.executemany("INSERT INTO ai_cost_records (usage_event_id, input_cost_usd, output_cost_usd, total_cost_usd, pricing_basis) VALUES (?, ?, ?, ?, ?)", costs)
    incidents = [
        (1, (end - timedelta(days=4)).isoformat(timespec="seconds"), "medium", "throttling", "Peak-hour Bedrock throttling increased response time.", "resolved"),
        (2, (end - timedelta(days=8)).isoformat(timespec="seconds"), "low", "output_growth", "Summary responses exceeded expected token envelope.", "open"),
        (5, (end - timedelta(days=12)).isoformat(timespec="seconds"), "high", "quality_regression", "Risk answer quality fell below approval threshold during a prompt change.", "resolved"),
        (7, (end - timedelta(days=3)).isoformat(timespec="seconds"), "medium", "client_errors", "Malformed requests increased client errors.", "open"),
    ]
    conn.executemany("INSERT INTO ai_incidents (deployment_id, opened_at, severity, incident_type, summary, status) VALUES (?, ?, ?, ?, ?, ?)", incidents)


# Thresholds are the AI-service equivalent of the VM analyst's percentile gates:
# every one is checked against a measured column, never against a deployment name.
UNUSED_REQUESTS_30D = 1_000      # a reserved tier serving <~33 requests/day is parked
MIN_ACTIONABLE_COST_USD = 100.0  # below this the change costs more than it saves
CACHEABLE_INPUT_MIN = 0.40       # repeated prompt context worth caching
QUALITY_HEADROOM_MIN = 0.04      # slack over the floor before a model change is fair
VERBOSE_OUTPUT_TOKENS = 1_200    # average completion length that suggests no output cap
BATCH_TOLERANT_LATENCY_MS = 4_000  # already answering slowly, so batching costs nothing
# A change that can alter what the model returns has to be worth clearly more
# than a change that cannot. Without this the cheapest model always wins and the
# agent stops proposing caching or batching at all, which is not how a FinOps
# team actually sequences work: take the free win first, take the risky one only
# when it is decisively bigger.
RISK_PREMIUM = 2.0


def _model_catalog(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {
        row["model_key"]: dict(row)
        for row in conn.execute(
            "SELECT m.model_key, m.display_name, m.service_id, m.model_tier,"
            " m.input_cost_per_million, m.output_cost_per_million, m.quality_index FROM ai_models m"
        )
    }


def _blended_cost(model: dict[str, Any], input_tokens: float, output_tokens: float) -> float:
    return (input_tokens * model["input_cost_per_million"]
            + output_tokens * model["output_cost_per_million"]) / 1_000_000


def _cheaper_model(catalog: dict[str, dict[str, Any]], current_key: str, quality_floor: float,
                   input_tokens: float, output_tokens: float) -> tuple[str | None, float]:
    """Cheapest model in the same service whose quality index still clears the floor.

    Savings come from the published token rates applied to this deployment's own
    30-day token mix, so an output-heavy workload and an input-heavy one on the
    same model switch do not get credited the same percentage.
    """
    current = catalog.get(current_key)
    if not current:
        return None, 0.0
    current_cost = _blended_cost(current, input_tokens, output_tokens)
    if current_cost <= 0:
        return None, 0.0
    candidates = [
        (key, _blended_cost(model, input_tokens, output_tokens))
        for key, model in catalog.items()
        if key != current_key
        and model["service_id"] == current["service_id"]
        and model["quality_index"] >= quality_floor
    ]
    if not candidates:
        return None, 0.0
    key, cost = min(candidates, key=lambda item: item[1])
    if cost >= current_cost:
        return None, 0.0
    return key, round(1.0 - cost / current_cost, 4)


def _generate_recommendations(conn: sqlite3.Connection) -> None:
    """Derive one action per deployment from measured usage, quality and price.

    Order is risk-ascending inside two hard safety gates: a deployment already
    under its quality floor gets remediation and no cost action at all, and a
    high-criticality or thin-headroom workload is never offered a model change.
    Within what is left the largest supported saving wins, which is the same
    rule the console uses to rank the merged estate list.
    """
    rows = deployment_summary(conn)
    catalog = _model_catalog(conn)
    now = datetime.utcnow().isoformat(timespec="seconds")
    recommendations = []
    for row in rows:
        cost = float(row["monthly_cost_usd"] or 0.0)
        requests = int(row["requests_30d"] or 0)
        input_tokens = float(row["input_tokens_30d"] or 0.0)
        output_tokens = float(row["output_tokens_30d"] or 0.0)
        headroom = float(row["quality_score"]) - float(row["quality_floor"])
        output_per_request = output_tokens / max(requests, 1)
        cacheable = float(row["cacheable_input_ratio"] or 0.0)
        reserved = row["service_tier"] == "reserved"
        nonprod = row["environment"] != "prod"

        action, target, savings_rate = "NO_ACTION", None, 0.0
        quality_risk = "low"
        reason = "Usage, cost, quality and reliability are within the configured operating envelope."
        impact = "No change required; continue monitoring cost, quality and latency."

        if float(row["quality_score"]) < float(row["quality_floor"]):
            # Safety gate: never propose a cost cut on a workload already
            # failing the quality bar it was signed off against.
            action, quality_risk = "QUALITY_REMEDIATION", "high"
            reason = (f"Answer quality {row['quality_score']:.3f} is below the agreed floor "
                      f"{row['quality_floor']:.2f}; cost optimisation is withheld until it recovers.")
            impact = "Investigate prompt or model regression before any cost change."
        elif reserved and requests < UNUSED_REQUESTS_30D:
            action, savings_rate = "SHUTDOWN_UNUSED_DEPLOYMENT", 0.95
            reason = (f"A reserved deployment served only {requests:,} requests in 30 days, "
                      f"so almost all of the commitment is unused.")
            impact = "Remove idle commitment after owner confirmation."
        elif reserved and nonprod:
            action, savings_rate = "MOVE_TO_PAY_PER_USE", 0.38
            reason = (f"A non-production workload at {requests:,} requests sits on a reserved tier "
                      f"with long idle periods.")
            impact = "Lower fixed spend; small cold-start trade-off is acceptable outside production."
        elif cost >= MIN_ACTIONABLE_COST_USD:
            options = []
            if not row["prompt_cache_enabled"] and cacheable >= CACHEABLE_INPUT_MIN:
                current = catalog.get(row["model_key"])
                input_cost = (input_tokens * current["input_cost_per_million"] / 1_000_000) if current else 0.0
                # Cached input bills at 10% of the input rate, so the saving is
                # 90% of the cacheable share of this deployment's input spend.
                options.append((
                    round((input_cost * cacheable * 0.90) / cost, 4), "ENABLE_PROMPT_CACHING", None, "low",
                    f"{cacheable:.0%} of input tokens are repeated context and prompt caching is disabled.",
                    "Reduce repeated input-token cost without changing the model or answer quality.",
                ))
            if float(row["latency_p95_ms"] or 0.0) >= BATCH_TOLERANT_LATENCY_MS:
                options.append((
                    0.45, "BATCH_REQUESTS", None, "low",
                    f"p95 latency is already {row['latency_p95_ms']:,.0f} ms, so the workload has no "
                    f"interactive latency requirement and suits batch inference.",
                    "Longer completion window in exchange for lower inference cost.",
                ))
            # Second safety gate: anything that changes what the model returns is
            # only offered where there is measured quality slack and no
            # high-criticality blast radius.
            if headroom >= QUALITY_HEADROOM_MIN and row["criticality"] != "high":
                if output_per_request > VERBOSE_OUTPUT_TOKENS and nonprod:
                    options.append((
                        0.40, "REDUCE_OUTPUT_TOKENS", None, "medium",
                        f"Non-production responses average {output_per_request:,.0f} output tokens with "
                        f"{headroom:.3f} quality headroom, so no output budget is being enforced.",
                        "Set a smaller output budget and re-check brand quality.",
                    ))
                key, rate = _cheaper_model(catalog, row["model_key"], float(row["quality_floor"]),
                                           input_tokens, output_tokens)
                if key:
                    options.append((
                        rate, "SWITCH_TO_SMALLER_MODEL", key, "medium",
                        f"{catalog[key]['display_name']} clears the "
                        f"{row['quality_floor']:.2f} quality floor at a lower token rate, and this workload has "
                        f"{headroom:.3f} of measured headroom.",
                        "Run a canary evaluation before switching production traffic.",
                    ))
            if options:
                safe = max((o for o in options if o[3] == "low"), key=lambda o: o[0], default=None)
                bold = max((o for o in options if o[3] != "low"), key=lambda o: o[0], default=None)
                if safe and bold:
                    chosen = bold if bold[0] >= safe[0] * RISK_PREMIUM else safe
                else:
                    chosen = safe or bold
                savings_rate, action, target, quality_risk, reason, impact = chosen
        elif cost > 0:
            reason = (f"Monthly spend of ${cost:,.2f} is below the ${MIN_ACTIONABLE_COST_USD:,.0f} "
                      f"threshold where an optimisation change pays for the engineering effort.")

        monthly_savings = round(cost * savings_rate, 2)
        confidence = 94.0 if action == "SHUTDOWN_UNUSED_DEPLOYMENT" else (88.0 if action in {"ENABLE_PROMPT_CACHING", "BATCH_REQUESTS"} else 82.0)
        evidence = {
            "requests_30d": row["requests_30d"],
            "input_tokens_30d": row["input_tokens_30d"],
            "output_tokens_30d": row["output_tokens_30d"],
            "monthly_cost_usd": row["monthly_cost_usd"],
            "quality_score": row["quality_score"],
            "quality_floor": row["quality_floor"],
            "quality_headroom": round(headroom, 4),
            "output_tokens_per_request": round(output_per_request, 1),
            "latency_p95_ms": row["latency_p95_ms"],
            "error_rate_pct": row["error_rate_pct"],
            "cacheable_input_ratio": row["cacheable_input_ratio"],
            "prompt_cache_enabled": bool(row["prompt_cache_enabled"]),
            "service_tier": row["service_tier"],
            "applied_savings_rate": savings_rate,
        }
        recommendations.append((
            f"rec-{row['deployment_key']}", row["deployment_id"], action, target, reason,
            confidence, monthly_savings, impact, quality_risk, json.dumps(evidence),
            "proposed" if action != "NO_ACTION" else "monitoring", now,
        ))
    conn.executemany(
        """INSERT INTO ai_recommendations (
            recommendation_key, deployment_id, action, target_model_key, reason,
            confidence, estimated_monthly_savings_usd, business_impact, quality_risk,
            evidence_json, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        recommendations,
    )


def deployment_summary(conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    owns_conn = conn is None
    conn = conn or get_connection()
    init_ai_schema(conn)
    query = """
        SELECT d.id AS deployment_id, d.deployment_key, d.region, d.service_tier,
               d.prompt_cache_enabled, d.lambda_function,
               a.display_name AS application, a.environment, a.criticality,
               a.monthly_budget_usd, a.quality_floor,
               p.provider_key AS provider, p.display_name AS provider_name,
               s.display_name AS ai_service, m.model_key, m.display_name AS model,
               SUM(u.request_count) AS requests_30d,
               SUM(u.input_tokens) AS input_tokens_30d,
               SUM(u.output_tokens) AS output_tokens_30d,
               SUM(u.cache_read_tokens) AS cache_read_tokens_30d,
               ROUND(AVG(u.latency_p95_ms), 2) AS latency_p95_ms,
               ROUND(AVG(u.quality_score), 4) AS quality_score,
               ROUND(AVG(u.cacheable_input_ratio), 3) AS cacheable_input_ratio,
               ROUND(100.0 * SUM(u.error_count) / MAX(SUM(u.request_count), 1), 3) AS error_rate_pct,
               ROUND(SUM(c.total_cost_usd), 2) AS monthly_cost_usd
        FROM ai_deployments d
        JOIN ai_applications a ON a.id = d.application_id
        JOIN ai_models m ON m.id = d.model_id
        JOIN ai_services s ON s.id = m.service_id
        JOIN ai_cloud_providers p ON p.id = s.provider_id
        JOIN ai_usage_events u ON u.deployment_id = d.id
        JOIN ai_cost_records c ON c.usage_event_id = u.id
        GROUP BY d.id
        ORDER BY monthly_cost_usd DESC
    """
    rows = [dict(row) for row in conn.execute(query).fetchall()]
    if owns_conn:
        conn.close()
    return rows


def recommendation_rows(provider: str | None = None) -> list[dict[str, Any]]:
    ensure_ai_demo_data()
    with get_connection() as conn:
        sql = """
            SELECT r.id AS recommendation_id, r.recommendation_key, r.action,
                   r.target_model_key, r.reason, r.confidence,
                   r.estimated_monthly_savings_usd, r.business_impact,
                   r.quality_risk, r.evidence_json, r.status, r.created_at,
                   d.deployment_key, d.region, d.service_tier, d.lambda_function,
                   a.display_name AS application, a.environment, a.criticality,
                   p.provider_key AS provider, p.display_name AS provider_name,
                   s.display_name AS ai_service, m.model_key, m.display_name AS current_model
            FROM ai_recommendations r
            JOIN ai_deployments d ON d.id = r.deployment_id
            JOIN ai_applications a ON a.id = d.application_id
            JOIN ai_models m ON m.id = d.model_id
            JOIN ai_services s ON s.id = m.service_id
            JOIN ai_cloud_providers p ON p.id = s.provider_id
        """
        params: tuple[Any, ...] = ()
        if provider:
            sql += " WHERE p.provider_key = ?"
            params = (provider,)
        sql += " ORDER BY r.estimated_monthly_savings_usd DESC, r.confidence DESC"
        result = []
        for row in conn.execute(sql, params).fetchall():
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            result.append(item)
        return result


def profile() -> dict[str, Any]:
    counts = ensure_ai_demo_data()
    with get_connection() as conn:
        totals = conn.execute(
            """SELECT SUM(request_count), SUM(input_tokens), SUM(output_tokens),
                      MIN(observed_at), MAX(observed_at) FROM ai_usage_events"""
        ).fetchone()
        cost = float(conn.execute("SELECT COALESCE(SUM(total_cost_usd), 0) FROM ai_cost_records").fetchone()[0])
        savings = float(conn.execute("SELECT COALESCE(SUM(estimated_monthly_savings_usd), 0) FROM ai_recommendations").fetchone()[0])
        provenance = [dict(row) for row in conn.execute("SELECT * FROM ai_data_provenance ORDER BY id").fetchall()]
    return {
        "dataset_name": "synthetic_multicloud_ai_service_usage_v1",
        "schema_version": SCHEMA_VERSION,
        "primary_service": "Amazon Bedrock",
        "category": "managed_llm_inference",
        "providers": 3,
        "services": counts["ai_services"],
        "models": counts["ai_models"],
        "applications": counts["ai_applications"],
        "deployments": counts["ai_deployments"],
        "usage_events": counts["ai_usage_events"],
        "requests": int(totals[0] or 0),
        "input_tokens": int(totals[1] or 0),
        "output_tokens": int(totals[2] or 0),
        "time_range": {"start": totals[3], "end": totals[4]},
        "monthly_cost_usd": round(cost, 2),
        "savings_opportunity_usd": round(savings, 2),
        "storage": "normalized SQLite relational tables",
        "raw_corestack_ai_data": "Not available and not claimed",
        "data_statement": "CoreStack supplies enterprise context only. AI usage is synthetic, generated from open LLM trace patterns and official metric schemas.",
        "provenance": provenance,
    }

