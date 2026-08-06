"""Infrastructure fleet analytics for the console.

The analyst answers questions; this module answers "what does the estate look
like right now". It reuses the same recommendation frame the analyst builds, so
a number shown on a chart and the same number quoted inside an answer can never
drift apart.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from agents import datacache
from agents.analyst import VM_CSV, FinOpsAnalystAgent

# Buckets are named for what an operator does about them, not for the numbers.
CPU_BANDS = [
    ("Idle", 0.0, 2.0),
    ("Very low", 2.0, 10.0),
    ("Low", 10.0, 25.0),
    ("Moderate", 25.0, 50.0),
    ("Busy", 50.0, 75.0),
    ("Saturated", 75.0, 1000.0),
]

_analyst = FinOpsAnalystAgent()


def _frame() -> pd.DataFrame:
    return _analyst._vm_recommendation_frame()


def summary() -> dict[str, Any]:
    """Fleet-wide rollup: KPIs plus everything the infrastructure charts need."""
    return datacache.derived("infra_fleet_summary", [VM_CSV], _build_summary)


def _build_summary() -> dict[str, Any]:
    df = _frame()
    if df.empty:
        return _empty_summary()

    metrics = datacache.load_csv(VM_CSV, parse_dates=["timestamp"])
    utilization = _utilization_averages(metrics)

    monthly_cost = float(df["Estimated Monthly Cost USD"].sum())
    savings = float(df["Estimated Savings Monthly USD"].sum())
    actionable = df[df["Recommended Action"] != "NO_ACTION"]

    return {
        "kpi": {
            "resources": int(len(df)),
            "providers": int(df["Provider"].nunique()),
            "monthly_cost_usd": round(monthly_cost, 2),
            "savings_usd": round(savings, 2),
            "savings_pct": round(100 * savings / monthly_cost, 1) if monthly_cost else 0.0,
            "actionable": int(len(actionable)),
            "idle_resources": int((df["Avg CPU 48h"] < 2.0).sum()),
            "shutdown_candidates": int(df["Shutdown Candidate"].sum()),
            "scale_down_candidates": int(df["Scale Down Candidate"].sum()),
            "risky_resources": int(df["Risky"].sum()),
            "avg_cpu": round(float(df["Avg CPU 48h"].mean()), 1),
            "tagged_pct": round(100 * float((df["Tagged"] == "Yes").mean()), 1),
            **utilization,
        },
        "providers": _by_provider(df),
        "cpu_bands": _cpu_bands(df),
        "action_mix": _action_mix(df),
        "workload_mix": _group_counts(df, "Workload Class"),
        "environments": _by_environment(df),
        "top_resources": _top_resources(df),
        "resources": sorted(df["VM"].tolist()),
    }


def _empty_summary() -> dict[str, Any]:
    return {
        "kpi": {
            "resources": 0, "providers": 0, "monthly_cost_usd": 0.0, "savings_usd": 0.0,
            "savings_pct": 0.0, "actionable": 0, "idle_resources": 0, "shutdown_candidates": 0,
            "scale_down_candidates": 0, "risky_resources": 0, "avg_cpu": 0.0, "tagged_pct": 0.0,
            "avg_memory": 0.0, "avg_disk": 0.0, "avg_network": 0.0,
        },
        "providers": [], "cpu_bands": [], "action_mix": [], "workload_mix": [],
        "environments": [], "top_resources": [], "resources": [],
    }


def _utilization_averages(metrics: pd.DataFrame) -> dict[str, float]:
    """Fleet-wide averages for the four utilization signals the demo collects."""
    columns = {
        "avg_memory": "memory_percent",
        "avg_disk": "disk_percent",
        "avg_network": "network_percent",
    }
    result: dict[str, float] = {}
    for key, column in columns.items():
        value = float(metrics[column].mean()) if column in metrics and not metrics.empty else 0.0
        result[key] = round(value, 1)
    return result


def _by_provider(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for provider, group in df.groupby("Provider"):
        rows.append({
            "provider": str(provider),
            "resources": int(len(group)),
            "monthly_cost_usd": round(float(group["Estimated Monthly Cost USD"].sum()), 2),
            "savings_usd": round(float(group["Estimated Savings Monthly USD"].sum()), 2),
            "avg_cpu": round(float(group["Avg CPU 48h"].mean()), 1),
        })
    return sorted(rows, key=lambda row: row["monthly_cost_usd"], reverse=True)


def _cpu_bands(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Distribution of average CPU across the fleet, banded by what to do next."""
    bands = []
    for label, low, high in CPU_BANDS:
        mask = (df["Avg CPU 48h"] >= low) & (df["Avg CPU 48h"] < high)
        subset = df[mask]
        bands.append({
            "label": label,
            "range": f"{low:.0f}-{high:.0f}%" if high < 1000 else f"{low:.0f}%+",
            "count": int(len(subset)),
            "monthly_cost_usd": round(float(subset["Estimated Monthly Cost USD"].sum()), 2),
        })
    return bands


def _action_mix(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for action, group in df.groupby("Recommended Action"):
        rows.append({
            "action": str(action),
            "count": int(len(group)),
            "savings_usd": round(float(group["Estimated Savings Monthly USD"].sum()), 2),
        })
    return sorted(rows, key=lambda row: row["count"], reverse=True)


def _group_counts(df: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    counts = df[column].value_counts()
    return [{"label": str(key), "count": int(value)} for key, value in counts.items()]


def _by_environment(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for environment, group in df.groupby("Environment"):
        rows.append({
            "environment": str(environment),
            "count": int(len(group)),
            "monthly_cost_usd": round(float(group["Estimated Monthly Cost USD"].sum()), 2),
        })
    return sorted(rows, key=lambda row: row["monthly_cost_usd"], reverse=True)


def _top_resources(df: pd.DataFrame, limit: int = 10) -> list[dict[str, Any]]:
    top = df.sort_values("Estimated Monthly Cost USD", ascending=False).head(limit)
    return [
        {
            "resource": row["VM"],
            "application": row["Application"],
            "provider": row["Provider"],
            "environment": row["Environment"],
            "instance_type": row["Instance Type"],
            "monthly_cost_usd": row["Estimated Monthly Cost USD"],
            "savings_usd": row["Estimated Savings Monthly USD"],
            "avg_cpu": row["Avg CPU 48h"],
            "action": row["Recommended Action"],
        }
        for row in top.to_dict("records")
    ]


def resource_detail(resource_id: str, hours: int = 168) -> dict[str, Any]:
    """Per-resource utilization history plus its current recommendation.

    Returns the trailing `hours` of hourly CPU, memory, disk and network so the
    UI can draw the four utilization sparklines for one machine.
    """
    df = _frame()
    match = df[df["VM"] == resource_id]
    if match.empty:
        return {}

    metrics = datacache.load_csv(VM_CSV, parse_dates=["timestamp"])
    history = metrics[metrics["resource_id"] == resource_id].sort_values("timestamp").tail(hours)

    series = {
        "cpu_percent": _series(history, "cpu_percent"),
        "memory_percent": _series(history, "memory_percent"),
        "disk_percent": _series(history, "disk_percent"),
        "network_percent": _series(history, "network_percent"),
    }
    timestamps = [ts.isoformat() for ts in history["timestamp"]] if "timestamp" in history else []

    return {
        "resource": resource_id,
        "recommendation": match.iloc[0].to_dict(),
        "timestamps": timestamps,
        "series": series,
        "current": {key: (values[-1] if values else 0.0) for key, values in series.items()},
        "peak": {key: (max(values) if values else 0.0) for key, values in series.items()},
    }


def _series(history: pd.DataFrame, column: str) -> list[float]:
    if column not in history or history.empty:
        return []
    return [round(float(value), 2) for value in history[column].fillna(0.0)]
