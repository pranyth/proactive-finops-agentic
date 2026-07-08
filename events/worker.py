"""Background worker that lets the coordinator consume events continuously."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from agents.coordinator import CoordinatorAgent
from events.store import claim_next_event, mark_event, update_coordinator_state


class EventWorker:
    """Small in-process worker for the demo; replace with Celery/Redis later."""

    def __init__(self, interval_seconds: float = 2.0) -> None:
        self.interval_seconds = interval_seconds
        self.coordinator = CoordinatorAgent()
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        while self._running:
            self.process_once()
            await asyncio.sleep(self.interval_seconds)

    def process_once(self) -> dict | None:
        event = claim_next_event()
        if event is None:
            return None
        try:
            decision = self.coordinator.handle_event(event)
            mark_event(event["event_id"], "processed", decision["summary"])
            update_coordinator_state("processed", event, decision["summary"])
            return decision
        except Exception as exc:  # pragma: no cover - defensive for demo runtime
            summary = f"Coordinator failed while processing {event['event_type']}: {exc}"
            mark_event(event["event_id"], "failed", summary)
            update_coordinator_state("failed", event, summary, failed=True)
            return {"status": "failed", "summary": summary}

    def process_pending(self, limit: int = 10) -> list[dict]:
        decisions = []
        for _ in range(limit):
            decision = self.process_once()
            if decision is None:
                break
            decisions.append(decision)
        return decisions
