"""Generate enterprise context data for the autonomous FinOps demo.

This script keeps real CoreStack-derived telemetry as the base and adds clearly
labeled synthetic enterprise context that is needed for autonomous FinOps
reasoning: inventory, cost, incidents, action history, pipeline runs, and field
provenance.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path("data")
VM_METRICS = DATA_DIR / "augmented_vm_metrics.csv"
DB_METRICS = DATA_DIR / "db_metrics.csv"
VM_TAGS = DATA_DIR / "vm_tags.json"

OUT_INVENTORY = DATA_DIR / "vm_inventory.csv"
OUT_COST = DATA_DIR / "cost_metrics.csv"
OUT_INCIDENTS = DATA_DIR / "incident_history.csv"
OUT_ACTIONS = DATA_DIR / "action_history.csv"
OUT_PIPELINES = DATA_DIR / "pipeline_runs.csv"
OUT_PROVENANCE = DATA_DIR / "data_provenance.csv"

REGIONS = ["eastus", "westus2", "centralindia", "westeurope", "southeastasia"]
OS_TYPES = ["ubuntu-22.04", "ubuntu-24.04", "windows-2022", "rhel-9"]
OWNER_TEAMS = ["finops", "platform", "data-eng", "app-ops", "sre", "analytics"]
RESOURCE_GROUPS = ["rg-finops", "rg-corestack-prod", "rg-corestack-dev", "rg-analytics", "rg-shared"]

SKU_BY_CLASS = {
    "truly_idle": ["Standard_B1s", "Standard_B1ms", "Standard_B2s"],
    "low_variable": ["Standard_B2s", "Standard_D2s_v5", "Standard_B2ms"],
    "moderate": ["Standard_D2s_v5", "Standard_D4s_v5", "Standard_E2s_v5"],
    "production": ["Standard_D4s_v5", "Standard_D8s_v5", "Standard_E4s_v5"],
}

HOURLY_RATE_USD = {
    "Standard_B1s": 0.012,
    "Standard_B1ms": 0.021,
    "Standard_B2s": 0.046,
    "Standard_B2ms": 0.083,
    "Standard_D2s_v5": 0.096,
    "Standard_D4s_v5": 0.192,
    "Standard_D8s_v5": 0.384,
    "Standard_E2s_v5": 0.126,
    "Standard_E4s_v5": 0.252,
}


def stable_rng(value: str) -> np.random.Generator:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    seed = int(digest[:12], 16) % (2**32)
    return np.random.default_rng(seed)


def choose(value: str, items: list[str]) -> str:
    rng = stable_rng(value)
    return items[int(rng.integers(0, len(items)))]


def infer_environment(vm: str, workload_class: str) -> str:
    name = vm.lower()
    if "prod" in name or workload_class == "production":
        return "prod"
    if "uat" in name:
        return "uat"
    if "test" in name or "demo" in name or "rule" in name:
        return "test"
    if "dev" in name:
        return "dev"
    return choose(vm + "env", ["dev", "test", "uat", "prod"])


def infer_criticality(environment: str, application: str, workload_class: str) -> str:
    if environment == "prod" and application != "untagged":
        return "high"
    if environment in {"prod", "uat"} or workload_class in {"moderate", "production"}:
        return "medium"
    return "low"


def build_inventory(vm_df: pd.DataFrame, tags: dict) -> pd.DataFrame:
    rows = []
    for vm, group in vm_df.groupby("resource_id"):
        rng = stable_rng(vm)
        workload_class = str(group["workload_class"].iloc[0])
        app_info = tags.get(vm, {})
        application = app_info.get("application", "untagged")
        environment = infer_environment(vm, workload_class)
        criticality = infer_criticality(environment, application, workload_class)
        sku = choose(vm + "sku", SKU_BY_CLASS.get(workload_class, SKU_BY_CLASS["low_variable"]))
        shutdown_allowed = environment != "prod" and criticality != "high"
        rows.append({
            "resource_id": vm,
            "cloud_provider": "azure",
            "subscription_id": "sub-corestack-demo",
            "resource_group": choose(vm + "rg", RESOURCE_GROUPS),
            "region": choose(vm + "region", REGIONS),
            "vm_sku": sku,
            "os_type": choose(vm + "os", OS_TYPES),
            "environment": environment,
            "application": application,
            "app_owner": app_info.get("app_owner", ""),
            "portfolio_owner": app_info.get("portfolio_owner", ""),
            "owner_team": app_info.get("app_owner") or choose(vm + "team", OWNER_TEAMS),
            "owner_email": f"{(app_info.get('app_owner') or choose(vm + 'team2', OWNER_TEAMS)).lower().replace(' ', '.')}@example.com",
            "cost_center": f"CC-{int(rng.integers(1000, 9999))}",
            "business_criticality": criticality,
            "shutdown_allowed": shutdown_allowed,
            "approval_required": environment in {"prod", "uat"} or application != "untagged",
            "business_hours": "Mon-Fri 09:00-18:00" if environment != "prod" else "24x7",
            "hourly_rate_usd": HOURLY_RATE_USD[sku],
            "source_type": "real_corestack_tags + synthetic_enterprise_context",
        })
    return pd.DataFrame(rows).sort_values("resource_id")


def build_cost_metrics(vm_df: pd.DataFrame, inventory: pd.DataFrame) -> pd.DataFrame:
    inv = inventory.set_index("resource_id")
    vm_df = vm_df.copy()
    vm_df["date"] = vm_df["timestamp"].dt.date
    daily = vm_df.groupby(["resource_id", "date"]).agg(
        avg_cpu=("cpu_percent", "mean"),
        max_cpu=("cpu_percent", "max"),
        avg_network=("network_percent", "mean"),
    ).reset_index()

    rows = []
    for _, row in daily.iterrows():
        vm = row["resource_id"]
        hourly = float(inv.loc[vm, "hourly_rate_usd"])
        utilization_modifier = 0.92 + min(float(row["avg_cpu"]) / 100.0, 0.25)
        daily_cost = hourly * 24 * utilization_modifier
        rows.append({
            "date": row["date"],
            "resource_id": vm,
            "vm_sku": inv.loc[vm, "vm_sku"],
            "environment": inv.loc[vm, "environment"],
            "application": inv.loc[vm, "application"],
            "currency": "USD",
            "daily_cost": round(daily_cost, 4),
            "estimated_monthly_cost": round(daily_cost * 30, 2),
            "avg_cpu": round(float(row["avg_cpu"]), 3),
            "max_cpu": round(float(row["max_cpu"]), 3),
            "source_type": "synthetic_cost_from_public_cloud_pricing_pattern",
        })
    return pd.DataFrame(rows)


def build_incidents(vm_df: pd.DataFrame, inventory: pd.DataFrame) -> pd.DataFrame:
    inv = inventory.set_index("resource_id")
    rows = []
    incident_id = 1
    for vm, group in vm_df.groupby("resource_id"):
        rng = stable_rng(vm + "incidents")
        criticality = inv.loc[vm, "business_criticality"]
        app = inv.loc[vm, "application"]
        threshold = group["cpu_percent"].mean() + 1.5 * group["cpu_percent"].std()
        spike_rows = group[group["cpu_percent"] > threshold].sort_values("timestamp")
        count = 1 if criticality == "high" else int(rng.integers(0, 2))
        if spike_rows.empty:
            continue
        picks = spike_rows.sample(min(count, len(spike_rows)), random_state=int(rng.integers(1, 999999)))
        for _, spike in picks.iterrows():
            severity = "P1" if criticality == "high" and spike["cpu_percent"] > 60 else choose(vm + str(incident_id), ["P2", "P3", "P3"])
            rows.append({
                "incident_id": f"INC-{incident_id:05d}",
                "timestamp": spike["timestamp"],
                "resource_id": vm,
                "application": app,
                "severity": severity,
                "incident_type": choose(vm + "itype" + str(incident_id), ["cpu_spike", "db_latency", "network_degradation", "pipeline_delay"]),
                "duration_minutes": int(rng.integers(20, 240)),
                "root_cause": "Synthetic incident generated from high utilization window",
                "remediation_taken": choose(vm + "remed" + str(incident_id), ["scaled_up", "restarted_service", "investigated_db", "no_action"]),
                "source_type": "synthetic_incident_history_from_trace_patterns",
            })
            incident_id += 1
    return pd.DataFrame(rows).sort_values("timestamp") if rows else pd.DataFrame()


def build_action_history(vm_df: pd.DataFrame, inventory: pd.DataFrame, cost_df: pd.DataFrame) -> pd.DataFrame:
    inv = inventory.set_index("resource_id")
    latest_cost = cost_df.sort_values("date").groupby("resource_id").tail(1).set_index("resource_id")
    rows = []
    action_id = 1
    for vm, group in vm_df.groupby("resource_id"):
        rng = stable_rng(vm + "actions")
        latest = group.sort_values("timestamp").tail(48)
        avg_cpu = latest["cpu_percent"].mean()
        avg_net = latest["network_percent"].mean()
        env = inv.loc[vm, "environment"]
        current_sku = inv.loc[vm, "vm_sku"]
        monthly_cost = float(latest_cost.loc[vm, "estimated_monthly_cost"])
        if bool(inv.loc[vm, "shutdown_allowed"]) and avg_cpu < 2.5 and avg_net < 20:
            action = "SCHEDULE_SHUTDOWN"
            savings = monthly_cost * 0.35
            after_sku = current_sku
            reason = "Low peak utilization and shutdown_allowed policy is true"
        elif avg_cpu < 4.0 and env != "prod":
            action = "SCALE_DOWN"
            savings = monthly_cost * 0.22
            after_sku = "Standard_B2s"
            reason = "Sustained under-utilization in non-production environment"
        else:
            continue
        rows.append({
            "action_id": f"ACT-{action_id:05d}",
            "timestamp": latest["timestamp"].max(),
            "resource_id": vm,
            "application": inv.loc[vm, "application"],
            "action": action,
            "before_sku": current_sku,
            "after_sku": after_sku,
            "status": choose(vm + "status", ["success", "success", "pending_approval"]),
            "approval_status": "required" if bool(inv.loc[vm, "approval_required"]) else "auto_approved",
            "reason": reason,
            "estimated_savings_monthly_usd": round(savings, 2),
            "triggered_by": "synthetic_policy_engine",
            "source_type": "synthetic_action_history",
        })
        action_id += 1
    return pd.DataFrame(rows)


def build_pipeline_runs(vm_df: pd.DataFrame) -> pd.DataFrame:
    start = pd.to_datetime(vm_df["timestamp"].max()).normalize() - pd.Timedelta(days=29)
    pipeline_names = ["telemetry_ingestion", "metric_augmentation", "forecast_generation", "recommendation_generation", "knowledge_indexing", "serverless_action_audit"]
    rows = []
    run_id = 1
    for day in pd.date_range(start, periods=30, freq="D"):
        for pipeline in pipeline_names:
            rng = stable_rng(f"{pipeline}-{day.date()}")
            failed = rng.random() < (0.08 if pipeline != "telemetry_ingestion" else 0.04)
            rows.append({
                "run_id": f"RUN-{run_id:05d}",
                "pipeline_name": pipeline,
                "start_time": day + pd.Timedelta(hours=int(rng.integers(0, 23))),
                "end_time": day + pd.Timedelta(hours=int(rng.integers(0, 23)), minutes=int(rng.integers(10, 59))),
                "status": "failed" if failed else "success",
                "duration_seconds": int(rng.integers(90, 4200)),
                "records_processed": int(rng.integers(0 if failed else 1000, 120000)),
                "failure_reason": choose(pipeline + str(day), ["schema_mismatch", "timeout", "missing_batch", "model_training_error"]) if failed else "",
                "retry_count": int(rng.integers(1, 4)) if failed else 0,
                "source_type": "synthetic_pipeline_history",
            })
            run_id += 1
    return pd.DataFrame(rows)


def build_provenance() -> pd.DataFrame:
    rows = [
        {"dataset": "augmented_vm_metrics.csv", "fields": "timestamp, resource_id, cpu/network/memory/disk/workload_class", "source_type": "real_corestack + synthetic_metric_enrichment", "notes": "CPU/network preserve real production VM patterns where available; memory/disk are generated when not collected."},
        {"dataset": "db_metrics.csv", "fields": "db connections, latency, reads, writes", "source_type": "synthetic_app_db_enrichment", "notes": "Generated to model Vijay's VM trouble -> DB degradation pattern."},
        {"dataset": "vm_tags.json", "fields": "application, owner tags", "source_type": "real_corestack_inventory_where_available", "notes": "Untagged VMs are explicitly marked untagged."},
        {"dataset": "vm_inventory.csv", "fields": "environment, SKU, owner, criticality, business hours, shutdown policy", "source_type": "real_corestack_tags + synthetic_enterprise_context", "notes": "Business context required for autonomous recommendations."},
        {"dataset": "cost_metrics.csv", "fields": "daily cost, monthly estimate, SKU", "source_type": "synthetic_cost_from_public_cloud_pricing_pattern", "notes": "Used for estimated savings in demos; replace with billing export for production."},
        {"dataset": "incident_history.csv", "fields": "incident id, severity, root cause, remediation", "source_type": "synthetic_incident_history_from_trace_patterns", "notes": "Used to demonstrate knowledge-agent reasoning and business risk."},
        {"dataset": "action_history.csv", "fields": "scale/shutdown actions, approval, savings", "source_type": "synthetic_action_history", "notes": "Used to explain why actions were taken."},
        {"dataset": "pipeline_runs.csv", "fields": "pipeline executions, failures, durations, retries", "source_type": "synthetic_pipeline_history", "notes": "Used for pipeline monitor and query-agent demos."},
    ]
    return pd.DataFrame(rows)


def main() -> None:
    vm_df = pd.read_csv(VM_METRICS, parse_dates=["timestamp"])
    with VM_TAGS.open() as handle:
        tags = json.load(handle)

    inventory = build_inventory(vm_df, tags)
    cost = build_cost_metrics(vm_df, inventory)
    incidents = build_incidents(vm_df, inventory)
    actions = build_action_history(vm_df, inventory, cost)
    pipelines = build_pipeline_runs(vm_df)
    provenance = build_provenance()

    inventory.to_csv(OUT_INVENTORY, index=False)
    cost.to_csv(OUT_COST, index=False)
    incidents.to_csv(OUT_INCIDENTS, index=False)
    actions.to_csv(OUT_ACTIONS, index=False)
    pipelines.to_csv(OUT_PIPELINES, index=False)
    provenance.to_csv(OUT_PROVENANCE, index=False)

    print(f"wrote {OUT_INVENTORY}: {len(inventory):,} rows")
    print(f"wrote {OUT_COST}: {len(cost):,} rows")
    print(f"wrote {OUT_INCIDENTS}: {len(incidents):,} rows")
    print(f"wrote {OUT_ACTIONS}: {len(actions):,} rows")
    print(f"wrote {OUT_PIPELINES}: {len(pipelines):,} rows")
    print(f"wrote {OUT_PROVENANCE}: {len(provenance):,} rows")


if __name__ == "__main__":
    main()