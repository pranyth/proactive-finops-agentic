"""Reset only generated event state for a clean presentation."""

from agents.storage import get_connection
from events.schemas import utc_now
from events.store import init_event_store


def main() -> None:
    with get_connection() as conn:
        init_event_store(conn)
        conn.execute("DELETE FROM event_bus")
        conn.execute(
            """UPDATE coordinator_state
               SET status = 'idle', last_event_id = '', last_event_type = '',
                   last_decision = 'Waiting for AI usage events',
                   events_processed = 0, events_failed = 0, updated_at = ?
               WHERE id = 1""",
            (utc_now(),),
        )
        conn.commit()
    print("Generated event history reset.")


if __name__ == "__main__":
    main()

