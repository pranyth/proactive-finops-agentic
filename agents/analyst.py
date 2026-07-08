"""Main FinOps Analyst Agent for the Phase 3 Vijay demo.

The public contract is intentionally one visible entry point:

    FinOpsAnalystAgent.run(question, context)

Everything else in this module is an internal tool used by that agent.
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
        vm_df = self._load_vm_metrics()
        db_df = self._load_db_metrics()
        tags = self._load_tags()

        tagged_vms = [vm for vm, info in tags.items() if info.get("application") != "untagged"]
        profile = {
            "dataset_name": "current_demo_data",
            "dataset_types": ["VM metrics", "DB metrics", "VM tags"],
            "source_files": [str(VM_CSV), str(DB_CSV), str(TAGS_JSON)],
            "vm_rows": int(len(vm_df)),
            "db_rows": int(len(db_df)),
            "vm_count": int(vm_df["resource_id"].nunique()),
            "db_vm_count": int(db_df["resource_id"].nunique()),
            "tag_records": int(len(tags)),
            "application_tagged_vms": int(len(tagged_vms)),
            "applications": sorted(db_df["application"].dropna().unique().tolist()) if not db_df.empty else [],
            "time_range": {
                "start": str(vm_df["timestamp"].min()) if not vm_df.empty else None,
                "end": str(vm_df["timestamp"].max()) if not vm_df.empty else None,
            },
            "available_columns": {
                "vm_metrics": list(vm_df.columns),
                "db_metrics": list(db_df.columns),
                "vm_tags": ["resource_id", "application", "app_owner", "portfolio_owner", "department"],
            },
            "missing_columns": self._missing_columns(vm_df, db_df),
            "raw_corestack_bson": "Available locally" if RAW_CORESTACK_DIR.exists() else "Not included",
            "raw_corestack_required": "Not required for current question/demo",
        }
        return profile

    def _load_vm_metrics(self) -> pd.DataFrame:
        return pd.read_csv(VM_CSV, parse_dates=["timestamp"])

    def _load_db_metrics(self) -> pd.DataFrame:
        return pd.read_csv(DB_CSV, parse_dates=["timestamp"])

    def _load_tags(self) -> dict[str, dict[str, Any]]:
        with TAGS_JSON.open() as handle:
            return json.load(handle)

    def _missing_columns(self, vm_df: pd.DataFrame, db_df: pd.DataFrame) -> dict[str, list[str]]:
        required_vm = {
            "timestamp", "resource_id", "cloud_provider", "cpu_percent",
            "memory_percent", "disk_percent", "network_percent", "workload_class",
        }
        required_db = {
            "timestamp", "resource_id", "application", "db_type", "db_connections",
            "db_query_latency_ms", "db_reads_per_sec", "db_writes_per_sec",
        }
        return {
            "vm_metrics": sorted(required_vm - set(vm_df.columns)),
            "db_metrics": sorted(required_db - set(db_df.columns)),
        }


class RequirementChecker:
    """Maps an intent to required/optional/not-required data."""

    def check(self, intent: str, profile: dict[str, Any]) -> list[dict[str, str]]:
        base = {
            "VM telemetry": self._available(profile["vm_rows"] > 0),
            "CPU metric": self._available("cpu_percent" in profile["available_columns"]["vm_metrics"]),
            "Network metric": self._available("network_percent" in profile["available_columns"]["vm_metrics"]),
            "Workload class": self._available("workload_class" in profile["available_columns"]["vm_metrics"]),
            "Application tags": "Available but optional" if profile["application_tagged_vms"] > 0 else "Missing optional",
            "DB metrics": "Available but optional" if profile["db_rows"] > 0 else "Missing optional",
            "Raw CoreStack BSON": "Not required",
        }

        if intent == "application_degraded":
            base["DB metrics"] = self._available(profile["db_rows"] > 0)
            base["Application tags"] = self._available(profile["application_tagged_vms"] > 0)
        elif intent == "db_required":
            base["DB metrics"] = "Depends on question"
            base["Raw CoreStack BSON"] = "Not required for demo answers"
        elif intent == "regenerate_raw_pipeline":
            base["Raw CoreStack BSON"] = self._available(profile["raw_corestack_bson"] == "Available locally")

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

    def _load_vm_metrics(self) -> pd.DataFrame:
        return pd.read_csv(VM_CSV, parse_dates=["timestamp"])

    def _load_db_metrics(self) -> pd.DataFrame:
        return pd.read_csv(DB_CSV, parse_dates=["timestamp"])

    def _load_tags(self) -> dict[str, dict[str, Any]]:
        with TAGS_JSON.open() as handle:
            return json.load(handle)

    def _vm_recommendation_frame(self) -> pd.DataFrame:
        df = self._load_vm_metrics()
        tags = self._load_tags()
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
            is_tagged = app != "untagged"
            is_shutdown_candidate = avg_cpu < 2.0 and avg_net < 18.0 and workload in {"truly_idle", "low_variable"}
            is_scale_down = avg_cpu < threshold * 0.30 and threshold > 5.0
            is_risky = max_cpu > threshold or avg_cpu > threshold * 0.85
            rows.append({
                "VM": vm,
                "Application": app,
                "Tagged": "Yes" if is_tagged else "No",
                "Workload Class": workload,
                "Avg CPU 48h": round(avg_cpu, 2),
                "Max CPU 48h": round(max_cpu, 2),
                "Avg Network 48h": round(avg_net, 2),
                "Dynamic Threshold": round(threshold, 2),
                "Shutdown Candidate": is_shutdown_candidate,
                "Scale Down Candidate": is_scale_down,
                "Risky": is_risky,
                "Confidence": round(min(98.0, max(35.0, (2.5 - avg_cpu) * 20 + (18.0 - avg_net) * 1.2)), 1),
                "Reason": self._recommendation_reason(avg_cpu, avg_net, threshold, workload, app),
            })
        return pd.DataFrame(rows)

    def _recommendation_reason(self, avg_cpu: float, avg_net: float, threshold: float, workload: str, app: str) -> str:
        if avg_cpu < 2.0 and avg_net < 18.0 and workload in {"truly_idle", "low_variable"}:
            tag_note = "tagged app check required" if app != "untagged" else "no app dependency tag found"
            return f"Low recent CPU/network with {workload} class; {tag_note}."
        if avg_cpu < threshold * 0.30 and threshold > 5.0:
            return f"Recent CPU is far below dynamic threshold {threshold:.1f}%."
        if avg_cpu > threshold:
            return f"Recent CPU exceeds dynamic threshold {threshold:.1f}%."
        return "Recent utilization is within normal range."

    def _answer_low_peak_shutdown(self):
        recs_df = self._vm_recommendation_frame()
        candidates = recs_df[recs_df["Shutdown Candidate"]].sort_values(
            ["Tagged", "Confidence", "Avg CPU 48h"], ascending=[True, False, True]
        ).head(12)
        answer = (
            f"I found {len(candidates)} VM candidates for low-peak shutdown review. "
            "These have low recent CPU/network usage and non-production-style workload behavior."
        )
        return (
            answer,
            candidates.to_dict("records"),
            {
                "chart_type": "low_peak_table",
                "total_candidates": int(len(candidates)),
                "untagged_candidates": int((candidates["Tagged"] == "No").sum()) if not candidates.empty else 0,
            },
            ["Dataset Profiler", "Requirement Checker", "Low-Peak Shutdown Tool", "Recommendation Tool"],
            "Review candidates, then send approved VMs to Serverless Action Tool for scheduled shutdown.",
        )

    def _answer_scale_down(self):
        recs_df = self._vm_recommendation_frame()
        candidates = recs_df[recs_df["Scale Down Candidate"]].sort_values("Avg CPU 48h").head(12)
        answer = f"I found {len(candidates)} VMs that are under their normal dynamic threshold and can be reviewed for scale down."
        return (
            answer,
            candidates.to_dict("records"),
            {"chart_type": "scale_down_table", "total_candidates": int(len(candidates))},
            ["Dataset Profiler", "Requirement Checker", "Recommendation Tool"],
            "Validate owner/application impact before rightsizing.",
        )

    def _answer_risky_vms(self):
        recs_df = self._vm_recommendation_frame()
        recs_df["Risk Score"] = (recs_df["Max CPU 48h"] / recs_df["Dynamic Threshold"].clip(lower=1)).round(2)
        risky = recs_df.sort_values("Risk Score", ascending=False).head(12)
        answer = f"The highest-risk VMs are the ones whose recent CPU peaks are closest to or above their dynamic thresholds. I ranked the top {len(risky)} by risk score."
        return (
            answer,
            risky.to_dict("records"),
            {"chart_type": "risk_ranking", "highest_risk_score": float(risky["Risk Score"].max()) if not risky.empty else 0.0},
            ["Dataset Profiler", "Requirement Checker", "Risk Ranking Tool", "Dynamic Threshold Tool"],
            "Inspect top risky VMs in the forecasting dashboard before action.",
        )

    def _answer_applications_degraded(self):
        db_df = self._load_db_metrics()
        rows = []
        for app, group in db_df.groupby("application"):
            avg_latency = float(group["db_query_latency_ms"].mean())
            max_latency = float(group["db_query_latency_ms"].max())
            min_conn = int(group["db_connections"].min())
            avg_reads = float(group["db_reads_per_sec"].mean())
            health_score = max(0.0, 100.0 - min(55.0, avg_latency * 1.6) - max(0.0, (12 - min_conn) * 3.0))
            status = "Degraded" if health_score < 70 or max_latency > 90 or min_conn < 10 else "Healthy"
            rows.append({
                "Application": app,
                "VM Count": int(group["resource_id"].nunique()),
                "Avg Latency ms": round(avg_latency, 2),
                "Max Latency ms": round(max_latency, 2),
                "Min DB Connections": min_conn,
                "Avg Reads/sec": round(avg_reads, 1),
                "Health Score": round(health_score, 1),
                "Status": status,
                "Reason": "Latency/connection degradation detected" if status == "Degraded" else "DB metrics are within expected demo range",
            })
        result = pd.DataFrame(rows).sort_values("Health Score")
        degraded = result[result["Status"] == "Degraded"]
        answer = f"I found {len(degraded)} applications that should be reviewed for degradation using DB latency and connection signals."
        return (
            answer,
            result.to_dict("records"),
            {"chart_type": "application_health", "degraded_count": int(len(degraded))},
            ["Dataset Profiler", "Requirement Checker", "App/DB Health Tool"],
            "Open the DB dashboard for time-series validation of degraded applications.",
        )

    def _answer_db_required(self):
        answer = (
            "DB data is not required for VM shutdown or scale-down recommendations. "
            "It is required when the question is about application degradation, DB latency, DB connections, or VM-to-application impact."
        )
        recs = [
            {"Question Type": "Low-peak VM shutdown", "DB Required": "No", "Why": "CPU/network/workload class are enough for first-pass candidates."},
            {"Question Type": "VM scale down", "DB Required": "No", "Why": "Rightsizing can start from VM utilization."},
            {"Question Type": "Application degraded", "DB Required": "Yes", "Why": "Need DB connections, latency, reads, and writes."},
            {"Question Type": "Why is app slow", "DB Required": "Yes", "Why": "Application health needs DB and VM correlation."},
        ]
        return (
            answer,
            recs,
            {"chart_type": "data_requirement_matrix"},
            ["Dataset Profiler", "Requirement Checker"],
            "Ask a VM question without DB data, or an application health question with DB metrics enabled.",
        )

    def _answer_why_recommended(self):
        recs_df = self._vm_recommendation_frame()
        priority = recs_df[
            recs_df["Shutdown Candidate"] | recs_df["Scale Down Candidate"] | recs_df["Risky"]
        ].copy()
        if priority.empty:
            priority = recs_df.sort_values("Avg CPU 48h").head(1)
        else:
            priority = priority.sort_values(["Shutdown Candidate", "Scale Down Candidate", "Risky"], ascending=False).head(1)
        row = priority.iloc[0].to_dict()
        answer = (
            f"{row['VM']} is recommended because its recent utilization pattern matches the agent rule: "
            f"{row['Reason']} The decision used CPU, network, workload class, dynamic threshold, and application tag context."
        )
        return (
            answer,
            [row],
            {"chart_type": "single_vm_explanation", "vm": row["VM"]},
            ["Dataset Profiler", "Requirement Checker", "Recommendation Tool", "Explanation Generator"],
            "Use this explanation format for every recommendation before triggering automation.",
        )

    def _answer_general(self, question: str):
        recs_df = self._vm_recommendation_frame()
        candidates = recs_df[recs_df["Shutdown Candidate"]].head(5)
        answer = (
            "I identified the current demo dataset and can answer VM shutdown, scale-down, risk, DB health, "
            "and data requirement questions. For this general query, I am showing the top low-peak candidates."
        )
        return (
            answer,
            candidates.to_dict("records"),
            {"chart_type": "general_summary", "question": question},
            ["Dataset Profiler", "Requirement Checker", "Recommendation Tool"],
            "Choose one of the prepared demo questions for a sharper answer.",
        )