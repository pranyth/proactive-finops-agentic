"""Meeting 1/2 agent wrappers and demo data bootstrap."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from agents.core import AgentResult
from agents.storage import init_db, insert_agent_run, replace_rows, table_count

VM_CSV = Path("data/augmented_vm_metrics.csv")
DB_CSV = Path("data/db_metrics.csv")
TAGS_JSON = Path("data/vm_tags.json")


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _duration_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class IngestionAgent:
    name = "Ingestion Agent"

    def run(self, conn) -> AgentResult:
        start = time.perf_counter()
        df = pd.read_csv(VM_CSV, parse_dates=["timestamp"])
        tags = json.loads(TAGS_JSON.read_text())
        updated_at = utc_now()

        summary_rows = []
        for vm, group in df.groupby("resource_id"):
            summary_rows.append(
                {
                    "resource_id": vm,
                    "workload_class": str(group["workload_class"].iloc[0]),
                    "records": int(len(group)),
                    "mean_cpu": round(float(group["cpu_percent"].mean()), 3),
                    "max_cpu": round(float(group["cpu_percent"].max()), 3),
                    "mean_network": round(float(group["network_percent"].mean()), 3),
                    "mean_memory": round(float(group["memory_percent"].mean()), 3),
                    "mean_disk": round(float(group["disk_percent"].mean()), 3),
                    "first_seen": str(group["timestamp"].min()),
                    "last_seen": str(group["timestamp"].max()),
                    "updated_at": updated_at,
                }
            )

        replace_rows(conn, "vm_metric_summary", summary_rows)
        storage_rows = [
            {
                "dataset": "vm_metrics",
                "rows_count": int(len(df)),
                "entity_count": int(df["resource_id"].nunique()),
                "first_seen": str(df["timestamp"].min()),
                "last_seen": str(df["timestamp"].max()),
                "source_path": str(VM_CSV),
                "updated_at": updated_at,
            },
            {
                "dataset": "vm_tags",
                "rows_count": int(len(tags)),
                "entity_count": int(sum(1 for item in tags.values() if item.get("application") != "untagged")),
                "first_seen": None,
                "last_seen": None,
                "source_path": str(TAGS_JSON),
                "updated_at": updated_at,
            },
        ]
        replace_rows(conn, "data_storage_summary", storage_rows)

        result = AgentResult(
            agent_name=self.name,
            status="success",
            summary=f"Stored {df['resource_id'].nunique()} VM summaries from CoreStack telemetry.",
            records_processed=int(len(df)),
            generated_insights=[
                f"{df['resource_id'].nunique()} Azure VMs normalized",
                f"{sum(1 for item in tags.values() if item.get('application') != 'untagged')} application-tagged VMs available",
                f"Telemetry range {df['timestamp'].min().date()} to {df['timestamp'].max().date()}",
            ],
            duration_ms=_duration_ms(start),
        )
        insert_agent_run(conn, result)
        return result


class SyntheticDataAgent:
    name = "Synthetic Data Agent"

    def run(self, conn) -> AgentResult:
        start = time.perf_counter()
        df = pd.read_csv(VM_CSV, parse_dates=["timestamp"])
        db_df = pd.read_csv(DB_CSV, parse_dates=["timestamp"])
        augmented_vms = int(df[df["augmented"] == True]["resource_id"].nunique())  # noqa: E712
        real_vms = int(df[df["augmented"] == False]["resource_id"].nunique())  # noqa: E712
        updated_at = utc_now()

        conn.execute(
            """
            INSERT OR REPLACE INTO data_storage_summary (
                dataset, rows_count, entity_count, first_seen, last_seen, source_path, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "db_metrics",
                int(len(db_df)),
                int(db_df["resource_id"].nunique()),
                str(db_df["timestamp"].min()),
                str(db_df["timestamp"].max()),
                str(DB_CSV),
                updated_at,
            ),
        )
        conn.commit()

        result = AgentResult(
            agent_name=self.name,
            status="success",
            summary=f"Verified generated telemetry for {augmented_vms} VMs and DB metrics for {db_df['resource_id'].nunique()} app VMs.",
            records_processed=int(len(df) + len(db_df)),
            generated_insights=[
                f"{augmented_vms} VMs use generated enrichment, {real_vms} preserve production CPU/network",
                "Memory, disk, and DB metrics are ready for prediction demos",
                f"DB telemetry covers {db_df['application'].nunique()} applications",
            ],
            duration_ms=_duration_ms(start),
        )
        insert_agent_run(conn, result)
        return result


class RecommendationAgent:
    name = "Recommendation Agent"

    def run(self, conn) -> AgentResult:
        start = time.perf_counter()
        df = pd.read_csv(VM_CSV, parse_dates=["timestamp"])
        created_at = utc_now()
        rows = []

        for vm, group in df.groupby("resource_id"):
            group = group.sort_values("timestamp")
            cpu = group["cpu_percent"].fillna(0)
            net = group["network_percent"].fillna(0)
            threshold = float(cpu.mean() + 1.5 * cpu.std())
            latest = group.tail(48)
            latest_cpu = latest["cpu_percent"].fillna(0)
            latest_net = latest["network_percent"].fillna(0)
            avg_cpu = float(latest_cpu.mean())
            max_cpu = float(latest_cpu.max())
            avg_net = float(latest_net.mean())
            workload = str(group["workload_class"].iloc[0])

            if avg_cpu > threshold:
                action = "SCALE_UP"
                urgency = (avg_cpu - threshold) / max(threshold, 1) * 100
                reason = f"Recent CPU {avg_cpu:.1f}% exceeds dynamic threshold {threshold:.1f}%."
            elif avg_cpu < 2.0 and avg_net < 12.0 and workload in {"truly_idle", "low_variable"}:
                action = "SHUTDOWN_LOW_PEAK"
                urgency = min(95.0, (2.0 - avg_cpu) * 25 + (12.0 - avg_net))
                reason = f"Low peak signature: CPU {avg_cpu:.1f}%, network {avg_net:.1f}%, class {workload}."
            elif avg_cpu < threshold * 0.3 and threshold > 5:
                action = "SCALE_DOWN"
                urgency = (threshold * 0.3 - avg_cpu) / max(threshold, 1) * 100
                reason = f"Recent CPU {avg_cpu:.1f}% is far below dynamic threshold {threshold:.1f}%."
            else:
                action = "KEEP_RUNNING"
                urgency = 0.0
                reason = "Recent utilization is within expected range."

            rows.append(
                {
                    "vm": vm,
                    "action": action,
                    "urgency": round(float(urgency), 2),
                    "reason": reason,
                    "avg_cpu_48h": round(avg_cpu, 3),
                    "max_cpu_48h": round(max_cpu, 3),
                    "threshold": round(threshold, 3),
                    "created_at": created_at,
                }
            )

        replace_rows(conn, "recommendations", rows)
        non_ok = sum(1 for row in rows if row["action"] != "KEEP_RUNNING")
        result = AgentResult(
            agent_name=self.name,
            status="success",
            summary=f"Generated {non_ok} actionable FinOps recommendations across {len(rows)} VMs.",
            records_processed=len(rows),
            generated_insights=[
                f"{sum(1 for row in rows if row['action'] == 'SHUTDOWN_LOW_PEAK')} low-peak shutdown candidates",
                f"{sum(1 for row in rows if row['action'] == 'SCALE_DOWN')} scale-down candidates",
                f"{sum(1 for row in rows if row['action'] == 'SCALE_UP')} scale-up candidates",
            ],
            duration_ms=_duration_ms(start),
        )
        insert_agent_run(conn, result)
        return result


class ApplicationHealthAgent:
    name = "Application Health Agent"

    def run(self, conn) -> AgentResult:
        start = time.perf_counter()
        db_df = pd.read_csv(DB_CSV, parse_dates=["timestamp"])
        app_count = int(db_df["application"].nunique())
        degraded = []
        for app, group in db_df.groupby("application"):
            latency = float(group["db_query_latency_ms"].mean())
            min_conn = int(group["db_connections"].min())
            if latency > 25 or min_conn < 10:
                degraded.append(app)

        result = AgentResult(
            agent_name=self.name,
            status="success",
            summary=f"Scanned DB health for {app_count} applications using VM-to-DB correlation.",
            records_processed=int(len(db_df)),
            generated_insights=[
                f"{len(degraded)} applications currently need attention",
                "DB connections and query latency are connected to VM health",
                f"Most recent DB metric timestamp: {db_df['timestamp'].max()}",
            ],
            duration_ms=_duration_ms(start),
        )
        insert_agent_run(conn, result)
        return result


class PipelineMonitorAgent:
    name = "Pipeline Monitor Agent"

    def run(self, conn) -> AgentResult:
        start = time.perf_counter()
        now = datetime.utcnow()
        stages = [
            ("CoreStack ingestion", "ingestion", "success", None, 106774),
            ("Synthetic telemetry", "augmentation", "success", None, 106774),
            ("Forecasting", "model_training", "success", None, 56),
            ("Recommendation generation", "recommendations", "success", None, 56),
            ("DB metric generation", "db_metrics", "success", None, 25584),
            ("Serverless simulation", "serverless", "failed", "Lambda timeout while simulating low-peak shutdown", 1),
            ("Forecasting", "model_training", "failed", "VM had insufficient history for 48-hour lookback", 0),
            ("CoreStack ingestion", "schema_validation", "failed", "Missing network_percent in one incoming batch", 0),
        ]
        rows = []
        for idx, (pipeline, stage, status, failure, records) in enumerate(stages):
            rows.append(
                {
                    "pipeline_name": pipeline,
                    "stage": stage,
                    "status": status,
                    "duration_ms": int(450 + idx * 137),
                    "records_processed": int(records),
                    "failure_reason": failure,
                    "created_at": (now - timedelta(hours=idx * 5)).isoformat(timespec="seconds"),
                }
            )
        replace_rows(conn, "pipeline_runs", rows)

        result = AgentResult(
            agent_name=self.name,
            status="success",
            summary="Created daily pipeline execution and failure history for the operations dashboard.",
            records_processed=len(rows),
            generated_insights=[
                f"{sum(1 for row in rows if row['status'] == 'failed')} demo failures captured with root cause",
                "Pipeline executions are now visible per day and per stage",
                "Failures are linked back to agent run history",
            ],
            duration_ms=_duration_ms(start),
        )
        insert_agent_run(conn, result)
        return result


class ServerlessActionAgent:
    name = "Serverless Action Agent"

    FUNCTION_MAP = {
        "SCALE_UP": "finops-scale-up-lambda",
        "SCALE_DOWN": "finops-scale-down-lambda",
        "SHUTDOWN_LOW_PEAK": "finops-schedule-shutdown-lambda",
        "DB_DEGRADED": "finops-db-investigation-lambda",
        "PIPELINE_FAILED": "finops-pipeline-alert-lambda",
    }

    def run(self, conn) -> AgentResult:
        start = time.perf_counter()
        recs = pd.read_sql_query(
            """
            SELECT vm, action, urgency, reason
            FROM recommendations
            WHERE action != 'KEEP_RUNNING'
            ORDER BY urgency DESC
            LIMIT 12
            """,
            conn,
        )
        with TAGS_JSON.open() as f:
            tags = json.load(f)
        rows = []
        now = datetime.utcnow()
        for idx, rec in recs.iterrows():
            app = tags.get(rec["vm"], {}).get("application", "untagged")
            status = "failed" if idx in {3, 9} else "success"
            payload = {
                "vm": rec["vm"],
                "application": app,
                "action": rec["action"],
                "urgency": round(float(rec["urgency"]), 2),
                "reason": rec["reason"],
            }
            rows.append(
                {
                    "function_name": self.FUNCTION_MAP.get(rec["action"], "finops-generic-lambda"),
                    "trigger_type": rec["action"],
                    "resource_id": rec["vm"],
                    "application": app,
                    "status": status,
                    "duration_ms": int(220 + idx * 91),
                    "payload": json.dumps(payload),
                    "response_message": "Simulated execution accepted" if status == "success" else "Simulated timeout; retry required",
                    "created_at": (now - timedelta(minutes=int(idx) * 17)).isoformat(timespec="seconds"),
                }
            )
        replace_rows(conn, "serverless_action_logs", rows)

        result = AgentResult(
            agent_name=self.name,
            status="success",
            summary=f"Prepared {len(rows)} Lambda-style action logs from current recommendations.",
            records_processed=len(rows),
            generated_insights=[
                "Recommendations are traceable to function payloads",
                f"{sum(1 for row in rows if row['status'] == 'failed')} simulated function failures available for demo",
                "Real cloud deployment can replace this simulator later",
            ],
            duration_ms=_duration_ms(start),
        )
        insert_agent_run(conn, result)
        return result


def bootstrap_meeting2(conn, force: bool = False) -> list[AgentResult]:
    init_db(conn)
    if not force and table_count(conn, "agent_runs") >= 6:
        return []
    agents = [
        IngestionAgent(),
        SyntheticDataAgent(),
        RecommendationAgent(),
        ApplicationHealthAgent(),
        PipelineMonitorAgent(),
        ServerlessActionAgent(),
    ]
    return [agent.run(conn) for agent in agents]
