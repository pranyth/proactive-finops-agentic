"""Process-level cache for the demo telemetry files.

The infrastructure analyst re-reads roughly 200k rows of CSV every time somebody
asks a question. That is fine for a batch script and far too slow for a console
where the user types a query and waits. Everything here is keyed on the file's
(mtime, size), so a regenerated dataset invalidates itself without a restart.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

import pandas as pd

_lock = threading.Lock()
_frames: dict[tuple, pd.DataFrame] = {}
_derived: dict[str, tuple[tuple, Any]] = {}


def _stamp(path: Path) -> tuple[float, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime, stat.st_size)


def load_csv(path: Path, parse_dates: list[str] | None = None) -> pd.DataFrame:
    """Read a CSV once per (file version, parse_dates) combination."""
    stamp = _stamp(path)
    if stamp is None:
        return pd.DataFrame()
    key = (str(path), stamp, tuple(parse_dates or ()))
    with _lock:
        cached = _frames.get(key)
    if cached is not None:
        return cached.copy(deep=False)

    try:
        frame = pd.read_csv(path, parse_dates=parse_dates or [])
    except ValueError:
        # A regenerated file may not carry every expected date column yet.
        frame = pd.read_csv(path)
    with _lock:
        _frames[key] = frame
    return frame.copy(deep=False)


def load_json(path: Path) -> dict[str, Any]:
    stamp = _stamp(path)
    if stamp is None:
        return {}
    key = (str(path), stamp, ("__json__",))
    with _lock:
        cached = _derived.get(key[0])
    if cached and cached[0] == key:
        return cached[1]
    with path.open() as handle:
        data = json.load(handle)
    with _lock:
        _derived[key[0]] = (key, data)
    return data


def derived(name: str, sources: list[Path], build: Callable[[], Any]) -> Any:
    """Memoize an expensive computation against the versions of its inputs.

    `build` re-runs whenever any source file changes, and never otherwise.
    """
    version = tuple(_stamp(path) for path in sources)
    with _lock:
        cached = _derived.get(name)
    if cached and cached[0] == version:
        return cached[1]
    value = build()
    with _lock:
        _derived[name] = (version, value)
    return value


def clear() -> None:
    """Drop everything. Used by the regenerate endpoint and by tests."""
    with _lock:
        _frames.clear()
        _derived.clear()
