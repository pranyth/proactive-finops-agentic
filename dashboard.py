import streamlit as st
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from datetime import datetime
from pathlib import Path
import random

st.set_page_config(page_title="Proactive Cloud FinOps", page_icon="☁️", layout="wide")
st.title("☁️ Proactive Cloud FinOps — CoreStack Integration")
st.markdown("**PES University | UE23CS320A | Project ID: 60 | Data: CoreStack Azure Telemetry**")
st.divider()

@st.cache_data
def load_data():
    df = pd.read_csv("data/augmented_vm_metrics.csv", parse_dates=["timestamp"])
    p99 = df["network_percent"].quantile(0.99)
    df["network_normalized"] = (df["network_percent"] / p99 * 100).clip(0, 100)
    return df

@st.cache_data
def load_original():
    path = Path("data/corestack_vm_metrics.csv")
    if not path.exists():
        return None
    return pd.read_csv(path, parse_dates=["timestamp"])

@st.cache_data
def classify_vms(df):
    results = []
    for vm_name, group in df.groupby("resource_id"):
        cpu = group["cpu_percent"].fillna(0)
        results.append({
            "VM": vm_name,
            "Class": group["workload_class"].iloc[0] if "workload_class" in group.columns else "unknown",
            "Mean CPU": round(cpu.mean(), 2),
            "Max CPU": round(cpu.max(), 2),
            "Records": len(group)
        })
    return pd.DataFrame(results)

@st.cache_data
def get_recommendations(df):
    results = []
    for vm_name, group in df.groupby("resource_id"):
        cpu = group["cpu_percent"].fillna(0)
        threshold = cpu.mean() + 1.5 * cpu.std()
        latest = group.sort_values("timestamp").tail(48)
        latest_cpu = latest["cpu_percent"].fillna(0)
        latest_mean = latest_cpu.mean()
        latest_max = latest_cpu.max()

        if latest_mean > threshold:
            action = "⬆️ SCALE UP"
            urgency = round((latest_mean - threshold) / threshold * 100, 1)
            reason = f"Avg CPU {latest_mean:.1f}% exceeds threshold {threshold:.1f}%"
        elif latest_mean < threshold * 0.3 and threshold > 5:
            action = "⬇️ SCALE DOWN"
            urgency = round((threshold * 0.3 - latest_mean) / threshold * 100, 1)
            reason = f"Avg CPU {latest_mean:.1f}% well below threshold {threshold:.1f}%"
        else:
            action = "✅ OK"
            urgency = 0
            reason = "Within normal range"

        results.append({
            "VM": vm_name,
            "Recommendation": action,
            "Urgency Score": urgency,
            "Avg CPU (48h)": round(latest_mean, 1),
            "Max CPU (48h)": round(latest_max, 1),
            "Auto Threshold": round(threshold, 1),
            "Reason": reason
        })

    df_rec = pd.DataFrame(results)
    top10 = df_rec[df_rec["Recommendation"] != "✅ OK"].sort_values(
        "Urgency Score", ascending=False).head(10)
    return df_rec, top10

@st.cache_data
def get_metric_availability(df):
    availability = []
    for vm_name, group in df.groupby("resource_id"):
        availability.append({
            "VM": vm_name,
            "CPU": "✅" if group["cpu_percent"].sum() > 0 else "❌",
            "Network": "✅" if group["network_percent"].sum() > 0 else "❌",
            "Memory": "⚠️ Not collected" if group["memory_percent"].sum() == 0 else "✅",
            "Disk": "⚠️ Not collected" if group["disk_percent"].sum() == 0 else "✅",
            "Workload Class": group["workload_class"].iloc[0] if "workload_class" in group.columns else "unknown",
            "Records": len(group)
        })
    return pd.DataFrame(availability)

@st.cache_data
def run_model(vm_name):
    """
    Random Forest model with 4-metric feature engineering.
    Features (per timestep, lookback=48h):
      - 48 CPU readings          (raw lookback)
      - 48 Network readings      (correlated signal)
      - 48 Memory readings       (pressure/leak signal)
      - 48 Disk readings         (write-activity signal)
      - 4  temporal features     (hour, dow, is_weekend, hour_norm)
      - 12 CPU rolling stats     (mean/max/std at 48h, 12h, 6h windows)
      - 6  Network rolling stats (mean/max at 48h, 12h, 6h)
      - 6  Memory rolling stats  (mean/max at 48h, 12h, 6h)
      - 4  Disk rolling stats    (mean/max at 48h, 6h)
      - 3  cross-metric features (cpu-mem delta, cpu-net ratio, mem pressure flag)
    Total: 179 features
    """
    df = pd.read_csv("data/augmented_vm_metrics.csv", parse_dates=["timestamp"])
    vm = df[df["resource_id"] == vm_name].sort_values("timestamp").reset_index(drop=True)

    # All metrics already normalized 0-100 in augmented CSV
    cpu  = vm["cpu_percent"].fillna(0).values
    net  = vm["network_percent"].fillna(0).values
    mem  = vm["memory_percent"].fillna(0).values
    disk = vm["disk_percent"].fillna(0).values
    timestamps = vm["timestamp"].values

    LOOKBACK = 48
    split = int(len(cpu) * 0.8)
    threshold = round(float(cpu[:split].mean() + 1.5 * cpu[:split].std()), 2)

    def make_features(cpu_s, net_s, mem_s, disk_s, ts_arr, lookback):
        X, y = [], []
        for i in range(lookback, len(cpu_s)):
            ts  = pd.Timestamp(ts_arr[i])
            cw  = cpu_s[i-lookback:i]
            nw  = net_s[i-lookback:i]
            mw  = mem_s[i-lookback:i]
            dw  = disk_s[i-lookback:i]

            # Raw lookback windows (48 each)
            feats = list(cw) + list(nw) + list(mw) + list(dw)

            # Temporal
            feats += [
                ts.hour,
                ts.dayofweek,
                int(ts.dayofweek >= 5),
                ts.hour / 23.0,
            ]

            # CPU rolling stats
            feats += [
                float(np.mean(cw)),        # 48h mean
                float(np.max(cw)),         # 48h max
                float(np.std(cw)),         # 48h std
                float(np.mean(cw[-12:])),  # 12h mean
                float(np.max(cw[-12:])),   # 12h max
                float(np.std(cw[-12:])),   # 12h std
                float(np.mean(cw[-6:])),   # 6h mean
                float(np.max(cw[-6:])),    # 6h max
                float(np.std(cw[-6:])),    # 6h std
                float(cw[-1] - cw[-6]),    # 6h trend (slope proxy)
                float(cw[-1] - np.mean(cw)),  # deviation from 48h mean
                float(np.percentile(cw, 90)), # 90th pct of lookback
            ]

            # Network rolling stats
            feats += [
                float(np.mean(nw)),
                float(np.max(nw)),
                float(np.mean(nw[-12:])),
                float(np.max(nw[-12:])),
                float(np.mean(nw[-6:])),
                float(np.max(nw[-6:])),
            ]

            # Memory rolling stats
            feats += [
                float(np.mean(mw)),
                float(np.max(mw)),
                float(np.mean(mw[-12:])),
                float(np.max(mw[-12:])),
                float(np.mean(mw[-6:])),
                float(np.max(mw[-6:])),
            ]

            # Disk rolling stats
            feats += [
                float(np.mean(dw)),
                float(np.max(dw)),
                float(np.mean(dw[-6:])),
                float(np.max(dw[-6:])),
            ]

            # Cross-metric features (the key new signal)
            cpu_mem_delta  = float(cw[-1] - mw[-1] / 100.0 * cw[-1])  # CPU not relieved by mem
            cpu_net_ratio  = float(cw[-1] / (nw[-1] + 1e-6))           # CPU/network load ratio
            mem_pressure   = float(np.mean(mw[-6:]) - np.mean(mw[-48:-6])) # mem trending up?
            feats += [cpu_mem_delta, cpu_net_ratio, mem_pressure]

            X.append(feats)
            y.append(cpu_s[i])
        return np.array(X), np.array(y)

    X_train, y_train = make_features(
        cpu[:split], net[:split], mem[:split], disk[:split], timestamps[:split], LOOKBACK)
    X_test, y_test = make_features(
        cpu[split:], net[split:], mem[split:], disk[split:], timestamps[split:], LOOKBACK)

    model = RandomForestRegressor(n_estimators=200, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    y_pred = np.clip(model.predict(X_test), 0, 100)

    mae  = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))

    proactive = sum(1 for p, a in zip(y_pred, y_test) if p > threshold and a > threshold)
    missed    = sum(1 for p, a in zip(y_pred, y_test) if p <= threshold and a > threshold)
    accuracy  = proactive / (proactive + missed) * 100 if (proactive + missed) > 0 else 0

    corr = round(float(pd.Series(cpu).corr(pd.Series(net))), 3)

    return {
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "accuracy": round(accuracy, 1),
        "proactive": proactive,
        "missed": missed,
        "threshold": threshold,
        "corr": corr,
        "y_test": y_test,
        "y_pred": y_pred,
        "test_timestamps": timestamps[split + LOOKBACK:],
        "train_end": timestamps[split],
    }

def generate_lambda_log():
    vms = ["cspbi-prod-ir-Europe", "cs-prod-ir-vm-india", "analytics-jump-host",
           "corestack-openvpn", "vm0-cspbi"]
    actions = ["Scale Up", "Scale Down"]
    statuses = ["✅ Success", "✅ Success", "✅ Success", "❌ Failed"]
    log = []
    for i in range(15):
        vm = random.choice(vms)
        action = random.choice(actions)
        status = random.choice(statuses)
        log.append({
            "Timestamp": f"2026-03-{random.randint(1,28):02d} {random.randint(0,23):02d}:{random.randint(0,59):02d}",
            "VM": vm,
            "Action": action,
            "Trigger": f"CPU threshold breach",
            "Function": "azure-finops-scaler",
            "Status": status,
            "Duration (ms)": random.randint(200, 2000)
        })
    return pd.DataFrame(log).sort_values("Timestamp", ascending=False)

df = load_data()
orig_df = load_original()
vm_classes = classify_vms(df)
all_recs, top10 = get_recommendations(df)
avail_df = get_metric_availability(df)

# --- Fleet Overview ---
st.subheader("📊 Fleet Overview")
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total VMs", df["resource_id"].nunique())
col2.metric("Total Records", f"{len(df):,}")
col3.metric("Date Range", f"{df['timestamp'].min().date()} → {df['timestamp'].max().date()}")
col4.metric("⬆️ Scale Up Needed", len(top10[top10["Recommendation"].str.contains("UP")]))
col5.metric("⬇️ Scale Down Needed", len(top10[top10["Recommendation"].str.contains("DOWN")]))
st.divider()

# --- Recommendations Engine ---
st.subheader("🎯 Recommendations Engine — Top 10 VMs")
st.markdown("Auto-calibrated per VM using dynamic threshold (mean + 1.5σ from training data). "
            "Urgency score reflects how far the VM is from its normal operating range.")
if not top10.empty:
    st.dataframe(
        top10[["VM", "Recommendation", "Urgency Score",
               "Avg CPU (48h)", "Max CPU (48h)", "Auto Threshold", "Reason"]],
        use_container_width=True, hide_index=True
    )
else:
    st.success("All VMs within normal operating range.")
st.divider()

# --- Data Augmentation ---
st.subheader("🔬 Data Augmentation — Low Variable → Regime Change")
st.markdown("""
**Mentor requirement:** *"Modify 46% dataset using AI such that it becomes similar to the 6% dataset"*

We analyzed spike characteristics from real production VMs (`cspbi-prod-ir-Europe`, `cs-prod-ir-vm-india`)
and injected statistically similar sustained burst patterns into 26 low_variable VMs.
""")

aug_spikes = len(df[df["cpu_percent"] > 20])
augmented_vm_count = df[df["augmented"] == True]["resource_id"].nunique() if "augmented" in df.columns else 0

if orig_df is None:
    st.info(
        "`data/corestack_vm_metrics.csv` is not included in this clean demo repo. "
        "The dashboard is using the checked-in augmented dataset, which is enough for clone-and-run demos."
    )
    col1, col2 = st.columns(2)
    col1.metric("Spike Events in Demo Dataset", aug_spikes)
    col2.metric("Augmented VMs", augmented_vm_count)

    aug_vm = st.selectbox(
        "Inspect augmented VM signal",
        sorted(df[df["augmented"] == True]["resource_id"].unique())
        if "augmented" in df.columns else sorted(df["resource_id"].unique()),
    )
    aug_vm_data = df[df["resource_id"] == aug_vm].sort_values("timestamp")

    fig_aug, ax = plt.subplots(figsize=(13, 3.5))
    ax.plot(aug_vm_data["timestamp"], aug_vm_data["cpu_percent"], color="tomato", linewidth=0.8)
    ax.set_title(f"{aug_vm} - Augmented CPU signal")
    ax.set_ylabel("CPU %")
    plt.tight_layout()
    st.pyplot(fig_aug)
    plt.close()
else:
    col1, col2, col3 = st.columns(3)
    orig_spikes = len(orig_df[orig_df["cpu_percent"] > 20])
    col1.metric("Spike Events Before", orig_spikes)
    col2.metric("Spike Events After", aug_spikes)
    col3.metric("Improvement", f"{aug_spikes / max(orig_spikes, 1):.1f}x")

    aug_vm = st.selectbox(
        "Compare VM before/after augmentation",
        sorted(df[df["augmented"] == True]["resource_id"].unique())
        if "augmented" in df.columns else ["analytics-jump-host"],
    )

    orig_vm_data = orig_df[orig_df["resource_id"] == aug_vm].sort_values("timestamp")
    aug_vm_data = df[df["resource_id"] == aug_vm].sort_values("timestamp")

    fig_aug, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 5))
    ax1.plot(orig_vm_data["timestamp"], orig_vm_data["cpu_percent"], color="steelblue", linewidth=0.8)
    ax1.set_title(f"{aug_vm} - Original")
    ax1.set_ylabel("CPU %")
    ax2.plot(aug_vm_data["timestamp"], aug_vm_data["cpu_percent"], color="tomato", linewidth=0.8)
    ax2.set_title(f"{aug_vm} - Augmented")
    ax2.set_ylabel("CPU %")
    plt.tight_layout()
    st.pyplot(fig_aug)
    plt.close()

st.divider()

# --- Workload Classification ---
st.subheader("🔍 Workload Classification")
col_left, col_right = st.columns([2, 3])
with col_left:
    class_counts = vm_classes["Class"].value_counts()
    colors = {
        "idle": "#5b9bd5", "low_variable": "#ed7d31",
        "regime_change": "#70ad47", "bursty_scheduled": "#ff4444",
        "consistently_high": "#ffc000"
    }
    fig, ax = plt.subplots(figsize=(5, 4))
    wedges, texts, autotexts = ax.pie(
        class_counts.values, labels=None,
        autopct="%1.0f%%",
        colors=[colors.get(c, "gray") for c in class_counts.index],
        startangle=90, pctdistance=0.6
    )
    ax.legend(wedges, class_counts.index,
              loc="lower center", bbox_to_anchor=(0.5, -0.15),
              ncol=2, fontsize=8)
    ax.set_title("VM Distribution by Workload Type")
    plt.tight_layout()
    st.pyplot(fig)
    plt.close()

with col_right:
    st.markdown("**Prediction strategy per workload class:**")
    st.markdown("""
    - 🟢 **regime_change** — Random Forest, 48h lookback, CPU + Network, dynamic threshold
    - 🔴 **bursty_scheduled** — Time-pattern model weighted on hour/day-of-week
    - 🟠 **low_variable** — Augmented to regime_change quality
    - 🔵 **idle** — Skipped
    """)
    active = vm_classes[vm_classes["Class"].isin(["regime_change", "bursty_scheduled"])]
    st.dataframe(active[["VM", "Class", "Mean CPU", "Max CPU"]],
                 use_container_width=True, hide_index=True)
st.divider()

# --- Model Performance ---
st.subheader("🤖 Predictive Model — Auto-Calibrated Per VM")
target_vms = ["cspbi-prod-ir-Europe", "cs-prod-ir-vm-india", "analytics-jump-host"]
selected_vm = st.selectbox("Select VM", target_vms)

with st.spinner(f"Training on {selected_vm}..."):
    results = run_model(selected_vm)

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("MAE", f"{results['mae']}%")
col2.metric("RMSE", f"{results['rmse']}%")
col3.metric("Proactive Accuracy", f"{results['accuracy']}%")
col4.metric("Proactive Catches", results["proactive"])
col5.metric("Auto Threshold", f"{results['threshold']}%")
col6.metric("CPU-Network Corr", results["corr"])
st.caption(f"⚙️ Threshold = mean + 1.5σ from training data only | "
           f"Train: up to {pd.Timestamp(results['train_end']).date()}")

fig2, ax2 = plt.subplots(figsize=(13, 4))
ax2.plot(results["test_timestamps"], results["y_test"],
         label="Actual CPU", color="steelblue", linewidth=0.8)
ax2.plot(results["test_timestamps"], results["y_pred"],
         label="Predicted CPU", color="orange", linewidth=0.8, linestyle="--")
ax2.axhline(y=results["threshold"], color="red", linestyle=":",
            linewidth=1.5, label=f"Auto Threshold ({results['threshold']}%)")
ax2.set_title(f"CPU Forecast vs Actual — {selected_vm} (Test Period)")
ax2.set_xlabel("Timestamp")
ax2.set_ylabel("CPU %")
ax2.legend()
plt.tight_layout()
st.pyplot(fig2)
plt.close()
st.divider()

# --- Correlation ---
st.subheader("📡 Multi-Metric Correlation — CPU vs Network")
vm_data = df[df["resource_id"] == selected_vm].sort_values("timestamp")
corr_val = vm_data["cpu_percent"].corr(vm_data["network_normalized"])
spikes = vm_data[vm_data["cpu_percent"] > results["threshold"]]
normal = vm_data[vm_data["cpu_percent"] <= results["threshold"]]

col1, col2 = st.columns(2)
with col1:
    fig3, ax3 = plt.subplots(figsize=(6, 4))
    ax3.bar(["Normal periods", "Spike periods"],
            [normal["network_normalized"].mean(),
             spikes["network_normalized"].mean() if len(spikes) > 0 else 0],
            color=["steelblue", "tomato"])
    ax3.set_ylabel("Avg Network Utilization %")
    ax3.set_title(f"Network Usage: Normal vs Spike Periods\nPearson r = {corr_val:.3f}")
    plt.tight_layout()
    st.pyplot(fig3)
    plt.close()

with col2:
    fig4, ax4 = plt.subplots(figsize=(6, 4))
    ax4.scatter(vm_data["network_normalized"], vm_data["cpu_percent"],
                alpha=0.3, color="steelblue", s=5)
    ax4.axhline(y=results["threshold"], color="red", linestyle=":",
                linewidth=1, label=f"Threshold {results['threshold']}%")
    ax4.set_xlabel("Network Utilization %")
    ax4.set_ylabel("CPU %")
    ax4.set_title(f"CPU vs Network Scatter\nr = {corr_val:.3f}")
    ax4.legend(fontsize=8)
    plt.tight_layout()
    st.pyplot(fig4)
    plt.close()
st.divider()

# --- Metric Availability ---
st.subheader("📋 Metric Availability Status")
st.markdown("System scan of all 56 VMs showing which metrics are currently being collected.")
col1, col2, col3 = st.columns(3)
col1.metric("CPU Available", f"{len(avail_df[avail_df['CPU']=='✅'])} VMs")
col2.metric("Network Available", f"{len(avail_df[avail_df['Network']=='✅'])} VMs")
col3.metric("Memory Available", "0 VMs ⚠️")
st.dataframe(avail_df, use_container_width=True, hide_index=True)
st.warning("💡 Memory and Disk metrics not collected. "
           "Recommend enabling Azure Monitor memory collection for richer predictions.")
st.divider()

# --- Lambda / Azure Functions Log ---
st.subheader("⚡ Workflow Executor — Azure Functions Execution Log")
st.markdown("""
Automated rightsizing workflows triggered by the Recommendation Agent.
Each recommendation triggers an **Azure Function** (`azure-finops-scaler`) 
that executes the scale up/down action and logs the result.
""")

log_df = generate_lambda_log()
total = len(log_df)
success = len(log_df[log_df["Status"].str.contains("Success")])
failed = len(log_df[log_df["Status"].str.contains("Failed")])

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Executions", total)
col2.metric("Successful", success)
col3.metric("Failed", failed)
col4.metric("Success Rate", f"{success/total*100:.1f}%")

st.dataframe(log_df, use_container_width=True, hide_index=True)
st.caption("⚙️ Azure Functions integration stub — real execution pending Azure Function deployment.")
st.divider()

# --- Telemetry Explorer ---
st.subheader("📈 Telemetry Explorer")
col_l, col_r = st.columns([3, 1])
with col_r:
    all_vms = sorted(df["resource_id"].unique())
    explorer_vm = st.selectbox("VM", all_vms, key="explorer")
    metric = st.selectbox("Metric", ["cpu_percent", "network_normalized"])
    days = st.slider("Days", 7, 180, 30)
with col_l:
    vm_exp = df[df["resource_id"] == explorer_vm].sort_values("timestamp").tail(days * 24)
    dyn_thresh = vm_exp["cpu_percent"].mean() + 1.5 * vm_exp["cpu_percent"].std()
    fig5, ax5 = plt.subplots(figsize=(10, 3))
    ax5.plot(vm_exp["timestamp"], vm_exp[metric], color="steelblue", linewidth=0.7)
    if metric == "cpu_percent":
        ax5.axhline(y=dyn_thresh, color="red", linestyle=":",
                    linewidth=1, label=f"Dynamic threshold ({dyn_thresh:.1f}%)")
        ax5.legend(fontsize=8)
    ax5.set_title(f"{explorer_vm} — {metric} (last {days} days)")
    ax5.set_xlabel("Date")
    ax5.set_ylabel(metric)
    plt.tight_layout()
    st.pyplot(fig5)
    plt.close()

st.divider()
st.caption("Proactive Cloud FinOps | PES University Capstone 2025 | CoreStack Industry Partner")
