"""Rolling-origin backtest of every capacity model at every horizon.

At each origin, each model is trained only on data up to that day and asked
for the weekly peak 7, 30, 91 and 182 days ahead. Origins step forward through
the test period, so every forecast is scored against a future the model never
saw. Writes one row per (series, horizon, origin) to results/forecasts_<dataset>.csv;
`analyze.py` turns that into tables and figures.

    python research/run_experiments.py            # both datasets, ~30 min on 10 cores
    python research/run_experiments.py --dataset synthetic
    python research/run_experiments.py --quick    # 6 series per dataset, smoke test
"""

from __future__ import annotations

import os

# One thread per worker: the pool already uses every core.
os.environ.setdefault("OMP_NUM_THREADS", "1")

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.capacity import ALL_MODELS, HORIZONS, Series, forecast  # noqa: E402

RESULTS = Path("research/results")
SYNTHETIC = Path("data/capacity_history.csv")
WIKIMEDIA = Path("data/research/wikimedia_daily.csv")
# Wikimedia series are request counts. Each is expressed as a percentage of a
# capacity sized so the busiest hour of its first year ran at 60%, a common
# provisioning target, which puts it on the same scale as the VM fleet.
WIKI_FIRST_YEAR_UTILISATION = 60.0

# (first origin in days, step in days). One year of training before the first
# synthetic forecast; two for Wikimedia, whose series are 10 years long.
SCHEDULE = {"synthetic": (365, 14), "wikimedia": (730, 28)}


def load_datasets() -> dict[str, dict[str, tuple[pd.DataFrame, str]]]:
    out: dict[str, dict[str, tuple[pd.DataFrame, str]]] = {"synthetic": {}, "wikimedia": {}}
    synthetic = pd.read_csv(SYNTHETIC, parse_dates=["date"])
    for name, rows in synthetic.groupby("resource_id"):
        out["synthetic"][name] = (rows.sort_values("date")[["date", "peak_demand_pct"]]
                                  .rename(columns={"peak_demand_pct": "demand"}), rows["regime"].iloc[0])
    if WIKIMEDIA.exists():
        wiki = pd.read_csv(WIKIMEDIA, parse_dates=["date"])
        for name, rows in wiki.groupby("series"):
            rows = rows.sort_values("date")
            capacity = rows["peak_hourly_views"].iloc[:365].max() / WIKI_FIRST_YEAR_UTILISATION * 100
            demand = rows["peak_hourly_views"] / capacity * 100
            out["wikimedia"][name] = (pd.DataFrame({"date": rows["date"], "demand": demand}), "real")
    return out


_SERIES: dict[tuple[str, str], tuple[Series, pd.DataFrame, str]] = {}


def _get(dataset: str, name: str) -> tuple[Series, pd.DataFrame, str]:
    key = (dataset, name)
    if key not in _SERIES:
        frame, regime = load_datasets()[dataset][name]
        _SERIES[key] = (Series(frame["demand"].to_numpy(), frame["date"].iloc[0]), frame, regime)
    return _SERIES[key]


def run_task(task: tuple) -> list[dict]:
    dataset, name, h, origins, models = task
    s, frame, regime = _get(dataset, name)
    rows = []
    for origin in origins:
        predictions = forecast(s, origin, h, models)
        if not predictions:
            continue
        rows.append({
            "dataset": dataset, "series": name, "regime": regime, "horizon": h, "origin": origin,
            "origin_date": frame["date"].iloc[origin].date().isoformat(),
            "actual": float(s.wk[origin + h]),
            "history_max": float(pd.Series(s.wk[:origin + 1]).max()),
            **predictions,
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--dataset", choices=sorted(SCHEDULE), action="append")
    parser.add_argument("--step", type=int, help="days between origins (default per dataset)")
    parser.add_argument("--models", help="comma-separated subset, e.g. the console's rf,linear,hybrid_q90")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = parser.parse_args()

    models = tuple(args.models.split(",")) if args.models else ALL_MODELS
    datasets = {k: v for k, v in load_datasets().items() if v and (not args.dataset or k in args.dataset)}
    tasks = []
    for dataset, series in datasets.items():
        first, step = SCHEDULE[dataset]
        step = args.step or step
        names = sorted(series)[:6] if args.quick else sorted(series)
        for name in names:
            n = len(series[name][0])
            for h in HORIZONS.values():
                origins = list(range(first, n - h, step))
                # Chunk so the pool stays busy when a dataset has few, long series.
                for i in range(0, len(origins), 8):
                    tasks.append((dataset, name, h, origins[i:i + 8], models))
    print(f"{len(tasks)} tasks over {sum(len(v) for v in datasets.values())} series, {args.workers} workers")

    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, chunk in enumerate(pool.map(run_task, tasks, chunksize=1), 1):
            rows.extend(chunk)
            if i % 50 == 0 or i == len(tasks):
                print(f"  {i}/{len(tasks)} tasks, {len(rows)} forecasts", flush=True)

    RESULTS.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    for dataset, part in frame.groupby("dataset"):
        out = RESULTS / f"forecasts_{dataset}{'_quick' if args.quick else ''}.csv"
        part.to_csv(out, index=False)
        print(f"wrote {len(part):,} rows to {out}")


if __name__ == "__main__":
    main()
