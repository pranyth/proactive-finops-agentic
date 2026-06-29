"""
generate_db_metrics.py
Generates realistic DB metrics for application-tagged VMs.

Key insight from Vijay:
  "Application: VM is in trouble -> fewer connections in DB
   and the number of in/out reduces"

So DB metrics are INVERSELY correlated with VM trouble:
  - VM CPU spike    -> DB connections DROP (app struggling)
  - VM CPU spike    -> DB query latency SPIKES
  - VM network drop -> DB reads/writes DROP
"""

import pandas as pd
import numpy as np
import json

AUGMENTED_CSV = "data/augmented_vm_metrics.csv"
TAGS_JSON     = "data/vm_tags.json"
OUTPUT_CSV    = "data/db_metrics.csv"

# DB personality per application
# db_type, base_connections, base_latency_ms, base_reads, base_writes
APP_DB_PROFILES = {
    "PowerBI":    dict(db_type="postgresql", base_conn=45, base_lat=12,  base_reads=850, base_writes=120),
    "servicenow": dict(db_type="mysql",      base_conn=30, base_lat=18,  base_reads=620, base_writes=380),
    "App4":       dict(db_type="mysql",      base_conn=20, base_lat=22,  base_reads=400, base_writes=200),
    "App5":       dict(db_type="postgresql", base_conn=25, base_lat=15,  base_reads=500, base_writes=150),
    "App6":       dict(db_type="mysql",      base_conn=18, base_lat=25,  base_reads=350, base_writes=280),
    "finops":     dict(db_type="postgresql", base_conn=35, base_lat=10,  base_reads=700, base_writes=90),
    "ebol":       dict(db_type="mysql",      base_conn=15, base_lat=30,  base_reads=300, base_writes=350),
    "oracle":     dict(db_type="pgsql",      base_conn=40, base_lat=14,  base_reads=600, base_writes=100),
}

def generate_db_series(vm_df, profile, rng):
    """
    Generate DB metrics correlated with VM health.
    Core rule: VM trouble = fewer connections + higher latency + lower throughput.
    """
    cpu  = vm_df["cpu_percent"].values
    net  = vm_df["network_percent"].values
    n    = len(cpu)

    threshold = cpu.mean() + 1.5 * cpu.std()
    is_spike  = cpu > threshold
    net_drop  = net < (net.mean() - net.std())  # network below normal

    bc = profile["base_conn"]
    bl = profile["base_lat"]
    br = profile["base_reads"]
    bw = profile["base_writes"]

    # --- Connections: drop during CPU spikes (app under pressure) ---
    connections = np.zeros(n)
    for i in range(n):
        base = bc * rng.uniform(0.85, 1.15)
        if is_spike[i]:
            # VM in trouble: connections drop 20-50%
            drop = rng.uniform(0.20, 0.50)
            base *= (1 - drop)
        if net_drop[i]:
            base *= rng.uniform(0.70, 0.90)
        connections[i] = max(1, base + rng.normal(0, bc * 0.05))

    # --- Query latency: spikes when VM is under stress ---
    latency = np.zeros(n)
    for i in range(n):
        base = bl * rng.uniform(0.90, 1.10)
        if is_spike[i]:
            # Latency spikes 2-5x during VM trouble
            base *= rng.uniform(2.0, 5.0)
        latency[i] = max(1, base + rng.normal(0, bl * 0.1))

    # --- Reads: follow network, drop when network drops ---
    reads = np.zeros(n)
    for i in range(n):
        base = br * rng.uniform(0.85, 1.15)
        if is_spike[i]:
            base *= rng.uniform(0.50, 0.80)   # reads drop during trouble
        if net_drop[i]:
            base *= rng.uniform(0.40, 0.70)
        reads[i] = max(0, base + rng.normal(0, br * 0.08))

    # --- Writes: also drop but less severely ---
    writes = np.zeros(n)
    for i in range(n):
        base = bw * rng.uniform(0.85, 1.15)
        if is_spike[i]:
            base *= rng.uniform(0.60, 0.85)
        if net_drop[i]:
            base *= rng.uniform(0.50, 0.80)
        writes[i] = max(0, base + rng.normal(0, bw * 0.08))

    return (np.round(connections).astype(int),
            np.round(latency, 2),
            np.round(reads).astype(int),
            np.round(writes).astype(int))


def main():
    df   = pd.read_csv(AUGMENTED_CSV, parse_dates=["timestamp"])
    tags = json.load(open(TAGS_JSON))

    # Only generate DB metrics for application-tagged VMs
    tagged_vms = {vm: info for vm, info in tags.items()
                  if info["application"] != "untagged"
                  and info["application"] in APP_DB_PROFILES}

    print(f"Generating DB metrics for {len(tagged_vms)} application VMs:")
    frames = []

    for vm_id, info in tagged_vms.items():
        app     = info["application"]
        profile = APP_DB_PROFILES[app]
        vm_df   = df[df["resource_id"] == vm_id].sort_values("timestamp").copy()

        if len(vm_df) == 0:
            print(f"  SKIP {vm_id} — not in augmented CSV")
            continue

        rng = np.random.default_rng(abs(hash(vm_id)) % (2**31))
        conn, lat, reads, writes = generate_db_series(vm_df, profile, rng)

        out = pd.DataFrame({
            "timestamp":          vm_df["timestamp"].values,
            "resource_id":        vm_id,
            "application":        app,
            "db_type":            profile["db_type"],
            "db_connections":     conn,
            "db_query_latency_ms":lat,
            "db_reads_per_sec":   reads,
            "db_writes_per_sec":  writes,
        })
        frames.append(out)

        # Quick validation
        cpu_v  = vm_df["cpu_percent"].values
        thr    = cpu_v.mean() + 1.5 * cpu_v.std()
        spikes = cpu_v > thr
        if spikes.sum() > 0:
            conn_spike    = conn[spikes].mean()
            conn_baseline = conn[~spikes].mean()
            lat_spike     = lat[spikes].mean()
            lat_baseline  = lat[~spikes].mean()
            print(f"  {vm_id:45s} app={app:10s} db={profile['db_type']}")
            print(f"    connections: baseline={conn_baseline:.0f}  during_spike={conn_spike:.0f}  drop={100*(1-conn_spike/conn_baseline):.0f}%")
            print(f"    latency_ms:  baseline={lat_baseline:.1f}   during_spike={lat_spike:.1f}   spike={lat_spike/lat_baseline:.1f}x")

    result = pd.concat(frames).sort_values(["resource_id", "timestamp"]).reset_index(drop=True)
    result.to_csv(OUTPUT_CSV, index=False)
    print(f"\nSaved {len(result):,} rows -> {OUTPUT_CSV}")
    print(f"VMs: {result['resource_id'].nunique()}  |  DB types: {result['db_type'].unique().tolist()}")

if __name__ == "__main__":
    main()
