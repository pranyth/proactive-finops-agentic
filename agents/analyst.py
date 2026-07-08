"""Main FinOps Analyst Agent for the Vijay demo.

The public contract is intentionally one visible entry point:

    FinOpsAnalystAgent.run(question, context)

Everything else in this module is an internal tool used by that agent. The
business logic is deterministic for the capstone demo, while the data model is
structured so it can evolve into LangGraph/LangChain services later.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from agents.core import AgentAnswer

VM_CSV = Path("data/augmented_vm_metrics.csv")
DB_CSV = Path("data/db_metrics.csv")
TAGS_JSON = Path("data/vm_tags.json")
INVENTORY_CSV = Path("data/vm_inventory.csv")
COST_CSV = Path("data/cost_metrics.csv")
INCIDENTS_CSV = Path("data/incident_history.csv")
ACTIONS_CSV = Path("data/action_history.csv")
PIPELINES_CSV = Path("data/pipeline_runs.csv")
PROVENANCE_CSV = Path("data/data_provenance.csv")
MULTICLOUD_CSV = Path("data/multicloud_vm_metrics.csv")
OPEN_TRACE_PATTERNS_CSV = Path("data/open_trace_patterns.csv")
RAW_CORESTACK_DIR = Path("corestack_data")


PREPARED_QUESTIONS = [
    "Which VMs can be shut down during low peak hours?",
    "Which VMs need scale down?",
    "Which VMs are risky?",
    "Which applications are degraded?",
    "Is DB data required for this question?",
    "Why is this VM recommended?",
]


class DatasetProfiler:
    """Identifies the current demo dataset and what it can support."""

    def profile(self) -> dict[str, Any]:
        vm_df = self._load_csv(VM_CSV, parse_dates=["timestamp"])
        db_df = self._load_csv(DB_CSV, parse_dates=["timestamp"])
        inventory_df = self._load_csv(INVENTORY_CSV)
        cost_df = self._load_csv(COST_CSV, parse_dates=["date"])
        incident_df = self._load_csv(INCIDENTS_CSV, parse_dates=["opened_at", "closed_at"])
        action_df = self._load_csv(ACTIONS_CSV, parse_dates=["created_at"])
        pipeline_df = self._load_csv(PIPELINES_CSV, parse_dates=["created_at"])
        provenance_df = self._load_csv(PROVENANCE_CSV)
        multicloud_df = self._load_csv(MULTICLOUD_CSV, parse_dates=["timestamp"])
        patterns_df = self._load_csv(OPEN_TRACE_PATTERNS_CSV)
        tags = self._load_tags()

        tagged_vms = [vm for vm, info in tags.items() if info.get("application") != "untagged"]
        dataset_types = ["VM metrics", "DB metrics", "VM tags"]
        optional_types = [
            (inventory_df, "Enterprise VM inventory"),
            (cost_df, "Cost metrics"),
            (incident_df, "Incident history"),
            (action_df, "Action history"),
            (pipeline_df, "Pipeline runs"),
            (multicloud_df, "Normalized multi-cloud VM telemetry"),
            (patterns_df, "Open-source trace pattern references"),
            (provenance_df, "Data provenance"),
        ]
        dataset_types.extend(name for frame, name in optional_types if not frame.empty)

        source_files = [str(VM_CSV), str(DB_CSV), str(TAGS_JSON)]
        source_files.extend(str(path) for path in [
            INVENTORY_CSV, COST_CSV, INCIDENTS_CSV, ACTIONS_CSV, PIPELINES_CSV,
            MULTICLOUD_CSV, OPEN_TRACE_PATTERNS_CSV, PROVENANCE_CSV,
        ] if path.exists())

        provider_counts = self._counts(multicloud_df, "provider")
        source_system_counts = self._counts(multicloud_df, "source_system")
        source_type_counts = self._counts(multicloud_df, "source_type")
        schema_versions = sorted(multicloud_df["schema_version"].dropna().unique().tolist()) if "schema_version" in multicloud_df else []

        return {
            "dataset_name": "current_demo_data",
            "platform_scope": "multi_cloud",
            "primary_title": "Agentic Proactive FinOps Governance for Multi-Cloud Telemetry",
            "evaluation_note": "CoreStack-derived Azure telemetry plus AWS/GCP telemetry generated from open-source workload trace patterns.",
            "dataset_types": dataset_types,
            "source_files": source_files,
            "source_mix": self._source_mix(provenance_df),
            "multi_cloud_available": bool(not multicloud_df.empty),
            "enterprise_context_available": bool(not inventory_df.empty and not cost_df.empty),
            "vm_rows": int(len(vm_df)),
            "db_rows": int(len(db_df)),
            "multicloud_rows": int(len(multicloud_df)),
            "open_trace_pattern_rows": int(len(patterns_df)),
            "inventory_rows": int(len(inventory_df)),
            "cost_rows": int(len(cost_df)),
            "incident_rows": int(len(incident_df)),
            "action_rows": int(len(action_df)),
            "pipeline_rows": int(len(pipeline_df)),
            "provenance_rows": int(len(provenance_df)),
            "vm_count": int(vm_df["resource_id"].nunique()) if "resource_id" in vm_df else 0,
            "multicloud_resource_count": int(multicloud_df["resource_id"].nunique()) if "resource_id" in multicloud_df else 0,
            "provider_count": int(multicloud_df["provider"].nunique()) if "provider" in multicloud_df else 0,
            "providers": provider_counts,
            "source_systems": source_system_counts,
            "multicloud_source_types": source_type_counts,
            "schema_versions": schema_versions,
            "db_vm_count": int(db_df["resource_id"].nunique()) if "resource_id" in db_df else 0,
            "tag_records": int(len(tags)),
            "application_tagged_vms": int(len(tagged_vms)),
            "applications": sorted(db_df["application"].dropna().unique().tolist()) if "application" in db_df else [],
            "time_range": {
                "start": str(vm_df["timestamp"].min()) if "timestamp" in vm_df and not vm_df.empty else None,
                "end": str(vm_df["timestamp"].max()) if "timestamp" in vm_df and not vm_df.empty else None,
            },
            "multicloud_time_range": {
                "start": str(multicloud_df["timestamp"].min()) if "timestamp" in multicloud_df and not multicloud_df.empty else None,
                "end": str(multicloud_df["timestamp"].max()) if "timestamp" in multicloud_df and not multicloud_df.empty else None,
            },
            "available_columns": {
                "vm_metrics": list(vm_df.columns),
                "db_metrics": list(db_df.columns),
                "vm_tags": ["resource_id", "application", "app_owner", "portfolio_owner", "department"],
                "vm_inventory": list(inventory_df.columns),
                "cost_metrics": list(cost_df.columns),
                "incident_history": list(incident_df.columns),
                "action_history": list(action_df.columns),
                "pipeline_runs": list(pipeline_df.columns),
                "multicloud_vm_metrics": list(multicloud_df.columns),
                "open_trace_patterns": list(patterns_df.columns),
                "data_provenance": list(provenance_df.columns),
            },
            "missing_columns": self._missing_columns(vm_df, db_df, inventory_df, cost_df, multicloud_df),
            "raw_corestack_bson": "Available locally" if RAW_CORESTACK_DIR.exists() else "Not included",
            "raw_corestack_required": "Not required for current question/demo",
        }

    def _load_csv(self, path: Path, parse_dates: list[str] | None = None) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame()
        try:
            return pd.read_csv(path, parse_dates=parse_dates or [])
        except ValueError:
            return pd.read_csv(path)

    def _load_tags(self) -> dict[str, dict[str, Any]]:
        if not TAGS_JSON.exists():
            return {}
        with TAGS_JSON.open() as handle:
            return json.load(handle)

    def _source_mix(self, provenance_df: pd.DataFrame) -> dict[str, int]:
        if provenance_df.empty or "source_type" not in provenance_df:
            return {}
        return provenance_df["source_type"].value_counts().to_dict()

    def _counts(self, df: pd.DataFrame, column: str) -> dict[str, int]:
        if df.empty or column not in df:
            return {}
        return {str(key): int(value) for key, value in df[column].value_counts().to_dict().items()}

    def _missing_columns(
        self,
        vm_df: pd.DataFrame,
        db_df: pd.DataFrame,
        inventory_df: pd.DataFrame,
        cost_df: pd.DataFrame,
        multicloud_df: pd.DataFrame,
    ) -> dict[str, list[str]]:
        required_vm = {
            "timestamp", "resource_id", "cloud_provider", "cpu_percent",
            "memory_percent", "disk_percent", "network_percent", "workload_class",
        }
        required_db = {
            "timestamp", "resource_id", "application", "db_type", "db_connections",
            "db_query_latency_ms", "db_reads_per_sec", "db_writes_per_sec",
        }
        required_inventory = {"resource_id", "environment", "business_criticality", "shutdown_allowed", "hourly_rate_usd"}
        required_cost = {"date", "resource_id", "daily_cost", "source_type"}
        required_multicloud = {
            "timestamp", "provider", "source_system", "account_id", "region", "resource_id",
            "normalized_resource_id", "resource_type", "instance_type", "cpu_percent",
            "memory_percent", "disk_percent", "network_percent", "cost_per_hour",
            "application", "environment", "business_criticality", "workload_class",
            "schema_version", "source_type",
        }
        return {
            "vm_metrics": sorted(required_vm - set(vm_df.columns)),
            "db_metrics": sorted(required_db - set(db_df.columns)),
            "vm_inventory": sorted(required_inventory - set(inventory_df.columns)),
            "cost_metrics": sorted(required_cost - set(cost_df.columns)),
            "multicloud_vm_metrics": sorted(required_multicloud - set(multicloud_df.columns)),
        }

class RequirementChecker:
    """Maps an intent to required/optional/not-required data."""

    def check(self, intent: str, profile: dict[str, Any]) -> list[dict[str, str]]:
        vm_cols = profile["available_columns"]["vm_metrics"]
        inventory_cols = profile["available_columns"].get("vm_inventory", [])
        cost_cols = profile["available_columns"].get("cost_metrics", [])
        multicloud_cols = profile["available_columns"].get("multicloud_vm_metrics", [])
        base = {
            "VM telemetry": self._available(profile["vm_rows"] > 0),
            "CPU metric": self._available("cpu_percent" in vm_cols),
            "Network metric": self._available("network_percent" in vm_cols),
            "Workload class": self._available("workload_class" in vm_cols),
            "Application tags": "Available but optional" if profile["application_tagged_vms"] > 0 else "Missing optional",
            "Enterprise inventory": self._available("environment" in inventory_cols and profile["inventory_rows"] > 0),
            "Cost metrics": self._available("daily_cost" in cost_cols and profile["cost_rows"] > 0),
            "Multi-cloud schema": self._available("provider" in multicloud_cols and profile.get("provider_count", 0) >= 3),
            "Provider labels": self._available(profile.get("provider_count", 0) >= 3),
            "Open-source trace patterns": "Available but optional" if profile.get("open_trace_pattern_rows", 0) > 0 else "Missing optional",
            "Incident history": "Available but optional" if profile["incident_rows"] > 0 else "Missing optional",
            "DB metrics": "Available but optional" if profile["db_rows"] > 0 else "Missing optional",
            "Raw CoreStack BSON": "Not required",
        }

        if intent == "application_degraded":
            base["DB metrics"] = self._available(profile["db_rows"] > 0)
            base["Application tags"] = self._available(profile["application_tagged_vms"] > 0)
            base["Cost metrics"] = "Not required"
        elif intent == "db_required":
            base["DB metrics"] = "Depends on question"
            base["Cost metrics"] = "Required for savings/cost-impact questions"
            base["Raw CoreStack BSON"] = "Not required for demo answers"
        elif intent in {"low_peak_shutdown", "scale_down"}:
            base["Enterprise inventory"] = "Available and important"
            base["Cost metrics"] = "Available and important"
            base["Multi-cloud schema"] = "Available and important"
        elif intent == "risky_vms":
            base["Incident history"] = "Available and important"

        return [{"Requirement": key, "Status": value} for key, value in base.items()]

    def _available(self, ok: bool) -> str:
        return "Available" if ok else "Missing"


class FinOpsAnalystAgent:
    """One visible agent that profiles data, selects tools, and explains answers."""

    def __init__(self) -> None:
        self.profiler = DatasetProfiler()
        self.requirements = RequirementChecker()

    def run(self, question: str, context: dict[str, Any] | None = None) -> AgentAnswer:
        context = context or {"time_window": "latest_48h", "cloud": "azure"}
        profile = self.profiler.profile()
        intent = self._classify_intent(question)
        requirement_check = self.requirements.check(intent, profile)

        if intent == "low_peak_shutdown":
            answer, recs, evidence, tools, next_action = self._answer_low_peak_shutdown()
        elif intent == "scale_down":
            answer, recs, evidence, tools, next_action = self._answer_scale_down()
        elif intent == "risky_vms":
            answer, recs, evidence, tools, next_action = self._answer_risky_vms()
        elif intent == "application_degraded":
            answer, recs, evidence, tools, next_action = self._answer_applications_degraded()
        elif intent == "db_required":
            answer, recs, evidence, tools, next_action = self._answer_db_required()
        elif intent == "why_recommended":
            answer, recs, evidence, tools, next_action = self._answer_why_recommended()
        else:
            answer, recs, evidence, tools, next_action = self._answer_general(question)

        return AgentAnswer(
            answer=answer,
            intent=intent,
            dataset_profile=profile,
            requirement_check=requirement_check,
            recommendations=recs,
            evidence=evidence,
            tools_used=tools,
            next_action=next_action,
            context=context,
        )

    def to_dict(self, answer: AgentAnswer) -> dict[str, Any]:
        return asdict(answer)

    def _classify_intent(self, question: str) -> str:
        q = question.lower()
        if "shut" in q or "shutdown" in q or "low peak" in q or "less peak" in q:
            return "low_peak_shutdown"
        if "scale down" in q or "downsize" in q or "underutil" in q:
            return "scale_down"
        if "risky" in q or "risk" in q or "scale up" in q or "spike" in q:
            return "risky_vms"
        if "application" in q and ("degraded" in q or "risk" in q or "health" in q):
            return "application_degraded"
        if "db" in q and ("required" in q or "require" in q or "needed" in q):
            return "db_required"
        if "why" in q and ("recommend" in q or "recommended" in q):
            return "why_recommended"
        return "general_finops"

    def _load_csv(self, path: Path, parse_dates: list[str] | None = None) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame()
        try:
            return pd.read_csv(path, parse_dates=parse_dates or [])
        except ValueError:
            return pd.read_csv(path)

    def _load_vm_metrics(self) -> pd.DataFrame:
        return self._load_csv(VM_CSV, parse_dates=["timestamp"])

    def _load_db_metrics(self) -> pd.DataFrame:
        return self._load_csv(DB_CSV, parse_dates=["timestamp"])

    def _load_tags(self) -> dict[str, dict[str, Any]]:
        if not TAGS_JSON.exists():
            return {}
        with TAGS_JSON.open() as handle:
            return json.load(handle)

    def _load_inventory(self) -> pd.DataFrame:
        return self._load_csv(INVENTORY_CSV)

    def _load_cost(self) -> pd.DataFrame:
        return self._load_csv(COST_CSV, parse_dates=["date"])

    def _load_incidents(self) -> pd.DataFrame:
        return self._load_csv(INCIDENTS_CSV, parse_dates=["opened_at", "closed_at"])

    def _load_actions(self) -> pd.DataFrame:
        return self._load_csv(ACTIONS_CSV, parse_dates=["created_at"])

    def _load_multicloud(self) -> pd.DataFrame:
        return self._load_csv(MULTICLOUD_CSV, parse_dates=["timestamp"])

    def _multicloud_lookup(self, multicloud: pd.DataFrame) -> dict[str, dict[str, Any]]:
        if multicloud.empty or "resource_id" not in multicloud:
            return {}
        latest = multicloud.sort_values("timestamp").groupby("resource_id").tail(1)
        lookup: dict[str, dict[str, Any]] = {}
        for _, row in latest.iterrows():
            prefixed_id = str(row.get("resource_id", ""))
            original_id = prefixed_id.split("-", 1)[1] if "-" in prefixed_id else prefixed_id
            lookup[original_id] = {
                "provider": row.get("provider", "azure"),
                "source_system": row.get("source_system", "corestack"),
                "account_id": row.get("account_id", "unknown"),
                "region": row.get("region", "unknown"),
                "instance_type": row.get("instance_type", "unknown"),
                "resource_type": row.get("resource_type", "virtual_machine"),
                "schema_version": row.get("schema_version", "unknown"),
                "source_type": row.get("source_type", "unknown"),
            }
        return lookup

    def _vm_recommendation_frame(self) -> pd.DataFrame:
        df = self._load_vm_metrics()
        tags = self._load_tags()
        inventory = self._load_inventory()
        cost = self._load_cost()
        incidents = self._load_incidents()
        actions = self._load_actions()
        multicloud = self._load_multicloud()

        inventory_lookup = inventory.set_index("resource_id").to_dict("index") if "resource_id" in inventory else {}
        monthly_cost = self._monthly_cost_lookup(cost)
        incident_count = incidents.groupby("resource_id").size().to_dict() if "resource_id" in incidents else {}
        action_count = actions.groupby("resource_id").size().to_dict() if "resource_id" in actions else {}
        provider_lookup = self._multicloud_lookup(multicloud)

        rows = []
        for vm, group in df.groupby("resource_id"):
            group = group.sort_values("timestamp")
            latest = group.tail(48)
            cpu = group["cpu_percent"].fillna(0)
            latest_cpu = latest["cpu_percent"].fillna(0)
            latest_net = latest["network_percent"].fillna(0)
            threshold = float(cpu.mean() + 1.5 * cpu.std())
            avg_cpu = float(latest_cpu.mean())
            max_cpu = float(latest_cpu.max())
            avg_net = float(latest_net.mean())
            workload = str(group["workload_class"].iloc[0])
            app = tags.get(vm, {}).get("application", "untagged")
            inv = inventory_lookup.get(vm, {})
            cloud = provider_lookup.get(vm, {})
            environment = inv.get("environment", "unknown")
            criticality = inv.get("business_criticality", "medium")
            shutdown_allowed = bool(inv.get("shutdown_allowed", False))
            approval_required = bool(inv.get("approval_required", True))
            owner = inv.get("owner", tags.get(vm, {}).get("app_owner", "unknown"))
            region = inv.get("region", "unknown")
            vm_sku = inv.get("vm_sku", "unknown")
            monthly = float(monthly_cost.get(vm, 0.0))
            savings_pct = self._savings_pct(avg_cpu, workload, environment, shutdown_allowed)
            estimated_savings = round(monthly * savings_pct, 2)
            incidents_seen = int(incident_count.get(vm, 0))
            actions_seen = int(action_count.get(vm, 0))
            is_tagged = app != "untagged"
            non_critical = environment != "prod" and criticality != "high"
            is_shutdown_candidate = (
                avg_cpu < 2.0
                and avg_net < 18.0
                and workload in {"truly_idle", "low_variable"}
                and shutdown_allowed
                and non_critical
            )
            is_scale_down = avg_cpu < threshold * 0.30 and threshold > 5.0 and criticality != "high"
            is_risky = max_cpu > threshold or avg_cpu > threshold * 0.85 or (criticality == "high" and incidents_seen > 0)
            confidence = self._confidence(avg_cpu, avg_net, incidents_seen, criticality, is_shutdown_candidate, is_scale_down, is_risky)
            action = self._recommended_action(is_shutdown_candidate, is_scale_down, is_risky)
            rows.append({
                "VM": vm,
                "Provider": cloud.get("provider", "azure"),
                "Source System": cloud.get("source_system", "corestack"),
                "Account ID": cloud.get("account_id", "unknown"),
                "Instance Type": cloud.get("instance_type", vm_sku),
                "Resource Type": cloud.get("resource_type", "virtual_machine"),
                "Schema Version": cloud.get("schema_version", "legacy"),
                "Telemetry Source": cloud.get("source_type", "corestack_derived"),
                "Application": app,
                "Tagged": "Yes" if is_tagged else "No",
                "Environment": environment,
                "Business Criticality": criticality,
                "Shutdown Allowed": "Yes" if shutdown_allowed else "No",
                "Approval Required": "Yes" if approval_required else "No",
                "Owner": owner,
                "Region": region,
                "VM SKU": vm_sku,
                "Workload Class": workload,
                "Avg CPU 48h": round(avg_cpu, 2),
                "Max CPU 48h": round(max_cpu, 2),
                "Avg Network 48h": round(avg_net, 2),
                "Dynamic Threshold": round(threshold, 2),
                "Estimated Monthly Cost USD": round(monthly, 2),
                "Estimated Savings Monthly USD": estimated_savings,
                "Incident Count": incidents_seen,
                "Historical Action Count": actions_seen,
                "Shutdown Candidate": is_shutdown_candidate,
                "Scale Down Candidate": is_scale_down,
                "Risky": is_risky,
                "Recommended Action": action,
                "Confidence": confidence,
                "Business Impact": self._business_impact(environment, criticality, estimated_savings, incidents_seen, action),
                "Reason": self._recommendation_reason(avg_cpu, avg_net, threshold, workload, app, environment, criticality, shutdown_allowed, estimated_savings, incidents_seen),
            })
        return pd.DataFrame(rows)

    def _monthly_cost_lookup(self, cost: pd.DataFrame) -> dict[str, float]:
        if cost.empty or "resource_id" not in cost:
            return {}
        daily = cost.groupby("resource_id")["daily_cost"].mean() if "daily_cost" in cost else pd.Series(dtype=float)
        return (daily * 30).round(2).to_dict()

    def _savings_pct(self, avg_cpu: float, workload: str, environment: str, shutdown_allowed: bool) -> float:
        if shutdown_allowed and environment != "prod" and avg_cpu < 2.0 and workload in {"truly_idle", "low_variable"}:
            return 0.45
        if avg_cpu < 8.0:
            return 0.22
        if avg_cpu < 18.0:
            return 0.12
        return 0.0

    def _confidence(
        self,
        avg_cpu: float,
        avg_net: float,
        incidents_seen: int,
        criticality: str,
        shutdown: bool,
        scale_down: bool,
        risky: bool,
    ) -> float:
        if shutdown:
            score = 58 + (2.0 - avg_cpu) * 12 + max(0.0, 18.0 - avg_net) * 0.8
        elif scale_down:
            score = 62 + max(0.0, 15.0 - avg_cpu) * 1.5
        elif risky:
            score = 64 + min(18, incidents_seen * 5) + (8 if criticality == "high" else 0)
        else:
            score = 48
        return round(min(98.0, max(35.0, score)), 1)

    def _recommended_action(self, shutdown: bool, scale_down: bool, risky: bool) -> str:
        if shutdown:
            return "SCHEDULE_SHUTDOWN"
        if scale_down:
            return "SCALE_DOWN"
        if risky:
            return "APPLICATION_REVIEW"
        return "NO_ACTION"

    def _business_impact(self, environment: str, criticality: str, savings: float, incidents_seen: int, action: str) -> str:
        if action == "SCHEDULE_SHUTDOWN":
            return f"Low business risk in {environment}; estimated monthly savings ${savings:,.2f}."
        if action == "SCALE_DOWN":
            return f"Moderate savings opportunity ${savings:,.2f}; owner approval recommended."
        if action == "APPLICATION_REVIEW":
            return f"{criticality.title()} criticality with {incidents_seen} related incidents; avoid automated remediation."
        return "No immediate cost or reliability action required."

    def _recommendation_reason(
        self,
        avg_cpu: float,
        avg_net: float,
        threshold: float,
        workload: str,
        app: str,
        environment: str,
        criticality: str,
        shutdown_allowed: bool,
        estimated_savings: float,
        incidents_seen: int,
    ) -> str:
        if avg_cpu < 2.0 and avg_net < 18.0 and workload in {"truly_idle", "low_variable"}:
            approval = "shutdown is policy-allowed" if shutdown_allowed else "shutdown needs policy approval"
            return (
                f"Low CPU/network with {workload} class; {approval}; "
                f"{environment}/{criticality} context; estimated savings ${estimated_savings:,.2f}."
            )
        if avg_cpu < threshold * 0.30 and threshold > 5.0:
            return f"Recent CPU is far below dynamic threshold {threshold:.1f}%, with business context from {app}."
        if avg_cpu > threshold or incidents_seen > 0:
            return f"Recent CPU or incident history indicates risk; threshold {threshold:.1f}%, incidents {incidents_seen}."
        return "Recent utilization is within normal range."

    def _answer_low_peak_shutdown(self):
        recs_df = self._vm_recommendation_frame()
        candidates = recs_df[recs_df["Shutdown Candidate"]].sort_values(
            ["Estimated Savings Monthly USD", "Confidence", "Avg CPU 48h"], ascending=[False, False, True]
        ).head(12)
        total_savings = float(candidates["Estimated Savings Monthly USD"].sum()) if not candidates.empty else 0.0
        answer = (
            f"I found {len(candidates)} VM candidates for low-peak shutdown review, with estimated monthly savings of "
            f"${total_savings:,.2f}. These are low-utilization, non-critical, policy-allowed candidates."
        )
        return (
            answer,
            candidates.to_dict("records"),
            {
                "chart_type": "low_peak_table",
                "total_candidates": int(len(candidates)),
                "estimated_monthly_savings_usd": round(total_savings, 2),
                "source_note": "Real VM telemetry plus synthetic enterprise/cost context with provenance tracking.",
            },
            ["Dataset Profiler", "Requirement Checker", "Knowledge/Context Tool", "Low-Peak Shutdown Tool", "Recommendation Tool"],
            "Review owner approvals, then send approved VMs to the Serverless Action Tool for scheduled shutdown.",
        )

    def _answer_scale_down(self):
        recs_df = self._vm_recommendation_frame()
        candidates = recs_df[recs_df["Scale Down Candidate"]].sort_values("Estimated Savings Monthly USD", ascending=False).head(12)
        savings = float(candidates["Estimated Savings Monthly USD"].sum()) if not candidates.empty else 0.0
        answer = f"I found {len(candidates)} VMs that can be reviewed for scale down, representing about ${savings:,.2f} in monthly savings potential."
        return (
            answer,
            candidates.to_dict("records"),
            {"chart_type": "scale_down_table", "total_candidates": int(len(candidates)), "estimated_monthly_savings_usd": round(savings, 2)},
            ["Dataset Profiler", "Requirement Checker", "Knowledge/Context Tool", "Recommendation Tool"],
            "Validate owner/application impact before rightsizing.",
        )

    def _answer_risky_vms(self):
        recs_df = self._vm_recommendation_frame()
        recs_df["Risk Score"] = (
            recs_df["Max CPU 48h"] / recs_df["Dynamic Threshold"].clip(lower=1)
            + recs_df["Incident Count"] * 0.15
            + recs_df["Business Criticality"].map({"high": 0.35, "medium": 0.12, "low": 0.0}).fillna(0)
        ).round(2)
        risky = recs_df.sort_values("Risk Score", ascending=False).head(12)
        answer = f"The highest-risk VMs combine utilization spikes, incident history, and business criticality. I ranked the top {len(risky)} by composite risk score."
        return (
            answer,
            risky.to_dict("records"),
            {"chart_type": "risk_ranking", "highest_risk_score": float(risky["Risk Score"].max()) if not risky.empty else 0.0},
            ["Dataset Profiler", "Requirement Checker", "Risk Ranking Tool", "Incident Context Tool", "Dynamic Threshold Tool"],
            "Inspect top risky VMs in the forecasting dashboard before action.",
        )

    def _answer_applications_degraded(self):
        db_df = self._load_db_metrics()
        inventory = self._load_inventory()
        incident_df = self._load_incidents()
        inv_cols = ["resource_id", "business_criticality", "environment"]
        if not inventory.empty and all(col in inventory.columns for col in inv_cols):
            db_df = db_df.merge(inventory[inv_cols], on="resource_id", how="left")
        rows = []
        for app, group in db_df.groupby("application"):
            avg_latency = float(group["db_query_latency_ms"].mean())
            max_latency = float(group["db_query_latency_ms"].max())
            min_conn = int(group["db_connections"].min())
            avg_reads = float(group["db_reads_per_sec"].mean())
            high_critical = int((group.get("business_criticality", pd.Series(dtype=str)) == "high").sum())
            related_incidents = 0
            if not incident_df.empty and "application" in incident_df:
                related_incidents = int((incident_df["application"] == app).sum())
            health_score = max(0.0, 100.0 - min(55.0, avg_latency * 1.6) - max(0.0, (12 - min_conn) * 3.0) - related_incidents * 4)
            status = "Degraded" if health_score < 70 or max_latency > 90 or min_conn < 10 else "Healthy"
            rows.append({
                "Application": app,
                "VM Count": int(group["resource_id"].nunique()),
                "Avg Latency ms": round(avg_latency, 2),
                "Max Latency ms": round(max_latency, 2),
                "Min DB Connections": min_conn,
                "Avg Reads/sec": round(avg_reads, 1),
                "High Criticality Samples": high_critical,
                "Related Incidents": related_incidents,
                "Health Score": round(health_score, 1),
                "Status": status,
                "Reason": "Latency/connection degradation detected" if status == "Degraded" else "DB metrics are within expected demo range",
            })
        result = pd.DataFrame(rows).sort_values("Health Score")
        degraded = result[result["Status"] == "Degraded"] if not result.empty else pd.DataFrame()
        answer = f"I found {len(degraded)} applications that should be reviewed for degradation using DB latency, connection, incident, and criticality signals."
        return (
            answer,
            result.to_dict("records"),
            {"chart_type": "application_health", "degraded_count": int(len(degraded))},
            ["Dataset Profiler", "Requirement Checker", "App/DB Health Tool", "Incident Context Tool"],
            "Open the DB dashboard for time-series validation of degraded applications.",
        )

    def _answer_db_required(self):
        answer = (
            "DB data is not required for first-pass VM shutdown or scale-down recommendations. "
            "It is required for application degradation questions. Cost and inventory data are required when the answer must include savings, approval risk, or business impact."
        )
        recs = [
            {"Question Type": "Low-peak VM shutdown", "DB Required": "No", "Other Required Context": "VM telemetry, inventory, shutdown policy, cost", "Why": "CPU/network identify candidates; inventory/cost make it business-safe."},
            {"Question Type": "VM scale down", "DB Required": "No", "Other Required Context": "VM telemetry, cost, owner/app tags", "Why": "Rightsizing can start from utilization and savings."},
            {"Question Type": "Application degraded", "DB Required": "Yes", "Other Required Context": "App tags and incidents", "Why": "Need DB connections, latency, reads, and writes."},
            {"Question Type": "Paper-grade evaluation", "DB Required": "Depends", "Other Required Context": "Provenance labels", "Why": "Synthetic/open-source-inspired context must be clearly separated from real telemetry."},
        ]
        return (
            answer,
            recs,
            {"chart_type": "data_requirement_matrix"},
            ["Dataset Profiler", "Requirement Checker"],
            "Use provenance labels when presenting or publishing results.",
        )

    def _answer_why_recommended(self):
        recs_df = self._vm_recommendation_frame()
        priority = recs_df[
            recs_df["Shutdown Candidate"] | recs_df["Scale Down Candidate"] | recs_df["Risky"]
        ].copy()
        if priority.empty:
            priority = recs_df.sort_values("Avg CPU 48h").head(1)
        else:
            priority = priority.sort_values(
                ["Estimated Savings Monthly USD", "Confidence", "Risky"], ascending=[False, False, False]
            ).head(1)
        row = priority.iloc[0].to_dict()
        answer = (
            f"{row['VM']} is recommended as {row['Recommended Action']} because: {row['Reason']} "
            f"The agent also considered environment={row['Environment']}, criticality={row['Business Criticality']}, "
            f"approval_required={row['Approval Required']}, incidents={row['Incident Count']}, and estimated savings=${row['Estimated Savings Monthly USD']:,.2f}."
        )
        return (
            answer,
            [row],
            {"chart_type": "single_vm_explanation", "vm": row["VM"]},
            ["Dataset Profiler", "Requirement Checker", "Recommendation Tool", "Knowledge/Context Tool", "Explanation Generator"],
            "Use this explanation format for every recommendation before triggering automation.",
        )

    def _answer_general(self, question: str):
        recs_df = self._vm_recommendation_frame()
        candidates = recs_df[recs_df["Shutdown Candidate"]].head(5)
        answer = (
            "I identified the current demo dataset and can answer VM shutdown, scale-down, risk, DB health, "
            "and data requirement questions. For this general query, I am showing top low-peak candidates with business context."
        )
        return (
            answer,
            candidates.to_dict("records"),
            {"chart_type": "general_summary", "question": question},
            ["Dataset Profiler", "Requirement Checker", "Knowledge/Context Tool", "Recommendation Tool"],
            "Choose one of the prepared demo questions for a sharper answer.",
        )
