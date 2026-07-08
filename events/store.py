"""SQLite-backed event bus for the autonomous FinOps demo."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from agents.storage import DB_PATH, get_connection
from events.schemas import FinOpsEvent, utc_now


def init_event_store(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS event_bus (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            correlation_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            payload TEXT NOT NULL,
            result_summary TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_event_bus_status_created
            ON event_bus(status, created_at);

        CREATE INDEX IF NOT EXISTS idx_event_bus_correlation
            ON event_bus(correlation_id);

        CREATE TABLE IF NOT EXISTS coordinator_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            status TEXT NOT NULL,
            last_event_id TEXT,
            last_event_type TEXT,
            last_decision TEXT,
            events_processed INTEGER NOT NULL DEFAULT 0,
            events_failed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO coordinator_state (
            id, status, last_event_id, last_event_type, last_decision,
            events_processed, events_failed, updated_at
        ) VALUES (1, 'idle', '', '', 'Waiting for events', 0, 0, ?)
        """,
        (utc_now(),),
    )
    conn.commit()


def publish_event(
    event_type: str,
    source: str,
    payload: dict[str, Any],
    correlation_id: str | None = None,
    status: str = "pending",
) -> dict[str, Any]:
    event = FinOpsEvent(event_type=event_type, source=source, payload=payload, status=status)
    if correlation_id:
        event.correlation_id = correlation_id
    with get_connection(DB_PATH) as conn:
        init_event_store(conn)
        conn.execute(
            """
            INSERT INTO event_bus (
                event_id, correlation_id, event_type, source, status, attempts,
                payload, result_summary, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.correlation_id,
                event.event_type,
                event.source,
                event.status,
                event.attempts,
                json.dumps(event.payload),
                event.result_summary,
                event.created_at,
                event.updated_at,
            ),
        )
        conn.commit()
    return event.to_dict()


def claim_next_event() -> dict[str, Any] | None:
    with get_connection(DB_PATH) as conn:
        init_event_store(conn)
        row = conn.execute(
            """
            SELECT * FROM event_bus
            WHERE status = 'pending'
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        now = utc_now()
        conn.execute(
            """
            UPDATE event_bus
            SET status = 'processing', attempts = attempts + 1, updated_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (now, row["id"]),
        )
        conn.commit()
        claimed = conn.execute("SELECT * FROM event_bus WHERE id = ?", (row["id"],)).fetchone()
        return row_to_event(claimed)


def mark_event(event_id: str, status: str, result_summary: str) -> None:
    with get_connection(DB_PATH) as conn:
        init_event_store(conn)
        conn.execute(
            """
            UPDATE event_bus
            SET status = ?, result_summary = ?, updated_at = ?
            WHERE event_id = ?
            """,
            (status, result_summary, utc_now(), event_id),
        )
        conn.commit()


def update_coordinator_state(
    status: str,
    event: dict[str, Any] | None,
    decision: str,
    failed: bool = False,
) -> None:
    with get_connection(DB_PATH) as conn:
        init_event_store(conn)
        conn.execute(
            """
            UPDATE coordinator_state
            SET status = ?,
                last_event_id = ?,
                last_event_type = ?,
                last_decision = ?,
                events_processed = events_processed + ?,
                events_failed = events_failed + ?,
                updated_at = ?
            WHERE id = 1
            """,
            (
                status,
                event.get("event_id", "") if event else "",
                event.get("event_type", "") if event else "",
                decision,
                0 if failed else 1,
                1 if failed else 0,
                utc_now(),
            ),
        )
        conn.commit()


def get_coordinator_state() -> dict[str, Any]:
    with get_connection(DB_PATH) as conn:
        init_event_store(conn)
        row = conn.execute("SELECT * FROM coordinator_state WHERE id = 1").fetchone()
        return dict(row) if row else {}


def fetch_events(limit: int = 100) -> list[dict[str, Any]]:
    with get_connection(DB_PATH) as conn:
        init_event_store(conn)
        rows = conn.execute(
            """
            SELECT * FROM event_bus
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [row_to_event(row) for row in rows]


def event_summary() -> dict[str, Any]:
    with get_connection(DB_PATH) as conn:
        init_event_store(conn)
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM event_bus
            GROUP BY status
            """
        ).fetchall()
        by_type = conn.execute(
            """
            SELECT event_type, COUNT(*) AS count
            FROM event_bus
            GROUP BY event_type
            ORDER BY count DESC
            """
        ).fetchall()
    status_counts = {row["status"]: int(row["count"]) for row in rows}
    type_counts = {row["event_type"]: int(row["count"]) for row in by_type}
    return {
        "total_events": sum(status_counts.values()),
        "pending_events": status_counts.get("pending", 0),
        "processing_events": status_counts.get("processing", 0),
        "processed_events": status_counts.get("processed", 0),
        "failed_events": status_counts.get("failed", 0),
        "by_type": type_counts,
    }


def row_to_event(row) -> dict[str, Any]:
    data = dict(row)
    try:
        data["payload"] = json.loads(data.get("payload") or "{}")
    except json.JSONDecodeError:
        data["payload"] = {}
    return data
