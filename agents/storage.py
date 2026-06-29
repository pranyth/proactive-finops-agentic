"""SQLite storage for the agentic FinOps demo."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

DB_PATH = Path("data/agentic_finops.db")


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS agent_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name TEXT NOT NULL,
            status TEXT NOT NULL,
            summary TEXT NOT NULL,
            records_processed INTEGER NOT NULL DEFAULT 0,
            generated_insights TEXT NOT NULL DEFAULT '[]',
            duration_ms INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS vm_metric_summary (
            resource_id TEXT PRIMARY KEY,
            workload_class TEXT,
            records INTEGER NOT NULL,
            mean_cpu REAL NOT NULL,
            max_cpu REAL NOT NULL,
            mean_network REAL NOT NULL,
            mean_memory REAL NOT NULL,
            mean_disk REAL NOT NULL,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS data_storage_summary (
            dataset TEXT PRIMARY KEY,
            rows_count INTEGER NOT NULL,
            entity_count INTEGER NOT NULL,
            first_seen TEXT,
            last_seen TEXT,
            source_path TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vm TEXT NOT NULL,
            action TEXT NOT NULL,
            urgency REAL NOT NULL,
            reason TEXT NOT NULL,
            avg_cpu_48h REAL NOT NULL,
            max_cpu_48h REAL NOT NULL,
            threshold REAL NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_name TEXT NOT NULL,
            stage TEXT NOT NULL,
            status TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            records_processed INTEGER NOT NULL DEFAULT 0,
            failure_reason TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS serverless_action_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            function_name TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            resource_id TEXT,
            application TEXT,
            status TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            payload TEXT NOT NULL,
            response_message TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()


def table_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def insert_agent_run(conn: sqlite3.Connection, result) -> None:
    conn.execute(
        """
        INSERT INTO agent_runs (
            agent_name, status, summary, records_processed,
            generated_insights, duration_ms, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result.agent_name,
            result.status,
            result.summary,
            result.records_processed,
            json.dumps(result.generated_insights),
            result.duration_ms,
            result.created_at,
        ),
    )
    conn.commit()


def replace_rows(conn: sqlite3.Connection, table: str, rows: Iterable[dict]) -> None:
    rows = list(rows)
    conn.execute(f"DELETE FROM {table}")
    if not rows:
        conn.commit()
        return
    columns = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in columns)
    query = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    conn.executemany(query, [[row[col] for col in columns] for row in rows])
    conn.commit()


def fetch_df(query: str):
    import pandas as pd

    with get_connection() as conn:
        init_db(conn)
        return pd.read_sql_query(query, conn)
