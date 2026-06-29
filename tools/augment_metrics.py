"""
augment_metrics.py  v3
Fixes: real prod CPU/Network preserved correctly, network normalized before groupby
"""
import pandas as pd
import numpy as np

INPUT_CSV  = "data/corestack_vm_metrics.csv"
OUTPUT_CSV = "data/augmented_vm_metrics.csv"

CSPBI_HOURLY = {
    0: 0.326, 1: 0.407, 2: 0.603, 3: 0.350, 4: 0.382,
    5: 0.745, 6: 0.312, 7: 0.377, 8: 0.546, 9: 0.341,
    10: 0.280, 11: 0.297, 12: 0.376, 13: 0.823, 14: 0.553,
    15: 0.350, 16: 0.331, 17: 0.484, 18: 0.331, 19: 0.476,
    20: 1.000, 21: 1.008, 22: 0.513, 23: 0.416,
}
CSPBI_DOW = {0: 1.02, 1: 1.01, 2: 0.99, 3: 0.94, 4: 0.99, 5: 1.05, 6: 1.00}
NETWORK_SPIKE = 76.0
NETWORK_BASE  = 20.0
TIERS = {
    "truly_idle":   dict(cpu_base=2.5,  cpu_spike=18.0, net_base=8.0,  mem_base=28.0, mem_range=8.0,  disk_start=20.0, disk_growth=0.018),
    "low_variable": dict(cpu_base=4.5,  cpu_spike=28.0, net_base=15.0, mem_base=48.0, mem_range=10.0, disk_start=38.0, disk_growth=0.038),
    "moderate":     dict(cpu_base=7.0,  cpu_spike=35.0, net_base=22.0, mem_base=58.0, mem_range=10.0, disk_start=48.0, disk_growth=0.052),
    "production":   dict(cpu_base=10.0, cpu_spike=55.0, net_base=20.0, mem_base=65.0, mem_range=12.0, disk_start=55.0, disk_growth=0.070),
}
REAL_PROD = {"cspbi-prod-ir-Europe", "cs-prod-ir-vm-india"}

def assign_tier(mean_cpu, max_cpu):
    if mean_cpu == 0.0 and max_cpu == 0.0:
        return "truly_idle"
    elif mean_cpu < 3.0:
        return "low_variable"
    elif mean_cpu < 8.0:
        return "moderate"
    else:
        return "production"

def generate_cpu_series(timestamps, tier, rng):
    t = TIERS[tier]
    base, spike_m = t["cpu_base"], t["cpu_spike"]
    n = len(timestamps)
    hours = timestamps.dt.hour.values
    dows  = timestamps.dt.dayofweek.values
    cpu = np.array([base * CSPBI_HOURLY[h] * CSPBI_DOW[d] for h, d in zip(hours, dows)])
    noise = np.zeros(n)
    for i in range(1, n):
        noise[i] = 0.7 * noise[i-1] + 0.3 * rng.normal(0, base * 0.15)
    cpu = np.clip(cpu + noise, 0, None)
    n_bursts = {"truly_idle": 3, "low_variable": 4, "moderate": 5, "production": 6}[tier]
    used = []
    attempts = 0
    while len(used) < n_bursts and attempts < 300:
        attempts += 1
        start    = int(rng.integers(48, max(49, n - 120)))
        duration = int(rng.integers(18, 73))
        end      = min(start + duration, n)
        if any(abs(start - w) < 240 for w in used):
            continue
        used.append(start)
        mag       = rng.uniform(spike_m * 0.7, spike_m * 1.2)
        ramp_up   = max(1, int(duration * 0.30))
        hold      = max(1, int(duration * 0.40))
        ramp_down = max(1, duration - ramp_up - hold)
        burst = np.zeros(duration)
        for j in range(ramp_up):
            burst[j] = mag * (j / ramp_up)
        for j in range(ramp_up, ramp_up + hold):
            burst[j] = mag * rng.uniform(0.85, 1.0)
        for j in range(ramp_up + hold, duration):
            burst[j] = mag * (1 - (j - ramp_up - hold) / max(ramp_down, 1))
        cpu[start:end] += burst[:end-start]
    return np.clip(cpu, 0, 99.9)

def generate_network_series(cpu, tier, rng):
    t = TIERS[tier]
    threshold = np.mean(cpu) + 1.5 * np.std(cpu)
    is_spike  = cpu > threshold
    tier_spike_scale = t["net_base"] / NETWORK_BASE
    spike_level = NETWORK_SPIKE * max(0.5, tier_spike_scale)
    net = np.where(is_spike,
        spike_level   * rng.uniform(0.85, 1.10, size=len(cpu)),
        t["net_base"] * rng.uniform(0.70, 1.30, size=len(cpu)))
    noise = np.zeros(len(cpu))
    for i in range(1, len(cpu)):
        noise[i] = 0.6 * noise[i-1] + 0.4 * rng.normal(0, t["net_base"] * 0.08)
    return np.clip(net + noise, 0, 100)

def generate_memory_series(cpu, tier, rng):
    t = TIERS[tier]
    base, mem_range = t["mem_base"], t["mem_range"]
    n = len(cpu)
    threshold = np.mean(cpu) + 1.5 * np.std(cpu)
    bg = np.zeros(n)
    bg[0] = base
    for i in range(1, n):
        bg[i] = bg[i-1] + 0.02 * (base - bg[i-1]) + rng.normal(0, 0.3)
    pressure = np.zeros(n)
    decay = np.exp(-1 / 4.0)
    for i in range(1, n):
        if cpu[i] > threshold:
            excess = (cpu[i] - threshold) / max(threshold, 1)
            new_p  = mem_range * 0.8 * min(excess, 1.5)
            pressure[i] = max(pressure[i-1] * decay, new_p)
        else:
            pressure[i] = pressure[i-1] * decay
    mem = bg + pressure
    return np.clip(mem, base - mem_range, min(base + mem_range, 95))

def generate_disk_series(cpu, tier, rng):
    t = TIERS[tier]
    current = t["disk_start"] + rng.uniform(-4, 4)
    rate = t["disk_growth"]
    n = len(cpu)
    disk = np.zeros(n)
    threshold = np.mean(cpu) + 1.5 * np.std(cpu)
    next_cleanup = int(rng.integers(200, 401))
    for i in range(n):
        current += rate * rng.uniform(0.8, 1.2)
        if cpu[i] > threshold:
            current += rng.uniform(0.02, 0.07)
        if i >= next_cleanup:
            current = max(current - rng.uniform(6, 15), t["disk_start"] * 0.65)
            next_cleanup = i + int(rng.integers(200, 401))
        current += rng.normal(0, 0.04)
        disk[i] = current
    return np.clip(disk, 5, 95)

def augment():
    print("Loading original CSV...")
    df = pd.read_csv(INPUT_CSV, parse_dates=["timestamp"])
    df = df.sort_values(["resource_id", "timestamp"]).reset_index(drop=True)

    # --- Step 1: normalize raw-byte network for real prod VMs IN PLACE on df ---
    print("Normalizing real prod network columns + snapshotting...")
    real_snapshots = {}
    for vm_id in REAL_PROD:
        mask = df["resource_id"] == vm_id
        raw_cpu = df.loc[mask, "cpu_percent"].values.copy()
        raw_net = df.loc[mask, "network_percent"].values.copy()
        # Normalize network bytes -> 0-100
        if raw_net.max() > 100:
            positives = raw_net[raw_net > 0]
            p99 = np.percentile(positives, 99) if len(positives) > 0 else 1.0
            raw_net = np.clip(raw_net / p99 * 100, 0, 100)
            df.loc[mask, "network_percent"] = raw_net
        # Snapshot AFTER normalization
        real_snapshots[vm_id] = {
            "cpu": raw_cpu,
            "net": raw_net,
        }
        print(f"  {vm_id}: cpu mean={np.nanmean(raw_cpu):.2f}  net mean={np.nanmean(raw_net):.2f}  net max={np.nanmax(raw_net):.2f}")

    stats = df.groupby("resource_id")["cpu_percent"].agg(["mean", "max"])
    all_frames = []

    for vm_id, vm_df in df.groupby("resource_id"):
        vm_df = vm_df.sort_values("timestamp").copy().reset_index(drop=True)
        ts    = vm_df["timestamp"]
        tier  = assign_tier(stats.loc[vm_id, "mean"], stats.loc[vm_id, "max"])
        rng   = np.random.default_rng(abs(hash(vm_id)) % (2**31))
        print(f"  {vm_id:45s} tier={tier}")

        if vm_id in REAL_PROD:
            # Use the pre-snapshotted real values — guaranteed correct
            snap = real_snapshots[vm_id]
            cpu_series = snap["cpu"].copy()
            net_series = snap["net"].copy()
            # Fill any NaNs with interpolation
            cpu_series = pd.Series(cpu_series).interpolate(method="linear").ffill().bfill().values
            net_series = pd.Series(net_series).interpolate(method="linear").ffill().bfill().values
        else:
            cpu_series = generate_cpu_series(ts, tier, rng)
            net_series = generate_network_series(cpu_series, tier, rng)

        mem_series  = generate_memory_series(cpu_series, tier, rng)
        disk_series = generate_disk_series(cpu_series, tier, rng)

        vm_out = vm_df.copy()
        vm_out["cpu_percent"]     = cpu_series
        vm_out["network_percent"] = net_series
        vm_out["memory_percent"]  = mem_series
        vm_out["disk_percent"]    = disk_series
        vm_out["workload_class"]  = tier
        vm_out["augmented"]       = vm_id not in REAL_PROD
        all_frames.append(vm_out)

    result = pd.concat(all_frames).sort_values(["resource_id", "timestamp"]).reset_index(drop=True)
    if "cost_per_hour" in result.columns and result["cost_per_hour"].sum() == 0:
        result = result.drop(columns=["cost_per_hour"])
    result.to_csv(OUTPUT_CSV, index=False)
    print(f"\nSaved {len(result):,} rows -> {OUTPUT_CSV}")
    print(f"Columns: {result.columns.tolist()}")

    print("\n─────────────────────────────────────────────────────")
    print("VALIDATION — target: CPU-Mem r>0.40, CPU-Net r>0.60")
    print("─────────────────────────────────────────────────────")
    check_vms = ["cspbi-prod-ir-Europe", "cs-prod-ir-vm-india",
                 "analytics-jump-host", "ruletest",
                 "patch-report-aug22", "core-team-29th", "tfwus-snow-01"]
    all_pass = True
    for vm_id in check_vms:
        if vm_id not in result["resource_id"].values:
            continue
        v    = result[result["resource_id"] == vm_id]
        cpu  = v["cpu_percent"].values
        mem  = v["memory_percent"].values
        net  = v["network_percent"].values
        disk = v["disk_percent"].values
        thr  = cpu.mean() + 1.5 * cpu.std()
        spk  = (cpu > thr).sum()
        r_cm = np.corrcoef(cpu, mem)[0, 1]
        r_cn = np.corrcoef(cpu, net)[0, 1]
        ok_cm = "✓" if r_cm > 0.40 else "✗ LOW"
        ok_cn = "✓" if r_cn > 0.60 else "✗ LOW"
        if "LOW" in ok_cm or "LOW" in ok_cn:
            all_pass = False
        print(f"\n  {vm_id}")
        print(f"    CPU   mean={cpu.mean():.1f}  std={cpu.std():.1f}  max={cpu.max():.1f}  spikes={spk}")
        print(f"    Mem   mean={mem.mean():.1f}  std={mem.std():.1f}  max={mem.max():.1f}")
        print(f"    Net   mean={net.mean():.1f}  std={net.std():.1f}  max={net.max():.1f}")
        print(f"    Disk  mean={disk.mean():.1f}  std={disk.std():.1f}  max={disk.max():.1f}")
        print(f"    CPU-Mem r={r_cm:.3f} {ok_cm}    CPU-Net r={r_cn:.3f} {ok_cn}")

    print()
    if all_pass:
        print("ALL CHECKS PASSED ✓ — augmented dataset ready for model training")
    else:
        print("SOME CHECKS FAILED ✗ — review above")
    print("\nDone.")

if __name__ == "__main__":
    augment()
