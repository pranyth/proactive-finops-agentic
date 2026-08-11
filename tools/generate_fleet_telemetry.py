"""Generate production-shaped VM telemetry for the FinOps demo.

The previous synthetic generator derived one hourly profile from a single real
PowerBI VM and applied it to every machine, with a day-of-week curve flat to
within 5% and a CPU ceiling of 10%. The result was a fleet where every machine
moved in lockstep, nothing ever looked busy, and four of the console's six CPU
bands were permanently empty.

Real estates are not flat. They contain a handful of genuinely hot machines, a
long tail of over-provisioned ones, a few zombies nobody turned off, and
workloads whose shapes differ from each other: an interactive app peaks during
office hours, a batch job runs at 2am, a CI fleet is idle all weekend.

This generator models that with explicit archetypes. Every row it writes is
labelled `augmented=True`; the real CoreStack machines are copied through
untouched with `augmented=False`, so the provenance rules in
docs/DATA_STRATEGY.md still hold.

    python tools/generate_fleet_telemetry.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path("data")
SOURCE = DATA_DIR / "augmented_vm_metrics.csv"
OUTPUT = DATA_DIR / "augmented_vm_metrics.csv"

SEED = 42
WINDOW_HOURS = 90 * 24
# The two machines whose telemetry came from CoreStack. Never regenerated.
REAL_VMS = {"cspbi-prod-ir-Europe", "cs-prod-ir-vm-india"}

# Hour-of-day multipliers, 00:00 -> 23:00. These are the shapes that were
# missing: an office-hours curve, a nightly batch window, and a flat line.
OFFICE_HOURS = [
    0.18, 0.15, 0.13, 0.12, 0.13, 0.18, 0.32, 0.58,
    0.85, 1.00, 1.05, 1.02, 0.88, 0.95, 1.08, 1.10,
    0.98, 0.80, 0.55, 0.40, 0.32, 0.28, 0.24, 0.20,
]
NIGHTLY_BATCH = [
    0.30, 1.00, 1.10, 1.05, 0.75, 0.20, 0.06, 0.05,
    0.05, 0.06, 0.06, 0.05, 0.06, 0.06, 0.05, 0.06,
    0.05, 0.06, 0.06, 0.08, 0.10, 0.14, 0.20, 0.26,
]
ALWAYS_ON = [0.92, 0.90, 0.88, 0.87, 0.88, 0.90, 0.95, 1.00,
             1.05, 1.08, 1.10, 1.08, 1.02, 1.06, 1.10, 1.09,
             1.04, 0.99, 0.96, 0.95, 0.94, 0.94, 0.93, 0.92]
FLAT = [1.0] * 24

# archetype -> behaviour. `workload_class` stays inside the four values the
# analyst reasons about; the archetype drives the numbers underneath it.
ARCHETYPES = {
    "zombie": dict(
        workload_class="truly_idle", shape=FLAT, weekend=1.0,
        cpu=(0.3, 1.4), burst=0.0, mem=(12, 26), disk=(8, 22), disk_growth=0.000,
        net=(1.5, 6.0), trend=0.0, noise=0.12,
        note="Forgotten machine. No traffic, no owner, still billed.",
    ),
    "oversized": dict(
        workload_class="low_variable", shape=OFFICE_HOURS, weekend=0.45,
        cpu=(5.0, 14.0), burst=0.25, mem=(28, 45), disk=(25, 48), disk_growth=0.010,
        net=(6.0, 18.0), trend=0.0, noise=0.22,
        note="Real workload on far too much machine. The rightsizing tail.",
    ),
    "dev_workstation": dict(
        workload_class="low_variable", shape=OFFICE_HOURS, weekend=0.08,
        cpu=(9.0, 24.0), burst=0.45, mem=(35, 55), disk=(30, 60), disk_growth=0.020,
        net=(8.0, 22.0), trend=0.0, noise=0.35,
        note="Engineer's box. Busy 10-18 on weekdays, dead at the weekend.",
    ),
    "ci_runner": dict(
        workload_class="moderate", shape=OFFICE_HOURS, weekend=0.12,
        cpu=(18.0, 46.0), burst=0.95, mem=(40, 62), disk=(35, 70), disk_growth=0.055,
        net=(20.0, 55.0), trend=0.0, noise=0.55,
        note="Build agent. Extremely spiky, idle overnight.",
    ),
    "batch_nightly": dict(
        workload_class="moderate", shape=NIGHTLY_BATCH, weekend=0.85,
        cpu=(22.0, 68.0), burst=0.60, mem=(45, 72), disk=(40, 78), disk_growth=0.070,
        net=(25.0, 70.0), trend=0.0, noise=0.30,
        note="Nightly ETL. Inverted profile: hot at 02:00, idle by day.",
    ),
    # Ceilings are peak-hour values. An OFFICE_HOURS machine averages roughly
    # 0.5x its ceiling once nights and weekends are included, so the ceiling is
    # set well above the band the machine should land in.
    "interactive_web": dict(
        workload_class="production", shape=OFFICE_HOURS, weekend=0.35,
        cpu=(52.0, 88.0), burst=0.35, mem=(48, 68), disk=(40, 65), disk_growth=0.030,
        net=(30.0, 68.0), trend=0.02, noise=0.28,
        note="Customer-facing app. Clean business-hours curve.",
    ),
    "api_backend": dict(
        workload_class="production", shape=ALWAYS_ON, weekend=0.62,
        cpu=(52.0, 78.0), burst=0.25, mem=(52, 72), disk=(45, 70), disk_growth=0.035,
        net=(35.0, 72.0), trend=0.03, noise=0.20,
        note="Always-on API. Steady load, mild day/night swing.",
    ),
    "database": dict(
        workload_class="production", shape=ALWAYS_ON, weekend=0.70,
        cpu=(30.0, 46.0), burst=0.20, mem=(74, 88), disk=(58, 86), disk_growth=0.090,
        net=(25.0, 50.0), trend=0.04, noise=0.14,
        note="Database. Moderate CPU but memory and disk are the constraint.",
    ),
    "memory_bound": dict(
        workload_class="production", shape=ALWAYS_ON, weekend=0.75,
        cpu=(8.0, 16.0), burst=0.15, mem=(80, 93), disk=(50, 72), disk_growth=0.040,
        net=(10.0, 24.0), trend=0.02, noise=0.16,
        note="Low CPU, high memory. Looks idle on CPU alone; downsizing it would OOM.",
    ),
    # A saturated system does not get a quiet weekend, which is precisely why
    # it is in trouble. Kept near-flat and high, with an upward drift so the
    # 48h window the analyst reads sits above the longer-run baseline.
    "saturated": dict(
        workload_class="production", shape=ALWAYS_ON, weekend=0.88,
        # Ceiling is deliberately below the clip limit: peak-hour shape (1.10)
        # and the upward trend multiply on top, and a machine railed flat at 99%
        # looks like a broken sensor rather than a busy server.
        cpu=(68.0, 80.0), burst=0.10, mem=(74, 92), disk=(62, 88), disk_growth=0.085,
        net=(45.0, 82.0), trend=0.12, noise=0.12,
        note="Running hot and trending up. The scale-up case.",
    ),
}

# How many of each archetype. Proportions follow what FinOps audits typically
# report: a small idle tail, a large over-provisioned middle, a healthy core,
# and a handful of machines genuinely under pressure.
FLEET_MIX = {
    "zombie": 7,
    "oversized": 14,
    "dev_workstation": 3,
    "ci_runner": 3,
    "batch_nightly": 4,
    "interactive_web": 7,
    "api_backend": 5,
    "database": 4,
    "memory_bound": 2,
    "saturated": 5,
}


def stable_rng(value: str) -> np.random.Generator:
    digest = hashlib.sha256(f"{value}-{SEED}".encode()).hexdigest()
    return np.random.default_rng(int(digest[:12], 16) % (2**32))


def ou_noise(n: int, sigma: float, rng: np.random.Generator) -> np.ndarray:
    """Ornstein-Uhlenbeck-ish walk: correlated wobble, not white noise.

    Real utilization drifts. Independent samples per hour look obviously fake
    on a sparkline.
    """
    out = np.zeros(n)
    for i in range(1, n):
        out[i] = 0.82 * out[i - 1] + rng.normal(0, sigma)
    return out


def build_series(vm: str, archetype: str, timestamps: pd.Series) -> pd.DataFrame:
    cfg = ARCHETYPES[archetype]
    rng = stable_rng(vm)
    n = len(timestamps)
    hours = timestamps.dt.hour.to_numpy()
    weekday = timestamps.dt.weekday.to_numpy()

    low, high = cfg["cpu"]
    # Each machine sits at its own point in the archetype's band, so machines
    # of the same kind are not clones of each other.
    ceiling = rng.uniform(low, high)
    shape = np.asarray(cfg["shape"], dtype=float)[hours]
    weekend_factor = np.where(weekday >= 5, cfg["weekend"], 1.0)

    # Slow drift over the window: saturated machines climb toward their limit.
    progress = np.linspace(0.0, 1.0, n)
    trend = 1.0 + cfg["trend"] * progress

    cpu = ceiling * shape * weekend_factor * trend
    cpu = cpu * (1.0 + ou_noise(n, cfg["noise"] * 0.30, rng))

    # Bursts land during the archetype's own busy window, not at random.
    if cfg["burst"] > 0:
        busy = shape > np.percentile(shape, 60)
        n_bursts = int(rng.integers(6, 26))
        for _ in range(n_bursts):
            start = int(rng.integers(0, max(1, n - 8)))
            if not busy[start]:
                continue
            length = int(rng.integers(2, 9))
            size = ceiling * cfg["burst"] * rng.uniform(0.5, 1.5)
            cpu[start:start + length] += size * np.hanning(max(3, length + 2))[1:length + 1]

    cpu = np.clip(cpu, 0.05, 99.0)

    # Memory follows CPU loosely but keeps its own floor: this is what makes a
    # memory-bound machine look wrong to rightsize on CPU alone.
    m_low, m_high = cfg["mem"]
    mem_base = rng.uniform(m_low, m_high)
    mem = mem_base + (cpu / max(ceiling, 1.0)) * (m_high - m_low) * 0.35
    mem = np.clip(mem + ou_noise(n, 0.5, rng), 4.0, 96.0)

    # Disk only grows, with occasional cleanups.
    d_low, d_high = cfg["disk"]
    disk = np.zeros(n)
    disk[0] = rng.uniform(d_low, d_high)
    growth = cfg["disk_growth"]
    next_cleanup = int(rng.integers(500, 1400))
    for i in range(1, n):
        disk[i] = disk[i - 1] + growth * rng.uniform(0.7, 1.3)
        if i == next_cleanup:
            disk[i] = max(d_low, disk[i] - rng.uniform(8, 20))
            next_cleanup = i + int(rng.integers(500, 1400))
    disk = np.clip(disk + rng.normal(0, 0.15, n), 3.0, 97.0)

    # Network tracks CPU for anything serving traffic.
    n_low, n_high = cfg["net"]
    net = n_low + (cpu / max(ceiling, 1.0)) * (n_high - n_low)
    net = np.clip(net * rng.uniform(0.85, 1.15, n) + ou_noise(n, 0.8, rng), 0.0, 100.0)

    return pd.DataFrame({
        "timestamp": timestamps.values,
        "resource_id": vm,
        "cloud_provider": "azure",
        "cpu_percent": np.round(cpu, 4),
        "memory_percent": np.round(mem, 4),
        "disk_percent": np.round(disk, 4),
        "network_percent": np.round(net, 4),
        "workload_class": cfg["workload_class"],
        "archetype": archetype,
        "augmented": True,
    })


# Which archetypes are plausible in which environment. A machine named *-test
# must not come out as a production database: the enterprise generator reads the
# environment from the name, and the two would then contradict each other.
ARCHETYPES_BY_ENV = {
    "prod": ["saturated", "api_backend", "database", "interactive_web", "memory_bound", "oversized"],
    "uat": ["oversized", "batch_nightly", "interactive_web", "ci_runner"],
    "test": ["zombie", "oversized", "ci_runner", "batch_nightly"],
    "dev": ["dev_workstation", "zombie", "oversized", "ci_runner"],
}


def env_hint(vm: str) -> str:
    """Mirror of infer_environment in generate_enterprise_context.py."""
    name = vm.lower()
    if "uat" in name:
        return "uat"
    if any(k in name for k in ("test", "demo", "rule", "sample")):
        return "test"
    if any(k in name for k in ("dev", "poc")):
        return "dev"
    if any(k in name for k in ("prod", "-ir-", "snow", "bi")):
        return "prod"
    return "prod"


def assign_archetypes(vm_names: list[str]) -> dict[str, str]:
    """Spread the fleet mix across machines, respecting their environment.

    Deterministic: same names in, same assignment out.
    """
    remaining = dict(FLEET_MIX)
    assignment: dict[str, str] = {}

    def take(archetype: str) -> bool:
        if remaining.get(archetype, 0) > 0:
            remaining[archetype] -= 1
            return True
        return False

    # Most-constrained environments first, so prod-only archetypes are not
    # consumed by machines that had other options.
    for environment in ("prod", "uat", "dev", "test"):
        for vm in sorted(v for v in vm_names if env_hint(v) == environment):
            for candidate in ARCHETYPES_BY_ENV[environment]:
                if take(candidate):
                    assignment[vm] = candidate
                    break

    # Anything left over gets whatever quota remains, then falls back to the
    # safest guess for its environment.
    leftovers = [a for a, count in remaining.items() for _ in range(count)]
    leftovers.sort()
    for vm in sorted(vm_names):
        if vm in assignment:
            continue
        allowed = ARCHETYPES_BY_ENV[env_hint(vm)]
        match = next((a for a in leftovers if a in allowed), None)
        if match:
            leftovers.remove(match)
            assignment[vm] = match
        else:
            assignment[vm] = allowed[0]
    return assignment


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Missing {SOURCE}. Nothing to base the timeline on.")

    existing = pd.read_csv(SOURCE, parse_dates=["timestamp"])
    real = existing[existing["resource_id"].isin(REAL_VMS)].copy()
    synthetic_names = sorted(set(existing["resource_id"]) - REAL_VMS)

    # 90 days of hourly points ending where the source data ends. The source
    # spans 235 days but each machine only covered part of it; giving all 56 the
    # full span would quadruple the file for no analytical gain, and 90 days is
    # the window FinOps reviews actually use.
    end = pd.Timestamp(existing["timestamp"].max()).floor("h")
    timeline = pd.Series(pd.date_range(end=end, periods=WINDOW_HOURS, freq="h"))
    print(f"timeline: {len(timeline):,} hourly points, {timeline.min()} -> {timeline.max()}")
    print(f"machines: {len(synthetic_names)} synthetic + {len(real['resource_id'].unique())} real")

    assignment = assign_archetypes(synthetic_names)
    counts = pd.Series(list(assignment.values())).value_counts()
    print("\narchetype mix:")
    for archetype, count in counts.items():
        print(f"  {archetype:<18} {count:>3}   {ARCHETYPES[archetype]['note']}")

    frames = [build_series(vm, assignment[vm], timeline) for vm in synthetic_names]

    if not real.empty:
        # Trim to the same window rather than resampling: these values are the
        # real observations and must not be interpolated or invented.
        real = real[real["timestamp"] >= timeline.min()].copy()
        real["archetype"] = "real_corestack_production"
        real["augmented"] = False
        frames.append(real)
        print(f"\nreal CoreStack rows kept unmodified: {len(real):,}")

    out = pd.concat(frames, ignore_index=True).sort_values(["resource_id", "timestamp"])
    out.to_csv(OUTPUT, index=False)

    per_vm = out.groupby("resource_id")["cpu_percent"].mean()
    print(f"\nwrote {len(out):,} rows to {OUTPUT}")
    print("\nfleet mean-CPU spread:")
    for label, low, high in [
        ("idle      <2%", 0, 2), ("very low 2-10%", 2, 10), ("low     10-25%", 10, 25),
        ("moderate 25-50%", 25, 50), ("busy    50-75%", 50, 75), ("saturated >75%", 75, 1e9),
    ]:
        print(f"  {label:<16} {((per_vm >= low) & (per_vm < high)).sum():>3}")


if __name__ == "__main__":
    main()
