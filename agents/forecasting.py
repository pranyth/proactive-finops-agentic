"""CPU forecasting for the infrastructure estate.

This is the model that made the project *proactive* rather than reactive. It
lived in the Streamlit dashboard (`dashboard.py`) and was left behind when the
project moved to the FastAPI console — the event bus kept publishing
`forecast.completed` with a hardcoded summary and no model behind it.

The feature engineering is a faithful port of the original: a 48-hour lookback
over CPU, network, memory and disk, plus time-of-day, rolling statistics at
48/12/6 hours, and cross-metric signals. Two things are added:

- a direct h-step-ahead model, so the console can say what happens *next*
  rather than only scoring the last hour. Predicting t+1 from real observations
  is easy and not very useful; an operator needs a day of warning.
- caching, because a single model takes about 12 seconds to fit and the console
  cannot block on that.

Training is deliberately per-machine. Fleet-wide behaviour differs so sharply by
archetype (a batch job peaks at 02:00, an interactive app at 15:00) that one
pooled model would average them into noise.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import numpy as np
import pandas as pd

from agents import datacache
from agents.analyst import VM_CSV

LOOKBACK = 48
TRAIN_SPLIT = 0.8
DEFAULT_HORIZON = 24
# 200 trees costs ~12s per machine and 120 costs ~7s for the same accuracy to
# two decimal places on this data. Override with FINOPS_FOREST_TREES.
N_ESTIMATORS = int(os.getenv("FINOPS_FOREST_TREES", "120"))

_warm_lock = threading.Lock()
_warming = False


def _load(resource_id: str) -> pd.DataFrame:
    df = datacache.load_csv(VM_CSV, parse_dates=["timestamp"])
    if df.empty:
        return df
    return df[df["resource_id"] == resource_id].sort_values("timestamp").reset_index(drop=True)


def _features(cpu, net, mem, disk, timestamps, lookback: int = LOOKBACK, horizon: int = 0):
    """Build the feature matrix.

    horizon=0 gives the original next-hour target used for backtesting.
    horizon=h labels each row with the *peak* CPU over the following h hours,
    which is the question an operator actually asks — "will this run out of room
    today" — rather than the value at one specific hour h ahead. On a diurnal
    workload the latter just lands on the same phase of the cycle and tells you
    nothing.
    """
    X, y = [], []
    limit = len(cpu) - horizon
    for i in range(lookback, limit):
        ts = pd.Timestamp(timestamps[i])
        cw, nw = cpu[i - lookback:i], net[i - lookback:i]
        mw, dw = mem[i - lookback:i], disk[i - lookback:i]

        feats = list(cw) + list(nw) + list(mw) + list(dw)
        feats += [ts.hour, ts.dayofweek, int(ts.dayofweek >= 5), ts.hour / 23.0]
        feats += [
            float(np.mean(cw)), float(np.max(cw)), float(np.std(cw)),
            float(np.mean(cw[-12:])), float(np.max(cw[-12:])), float(np.std(cw[-12:])),
            float(np.mean(cw[-6:])), float(np.max(cw[-6:])), float(np.std(cw[-6:])),
            float(cw[-1] - cw[-6]), float(cw[-1] - np.mean(cw)), float(np.percentile(cw, 90)),
        ]
        feats += [
            float(np.mean(nw)), float(np.max(nw)), float(np.mean(nw[-12:])),
            float(np.max(nw[-12:])), float(np.mean(nw[-6:])), float(np.max(nw[-6:])),
        ]
        feats += [
            float(np.mean(mw)), float(np.max(mw)), float(np.mean(mw[-12:])),
            float(np.max(mw[-12:])), float(np.mean(mw[-6:])), float(np.max(mw[-6:])),
        ]
        feats += [
            float(np.mean(dw)), float(np.max(dw)), float(np.mean(dw[-6:])), float(np.max(dw[-6:])),
        ]
        # Cross-metric: CPU not relieved by memory, CPU-per-network, memory trending up.
        feats += [
            float(cw[-1] - mw[-1] / 100.0 * cw[-1]),
            float(cw[-1] / (nw[-1] + 1e-6)),
            float(np.mean(mw[-6:]) - np.mean(mw[-48:-6])),
        ]
        X.append(feats)
        y.append(float(np.max(cpu[i + 1:i + 1 + horizon])) if horizon else cpu[i])
    return np.array(X), np.array(y)


def forecast_resource(resource_id: str, horizon: int = DEFAULT_HORIZON) -> dict[str, Any]:
    """Backtest the model on held-out data and project `horizon` hours ahead."""
    return datacache.derived(
        f"forecast::{resource_id}::{horizon}", [VM_CSV],
        lambda: _build_forecast(resource_id, horizon),
    )


def _build_forecast(resource_id: str, horizon: int) -> dict[str, Any]:
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.metrics import mean_absolute_error, mean_squared_error

    vm = _load(resource_id)
    # Two lookback windows plus the horizon, or the split leaves nothing to test.
    if vm.empty or len(vm) < LOOKBACK * 3 + horizon:
        return {}

    cpu = vm["cpu_percent"].fillna(0).to_numpy()
    net = vm["network_percent"].fillna(0).to_numpy()
    mem = vm["memory_percent"].fillna(0).to_numpy()
    disk = vm["disk_percent"].fillna(0).to_numpy()
    stamps = vm["timestamp"].to_numpy()

    split = int(len(cpu) * TRAIN_SPLIT)
    # The alert threshold is computed from training data only. Deriving it from
    # the whole series would leak the test period into the metric.
    threshold = round(float(cpu[:split].mean() + 1.5 * cpu[:split].std()), 2)

    X_train, y_train = _features(cpu[:split], net[:split], mem[:split], disk[:split], stamps[:split])
    X_test, y_test = _features(cpu[split:], net[split:], mem[split:], disk[split:], stamps[split:])
    if not len(X_train) or not len(X_test):
        return {}

    model = RandomForestRegressor(n_estimators=N_ESTIMATORS, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    y_pred = np.clip(model.predict(X_test), 0, 100)

    # Breach recall: of the hours that actually went over the threshold, how many
    # did the model call in advance. Precision matters less here — a false alarm
    # costs a look, a miss costs an outage.
    caught = int(sum(1 for p, a in zip(y_pred, y_test) if p > threshold and a > threshold))
    missed = int(sum(1 for p, a in zip(y_pred, y_test) if p <= threshold and a > threshold))
    false_alarms = int(sum(1 for p, a in zip(y_pred, y_test) if p > threshold and a <= threshold))
    recall = (caught / (caught + missed) * 100) if (caught + missed) else None

    ahead = _project_ahead(cpu, net, mem, disk, stamps, split, horizon, threshold)

    test_stamps = stamps[split + LOOKBACK:]
    return {
        "resource": resource_id,
        "model": f"RandomForestRegressor({N_ESTIMATORS} trees, {X_train.shape[1]} features)",
        "trained_on": int(len(X_train)),
        "tested_on": int(len(X_test)),
        "train_end": pd.Timestamp(stamps[split]).isoformat(),
        "threshold": threshold,
        "metrics": {
            "mae": round(float(mean_absolute_error(y_test, y_pred)), 2),
            "rmse": round(float(np.sqrt(mean_squared_error(y_test, y_pred))), 2),
            "breach_recall_pct": round(recall, 1) if recall is not None else None,
            "breaches_caught": caught,
            "breaches_missed": missed,
            "false_alarms": false_alarms,
        },
        # Trim the plotted series: the console draws a sparkline, not a poster.
        "timestamps": [pd.Timestamp(t).isoformat() for t in test_stamps[-168:]],
        "actual": [round(float(v), 2) for v in y_test[-168:]],
        "predicted": [round(float(v), 2) for v in y_pred[-168:]],
        "ahead": ahead,
    }


def _project_ahead(cpu, net, mem, disk, stamps, split, horizon: int, threshold: float) -> dict[str, Any]:
    """Predict the peak CPU over the next `horizon` hours.

    A direct model rather than feeding predictions back into itself, which
    compounds error across a 24-hour window. Validated on the same held-out
    period as the backtest, so the forward number carries an error bar instead
    of being asserted.
    """
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.metrics import mean_absolute_error

    X_train, y_train = _features(cpu[:split], net[:split], mem[:split], disk[:split],
                                 stamps[:split], horizon=horizon)
    if not len(X_train):
        return {}
    model = RandomForestRegressor(n_estimators=N_ESTIMATORS, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)

    validation: dict[str, Any] = {}
    X_test, y_test = _features(cpu[split:], net[split:], mem[split:], disk[split:],
                               stamps[split:], horizon=horizon)
    if len(X_test):
        y_hat = np.clip(model.predict(X_test), 0, 100)
        hit = int(sum(1 for p, a in zip(y_hat, y_test) if (p > threshold) == (a > threshold)))
        validation = {
            "mae": round(float(mean_absolute_error(y_test, y_hat)), 2),
            "breach_call_accuracy_pct": round(100.0 * hit / len(y_test), 1),
            "validated_on": int(len(X_test)),
        }

    # One feature row from the end of the series -> peak over the coming window.
    X_now, _ = _features(cpu[-(LOOKBACK + 1):], net[-(LOOKBACK + 1):], mem[-(LOOKBACK + 1):],
                         disk[-(LOOKBACK + 1):], stamps[-(LOOKBACK + 1):])
    if not len(X_now):
        return {}
    predicted = float(np.clip(model.predict(X_now[-1:])[0], 0, 100))
    return {
        "horizon_hours": horizon,
        "predicted_peak_cpu": round(predicted, 1),
        "threshold": threshold,
        "will_breach": bool(predicted > threshold),
        "headroom": round(100.0 - predicted, 1),
        "validation": validation,
        "from": pd.Timestamp(stamps[-1]).isoformat(),
    }


def fleet_forecast(limit: int = 10) -> dict[str, Any]:
    """Forecast the machines most likely to matter, ranked by predicted breach.

    Fitting all 56 machines takes roughly ten minutes, so this covers the
    busiest `limit` and says so rather than implying full coverage.
    """
    return datacache.derived(
        f"forecast::fleet::{limit}", [VM_CSV], lambda: _build_fleet_forecast(limit)
    )


def _build_fleet_forecast(limit: int) -> dict[str, Any]:
    df = datacache.load_csv(VM_CSV, parse_dates=["timestamp"])
    if df.empty:
        return {"forecasts": [], "covered": 0, "total": 0}

    # Two ways a machine becomes interesting, and they select different sets.
    # Busiest by p95 finds the ones near their ceiling. But a threshold of
    # mean+1.5*std is a ~6% tail by construction, and on a steadily-loaded
    # machine the 24h peak sits just under it — so ranking on p95 alone returns
    # "no breaches anywhere" and hides the spiky workloads, which is exactly
    # where a breach is actually likely.
    grouped = df.groupby("resource_id")["cpu_percent"]
    peaks = grouped.quantile(0.95).sort_values(ascending=False)
    stats = grouped.agg(["mean", "std"])
    burstiness = (stats["std"] / stats["mean"].clip(lower=0.5)).sort_values(ascending=False)
    active = stats[stats["mean"] > 1.0].index

    busiest = list(peaks.head(limit).index)
    spiky = [vm for vm in burstiness.index if vm in active and vm not in busiest][:3]
    targets = busiest + spiky

    rows = []
    for resource_id in targets:
        result = forecast_resource(resource_id)
        if not result:
            continue
        ahead = result.get("ahead") or {}
        rows.append({
            "resource": resource_id,
            "predicted_peak_cpu": ahead.get("predicted_peak_cpu"),
            "threshold": result["threshold"],
            "will_breach": ahead.get("will_breach", False),
            "horizon_hours": ahead.get("horizon_hours", DEFAULT_HORIZON),
            "mae": result["metrics"]["mae"],
            "breach_recall_pct": result["metrics"]["breach_recall_pct"],
        })

    # Least headroom first: how close the predicted peak comes to the machine's
    # own alert threshold is the actionable ordering, whether or not it crosses.
    for row in rows:
        peak = row["predicted_peak_cpu"] or 0
        row["headroom_to_threshold"] = round(row["threshold"] - peak, 1)
    rows.sort(key=lambda r: (r["will_breach"], -r["headroom_to_threshold"]), reverse=True)
    return {
        "forecasts": rows,
        "covered": len(rows),
        "total": int(df["resource_id"].nunique()),
        "selection": "busiest by peak CPU, plus the most volatile",
        "predicted_breaches": sum(1 for r in rows if r["will_breach"]),
        "tightest_headroom": min((r["headroom_to_threshold"] for r in rows), default=None),
    }


def warm_fleet_forecast(limit: int = 10) -> None:
    """Fit the fleet forecast on a background thread.

    Startup must not block for minutes, and the first person to open the
    forecast view should not pay for every model either.
    """
    global _warming
    with _warm_lock:
        if _warming:
            return
        _warming = True

    def _run() -> None:
        global _warming
        try:
            fleet_forecast(limit)
        except Exception as exc:  # noqa: BLE001 - a warm-up must never take the app down
            print(f"[forecast] warm-up skipped: {exc}")
        finally:
            with _warm_lock:
                _warming = False

    threading.Thread(target=_run, name="forecast-warmup", daemon=True).start()


def is_warming() -> bool:
    with _warm_lock:
        return _warming
