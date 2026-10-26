"""Multi-horizon capacity forecasting: 1 week, 1 month, 3 months, 6 months.

`agents/forecasting.py` answers "will this machine breach in the next 24
hours" with a Random Forest over absolute CPU levels. That model cannot answer
a planning question. A tree predicts by averaging training targets, so it can
never forecast a level it has not already seen, and a growing workload is by
definition heading somewhere it has not been.

This module separates the two jobs. A linear trend, refitted on the past year
at every forecast origin, carries the level forward. A tree model learns only
the residual shape around that trend. The quantile variant forecasts the 90th
percentile instead of the mean, because under-provisioning costs an outage
while over-provisioning only costs money.

Everything works on one daily-peak series per machine. The forecast target is
the peak of the 7-day window ending h days after the origin: "how much
capacity will that week need".
"""

from __future__ import annotations

import functools
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from threadpoolctl import threadpool_limits

from agents import datacache

CAPACITY_CSV = Path("data/capacity_history.csv")
COST_CSV = Path("data/cost_metrics.csv")
INVENTORY_CSV = Path("data/vm_inventory.csv")
# The rolling-origin backtest (research/run_experiments.py). The console shows
# it as proof: what each model said six months before, against what happened.
BACKTEST_CSV = Path("research/results/forecasts_synthetic.csv")
BACKTEST_MODELS = ("rf", "linear", "hybrid_q90")
CALIBRATION_QUANTILE = 0.9

HORIZONS = {"1 week": 7, "1 month": 30, "3 months": 91, "6 months": 182}
TREND_WINDOW = 365
MIN_HISTORY = 91
MIN_TRAIN = 30
BREACH_PCT = 80.0
# 1-year compute savings plans list at roughly 30% off on-demand across the
# three major clouds. Applied only to the capacity the forecast floor covers.
COMMITMENT_DISCOUNT = 0.30
POINT_MODELS = ("persistence", "linear", "rf", "hybrid")
ALL_MODELS = POINT_MODELS + ("hybrid_oob90", "hybrid_q90")
WEEK_LAGS = np.array([0, 7, 14, 21, 28])


class Series:
    """One machine's daily peaks, with everything derived from them precomputed."""

    def __init__(self, daily: np.ndarray, start: pd.Timestamp) -> None:
        self.daily = np.asarray(daily, dtype=float)
        n = len(self.daily)
        self.wk = pd.Series(self.daily).rolling(7, min_periods=7).max().to_numpy()
        self.windows = sliding_window_view(self.daily, MIN_HISTORY)
        calendar = pd.date_range(start, periods=n + max(HORIZONS.values()) + 1, freq="D")
        self.dow = calendar.dayofweek.to_numpy()
        self.season = 2 * np.pi * calendar.dayofyear.to_numpy() / 365.25
        self.slope, self.intercept = _rolling_trend(self.wk)

    def __len__(self) -> int:
        return len(self.daily)

    def trend_at(self, origin, target):
        return self.slope[origin] * target + self.intercept[origin]


def _rolling_trend(wk: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """OLS of weekly peak on time, fitted at every origin on the trailing year.

    Each origin only sees its own past, so the trend used at any origin is the
    trend that would have been available on that day. Closed form over prefix
    sums: 730 np.polyfit calls per machine spent most of their time spinning
    up BLAS threads for a 2-parameter fit.
    """
    n = len(wk)
    slope, intercept = np.full(n, np.nan), np.full(n, np.nan)
    x = np.arange(n, dtype=float)
    y = np.nan_to_num(wk)
    prefix = [np.concatenate(([0.0], np.cumsum(v))) for v in (np.ones(n), x, y, x * x, x * y)]
    t = np.arange(6 + 27, n)
    lo = np.maximum(6, t - TREND_WINDOW + 1)
    count, sx, sy, sxx, sxy = (p[t + 1] - p[lo] for p in prefix)
    slope[t] = (count * sxy - sx * sy) / (count * sxx - sx * sx)
    intercept[t] = (sy - slope[t] * sx) / count
    return slope, intercept


def features(s: Series, origins: np.ndarray, h: int, trend_origin: int | None = None) -> np.ndarray:
    """Feature rows for forecasting the week ending h days after each origin.

    With `trend_origin`, every level is expressed relative to the one trend
    fitted at that origin, so the model learns shape, not level, and the trend
    supplies the level it could never extrapolate on its own.
    """
    t = np.asarray(origins)
    level = s.trend_at(trend_origin, t)[:, None] if trend_origin is not None else np.zeros((len(t), 1))
    window = s.windows[t - (MIN_HISTORY - 1)] - level
    cols = [window[:, -28:], s.wk[t[:, None] - WEEK_LAGS] - level]
    for k in (7, 28, 91):
        cols += [window[:, -k:].mean(1, keepdims=True), window[:, -k:].max(1, keepdims=True),
                 window[:, -k:].std(1, keepdims=True)]
    cols += [s.dow[t][:, None], np.sin(s.season[t + h])[:, None], np.cos(s.season[t + h])[:, None]]
    return np.hstack(cols)


def training_set(s: Series, origin: int, h: int) -> np.ndarray:
    """Training origins whose target week ends on or before the forecast origin."""
    return np.arange(MIN_HISTORY - 1, origin - h + 1)


def _forest():
    from sklearn.ensemble import RandomForestRegressor
    return RandomForestRegressor(n_estimators=120, oob_score=True, random_state=42, n_jobs=1)


def _quantile(q: float):
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=200, learning_rate=0.05,
                                         max_leaf_nodes=15, min_samples_leaf=10, random_state=42)


def _single_thread(fn):
    """On a few hundred rows, OpenMP threads cost more than they save and fight
    every other model fitting in the process."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with threadpool_limits(limits=1):
            return fn(*args, **kwargs)
    return wrapper


def _detrended(s: Series, train: np.ndarray, origin: int, h: int):
    """Training rows, the forecast row, and residual targets, all against the
    single trend fitted at `origin`.

    Detrending each training row by the trend of its own day was tried first
    and fails: early rows carry trends fitted on a few weeks of data, the model
    learns to correct their extrapolation errors, and applies those
    corrections to a trend that does not make them (research/results/ablation).
    """
    residual = s.wk[train + h] - s.trend_at(origin, train + h)
    return features(s, train, h, origin), features(s, np.array([origin]), h, origin), residual


@_single_thread
def forecast(s: Series, origin: int, h: int, models=ALL_MODELS) -> dict[str, float]:
    """Every model's forecast of the weekly peak h days after `origin`.

    Only data up to and including `origin` is used. Returns {} when there is
    not enough history to train on.
    """
    train = training_set(s, origin, h)
    if len(train) < MIN_TRAIN:
        return {}
    now = np.array([origin])
    trend_now = float(s.trend_at(origin, origin + h))
    y = s.wk[train + h]
    out: dict[str, float] = {}

    if "persistence" in models:
        out["persistence"] = float(s.wk[origin])
    if "linear" in models:
        out["linear"] = trend_now
    if "rf" in models:
        out["rf"] = float(_forest().fit(features(s, train, h), y).predict(features(s, now, h))[0])

    if any(m.startswith("hybrid") for m in models):
        X, X_now, residual = _detrended(s, train, origin, h)
        if {"hybrid", "hybrid_oob90"} & set(models):
            forest = _forest().fit(X, residual)
            point = trend_now + float(forest.predict(X_now)[0])
            out["hybrid"] = point
            # Out-of-bag errors stand in for unseen-data errors: the usual
            # "point forecast plus an empirical safety margin" practice.
            out["hybrid_oob90"] = point + float(np.quantile(residual - forest.oob_prediction_, 0.9))
        if "hybrid_q90" in models:
            out["hybrid_q90"] = trend_now + float(_quantile(0.9).fit(X, residual).predict(X_now)[0])
    return {name: max(0.0, value) for name, value in out.items() if name in models}


@_single_thread
def quantile_band(s: Series, origin: int, h: int, quantiles=(0.1, 0.5, 0.9)) -> dict[float, float]:
    """Trend plus quantile-boosted residuals: the band the console plots."""
    train = training_set(s, origin, h)
    if len(train) < MIN_TRAIN:
        return {}
    X, X_now, residual = _detrended(s, train, origin, h)
    trend_now = float(s.trend_at(origin, origin + h))
    band = {q: max(0.0, trend_now + float(_quantile(q).fit(X, residual).predict(X_now)[0])) for q in quantiles}
    # Independently fitted quantiles can cross; sorting restores a valid band.
    return dict(zip(quantiles, sorted(band.values())))


# ── console ──────────────────────────────────────────────────────────────

_warm_lock = threading.Lock()
_warming = False


def _history() -> pd.DataFrame:
    return datacache.load_csv(CAPACITY_CSV, parse_dates=["date"])


def _series(resource_id: str) -> tuple[Series, pd.DataFrame] | None:
    df = _history()
    if df.empty:
        return None
    rows = df[df["resource_id"] == resource_id].sort_values("date")
    if len(rows) < MIN_HISTORY + max(HORIZONS.values()) + MIN_TRAIN:
        return None
    return Series(rows["peak_demand_pct"].to_numpy(), rows["date"].iloc[0]), rows


def _monthly_cost(resource_id: str) -> float:
    cost = datacache.load_csv(COST_CSV, parse_dates=["date"])
    rows = cost[cost["resource_id"] == resource_id]
    return float(rows.sort_values("date")["estimated_monthly_cost"].iloc[-1]) if len(rows) else 0.0


def inventory() -> dict[str, dict[str, Any]]:
    df = datacache.load_csv(INVENTORY_CSV)
    return {} if df.empty else df.fillna("").set_index("resource_id").to_dict("index")


def capacity_plan(resource_id: str, full: bool = True) -> dict[str, Any]:
    """Four horizons for one machine, each turned into the decision it feeds.

    `full=False` fits only the quantiles the decisions read (p90 everywhere, plus
    the 6-month p10): 5 models instead of 12, which is what the fleet table needs.
    """
    return datacache.derived(f"capacity::{resource_id}::{full}", [CAPACITY_CSV, COST_CSV, BACKTEST_CSV],
                             lambda: _build_plan(resource_id, full))


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _build_plan(resource_id: str, full: bool = True) -> dict[str, Any]:
    loaded = _series(resource_id)
    if loaded is None:
        return {}
    s, rows = loaded
    origin = len(s) - 1
    last_date = rows["date"].iloc[-1]
    margins = {h: c["margin"] for h, c in calibration().items()}
    horizons = []
    for label, h in HORIZONS.items():
        quantiles = (0.1, 0.5, 0.9) if full else (0.1, 0.9) if label == "6 months" else (0.9,)
        band = quantile_band(s, origin, h, quantiles)
        if band:
            horizons.append({
                "label": label, "days": h,
                "date": (last_date + pd.Timedelta(days=h)).date().isoformat(),
                "p10": _round(band.get(0.1)), "p50": _round(band.get(0.5)),
                "p90": round(band[0.9] + margins.get(h, 0.0), 1), "p90_model": round(band[0.9], 1),
                "breach": band[0.9] + margins.get(h, 0.0) >= BREACH_PCT,
            })
    monthly_cost = _monthly_cost(resource_id)
    current_peak = round(float(s.wk[origin]), 1)
    history = rows.tail(182)
    plan = {
        "resource": resource_id,
        "archetype": rows["archetype"].iloc[0],
        "regime": rows["regime"].iloc[0],
        "as_of": last_date.date().isoformat(),
        "current_peak": current_peak,
        "over_now": current_peak >= BREACH_PCT,
        "trend_per_month": round(float(s.slope[origin]) * 30, 2),
        "days_to_breach": _days_to_breach(s, origin),
        "breach_threshold": BREACH_PCT,
        "monthly_cost_usd": round(monthly_cost, 2),
        "horizons": horizons,
        "decisions": _decisions(horizons, monthly_cost, current_peak),
        "history": {
            "dates": [d.date().isoformat() for d in history["date"]],
            "weekly_peak": [round(float(v), 1) for v in s.wk[-len(history):]],
        },
    }
    if full:
        plan["backtest"] = _backtest(resource_id)
    return plan


def calibration() -> dict[int, dict[str, float]]:
    """How much to widen the model's p90 so it covers ~90% of real outcomes.

    The quantile model's p90 covered only 66-73% of backtest outcomes. The
    margin is the 90th percentile of (actual - p90) across the whole fleet's
    backtest per horizon (split-conformal). Pooled beats per-machine: tested
    on forecasts calibrated only with errors known at the time, pooled landed
    at 88-92% coverage, per-machine at 81-90% (research/analyze.py).
    """
    return datacache.derived("capacity::calibration", [BACKTEST_CSV], _build_calibration)


def _build_calibration() -> dict[int, dict[str, float]]:
    df = datacache.load_csv(BACKTEST_CSV)
    if df.empty:
        return {}
    out = {}
    for h, rows in df.groupby("horizon"):
        errors = rows["actual"] - rows["hybrid_q90"]
        out[int(h)] = {
            "margin": round(max(0.0, float(np.quantile(errors, CALIBRATION_QUANTILE))), 2),
            "model_coverage_pct": round(float((errors <= 0).mean() * 100), 1),
            "forecasts": int(len(rows)),
        }
    return out


def _backtest(resource_id: str, horizon: int = HORIZONS["6 months"]) -> dict[str, Any]:
    df = datacache.load_csv(BACKTEST_CSV)
    if df.empty:
        return {}
    rows = df[(df["series"] == resource_id) & (df["horizon"] == horizon)].sort_values("origin")
    if rows.empty:
        return {}
    targets = pd.to_datetime(rows["origin_date"]) + pd.Timedelta(days=horizon)
    return {
        "horizon_days": horizon,
        "dates": [d.date().isoformat() for d in targets],
        "actual": [round(float(v), 1) for v in rows["actual"]],
        "models": {m: [round(float(v), 1) for v in rows[m]] for m in BACKTEST_MODELS},
        "mae": {m: round(float((rows[m] - rows["actual"]).abs().mean()), 2) for m in BACKTEST_MODELS},
        "beyond_history": int((rows["actual"] > rows["history_max"]).sum()),
    }


def _days_to_breach(s: Series, origin: int) -> int | None:
    """Where the trend line crosses the threshold, if it is heading there."""
    slope, intercept = s.slope[origin], s.intercept[origin]
    if slope <= 0:
        return None
    crossing = (BREACH_PCT - intercept) / slope - origin
    return max(0, int(round(crossing))) if crossing < 3 * 365 else None


def _decisions(horizons: list[dict[str, Any]], monthly_cost: float,
               current_peak: float = 0.0) -> list[dict[str, Any]]:
    """Each horizon answers a different question, so each reads a different number.

    Short horizons protect against outages and read the p90. The commitment
    decision reads the p10: you only commit to capacity you are nearly sure
    to use, and the floor is what makes that safe.
    """
    by = {row["label"]: row for row in horizons}
    out = []
    # Already over the line is a present-tense problem, not a forecast; say so
    # rather than dressing it up as a prediction.
    if current_peak >= BREACH_PCT:
        out.append({"horizon": "now", "action": "SCALE_UP", "savings_usd": 0.0,
                    "reason": f"Already peaking at {current_peak}% of capacity, over the "
                              f"{BREACH_PCT:.0f}% threshold today. Scale up now."})
    for label, action, verb in ([] if out else (("1 week", "SCALE_UP", "Scale up now"),
                                ("1 month", "PLAN_SCALE_UP", "Schedule a capacity increase this month"),
                                ("3 months", "PLAN_SCALE_UP", "Plan a resize or migration this quarter"),
                                ("6 months", "PLAN_SCALE_UP", "Budget for more capacity within six months"))):
        row = by.get(label)
        if row and row["breach"]:
            out.append({"horizon": label, "action": action, "savings_usd": 0.0,
                        "reason": f"{verb}: p90 demand {row['p90']}% passes the {BREACH_PCT:.0f}% threshold "
                                  f"by {row['date']}."})
            break
    floor = by.get("6 months")
    if floor and monthly_cost:
        if floor["p10"] >= 40:
            covered = min(floor["p10"], 100.0) / 100.0
            out.append({"horizon": "6 months", "action": "COMMIT_CAPACITY",
                        "savings_usd": round(monthly_cost * covered * COMMITMENT_DISCOUNT, 2),
                        "reason": f"Demand floor holds at {floor['p10']}% for six months, so a 1-year savings "
                                  f"plan on that share of the machine is safe."})
        elif floor["p90"] < 25:
            out.append({"horizon": "6 months", "action": "AVOID_COMMITMENT", "savings_usd": 0.0,
                        "reason": f"Six-month demand stays under {floor['p90']}% even at p90; do not commit "
                                  f"capacity to it — rightsize instead."})
    return out


def fleet_capacity() -> dict[str, Any]:
    """Every machine's plan, tightest first."""
    return datacache.derived("capacity::fleet", [CAPACITY_CSV, COST_CSV, BACKTEST_CSV], _build_fleet)


def _build_fleet() -> dict[str, Any]:
    df = _history()
    if df.empty:
        return {"machines": [], "covered": 0}
    ids = sorted(df["resource_id"].unique())
    plans = [capacity_plan(resource_id, full=False) for resource_id in ids]
    rows = []
    for resource_id, plan in zip(ids, plans):
        if not plan:
            continue
        p90 = {row["label"]: row["p90"] for row in plan["horizons"]}
        first_breach = "now" if plan["over_now"] else next(
            (row["label"] for row in plan["horizons"] if row["breach"]), None)
        rows.append({
            "resource": resource_id, "regime": plan["regime"], "current_peak": plan["current_peak"],
            "trend_per_month": plan["trend_per_month"], "days_to_breach": plan["days_to_breach"],
            "p90": p90, "first_breach": first_breach, "monthly_cost_usd": plan["monthly_cost_usd"],
            "commitment_savings_usd": sum(d["savings_usd"] for d in plan["decisions"]),
            "decisions": plan["decisions"],
        })
    order = {label: i for i, label in enumerate(["now", *HORIZONS])}
    rows.sort(key=lambda r: (order.get(r["first_breach"], 99), -max(r["p90"].values(), default=0)))
    return {
        "machines": rows,
        "covered": len(rows),
        "horizons": list(HORIZONS),
        "breaching": {label: sum(1 for r in rows if r["first_breach"] == label) for label in ["now", *HORIZONS]},
        "commitment_savings_usd": round(sum(r["commitment_savings_usd"] for r in rows), 2),
        "model": "linear trend (trailing year) + quantile gradient boosting on residuals; p90 widened by a "
                 "fleet-wide conformal margin per horizon",
        "calibration": {label: calibration().get(h) for label, h in HORIZONS.items()},
    }


def warm_fleet_capacity() -> None:
    """Fit the fleet plan on a background thread so startup never blocks on it."""
    global _warming
    with _warm_lock:
        if _warming:
            return
        _warming = True

    def _run() -> None:
        global _warming
        try:
            fleet_capacity()
        except Exception as exc:  # noqa: BLE001 - a warm-up must never take the app down
            print(f"[capacity] warm-up skipped: {exc}")
        finally:
            with _warm_lock:
                _warming = False

    threading.Thread(target=_run, name="capacity-warmup", daemon=True).start()


def is_warming() -> bool:
    with _warm_lock:
        return _warming
