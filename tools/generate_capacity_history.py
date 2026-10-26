"""Generate 36 months of demand history for capacity forecasting.

The operational telemetry (`augmented_vm_metrics.csv`) is 90 days, which can
neither train nor validate a 3- or 6-month forecast. This writes a separate,
longer history for the same synthetic machines and archetypes, with one
change that matters: each machine follows a known growth regime (flat, linear,
compounding, a step change, decline, or quarter-end cycles). The regime is
written next to the data, so the experiments can report accuracy per regime
and a reader can see exactly what each model was asked to extrapolate.

Every regime ends at 1.0, so the final months match the level the operational
dataset shows today. Demand is expressed as a percentage of the machine's
current capacity and is not clipped at 100: forecasting demand that exceeds
capacity is the point.

The two real CoreStack machines are excluded. Their history cannot be
invented.

    python tools/generate_capacity_history.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from generate_fleet_telemetry import ARCHETYPES, REAL_VMS, assign_archetypes, ou_noise, stable_rng

SOURCE = Path("data/augmented_vm_metrics.csv")
OUTPUT = Path("data/capacity_history.csv")
DAYS = 1095  # 12-month forecasts need a year to learn, a year to forecast, a year to check

REGIMES_BY_ARCHETYPE = {
    "zombie": ["flat"],
    "oversized": ["flat", "decline", "linear"],
    "dev_workstation": ["flat", "step"],
    "ci_runner": ["step", "linear"],
    "batch_nightly": ["linear", "quarterly"],
    "interactive_web": ["linear", "exponential", "quarterly"],
    "api_backend": ["linear", "exponential", "step"],
    "database": ["linear", "exponential"],
    "memory_bound": ["flat", "linear"],
    "saturated": ["exponential", "linear"],
}


def growth_curve(regime: str, u: np.ndarray, dates: pd.DatetimeIndex, rng: np.random.Generator) -> np.ndarray:
    """Multiplier over the window, u running 0 -> 1, always ending at 1.0."""
    if regime == "linear":
        start = rng.uniform(0.40, 0.70)
        return start + (1 - start) * u
    if regime == "exponential":
        return rng.uniform(0.35, 0.60) ** (1 - u)
    if regime == "step":
        # A launch or migration: one level before, one after, a two-week ramp.
        before, at = rng.uniform(0.50, 0.70), rng.uniform(0.30, 0.80)
        ramp = 1 / (1 + np.exp(-(u - at) * len(u) / (14 * 24) * 6))
        return before + (1 - before) * ramp
    if regime == "decline":
        start = rng.uniform(1.40, 1.90)
        return start + (1 - start) * u
    if regime == "quarterly":
        base = rng.uniform(0.75, 0.90) + (1 - rng.uniform(0.75, 0.90)) * u
        quarter_end = np.asarray(dates.month.isin([3, 6, 9, 12]) & (dates.day >= 15))
        return base * np.where(quarter_end, 1 + rng.uniform(0.15, 0.30), 1.0)
    return np.ones_like(u)


def build_history(vm: str, archetype: str, regime: str, timeline: pd.DatetimeIndex) -> pd.DataFrame:
    cfg = ARCHETYPES[archetype]
    rng = stable_rng(f"capacity-{vm}")
    n = len(timeline)
    u = np.linspace(0.0, 1.0, n)

    ceiling = rng.uniform(*cfg["cpu"])
    shape = np.asarray(cfg["shape"], dtype=float)[timeline.hour]
    weekend = np.where(timeline.weekday >= 5, cfg["weekend"], 1.0)
    annual = 1 + (0 if archetype == "zombie" else rng.uniform(0, 0.08)) * np.sin(
        2 * np.pi * (timeline.dayofyear.to_numpy() - rng.uniform(0, 365)) / 365.25)

    growth = growth_curve(regime, u, timeline, rng)
    demand = ceiling * shape * weekend * annual * growth
    demand = demand * (1 + ou_noise(n, cfg["noise"] * 0.30, rng))
    if cfg["burst"] > 0:
        for _ in range(int(rng.integers(40, 160))):
            start, length = int(rng.integers(0, n - 8)), int(rng.integers(2, 9))
            size = ceiling * cfg["burst"] * rng.uniform(0.5, 1.5) * growth[start]
            demand[start:start + length] += size * np.hanning(length + 2)[1:length + 1]
    demand = np.clip(demand, 0.05, None)

    hourly = pd.Series(demand, index=timeline)
    daily = hourly.groupby(hourly.index.normalize()).agg(["max", "mean"])
    return pd.DataFrame({
        "date": daily.index,
        "resource_id": vm,
        "archetype": archetype,
        "regime": regime,
        "peak_demand_pct": daily["max"].round(3).to_numpy(),
        "mean_demand_pct": daily["mean"].round(3).to_numpy(),
    })


def main() -> None:
    existing = pd.read_csv(SOURCE, usecols=["timestamp", "resource_id"], parse_dates=["timestamp"])
    names = sorted(set(existing["resource_id"]) - REAL_VMS)
    end = pd.Timestamp(existing["timestamp"].max()).normalize() + pd.Timedelta(hours=23)
    timeline = pd.date_range(end=end, periods=DAYS * 24, freq="h")

    assignment = assign_archetypes(names)
    frames = []
    for vm in names:
        options = REGIMES_BY_ARCHETYPE[assignment[vm]]
        regime = options[int(stable_rng(f"regime-{vm}").integers(0, len(options)))]
        frames.append(build_history(vm, assignment[vm], regime, timeline))

    out = pd.concat(frames, ignore_index=True)
    out.to_csv(OUTPUT, index=False)
    print(f"wrote {len(out):,} rows ({len(names)} machines x {DAYS} days) to {OUTPUT}")
    print(out.groupby("regime")["resource_id"].nunique().to_string())


if __name__ == "__main__":
    main()
