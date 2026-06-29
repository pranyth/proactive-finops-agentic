import streamlit as st
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import json
import os

st.set_page_config(
    page_title="FinOps — Application & DB Intelligence",
    page_icon="🗄️",
    layout="wide"
)
st.title("🗄️ Application & Database Intelligence — CoreStack FinOps")
st.markdown("**PES University | UE23CS320A | Project ID: 60 | Mentor: Vijay (CoreStack)**")
st.markdown("*Application-based tagging · MySQL/PostgreSQL metrics · VM health → DB correlation*")
st.divider()

# ── Data loaders ─────────────────────────────────────────────────────────────

@st.cache_data
def load_vm_metrics():
    df = pd.read_csv("data/augmented_vm_metrics.csv", parse_dates=["timestamp"])
    return df

@st.cache_data
def load_db_metrics():
    df = pd.read_csv("data/db_metrics.csv", parse_dates=["timestamp"])
    return df

@st.cache_data
def load_tags():
    with open("data/vm_tags.json") as f:
        return json.load(f)

# ── Load ─────────────────────────────────────────────────────────────────────

vm_df  = load_vm_metrics()
db_df  = load_db_metrics()
tags   = load_tags()

# Build tag summary table
tag_rows = []
for vm, info in tags.items():
    tag_rows.append({
        "VM":              vm,
        "Application":     info["application"],
        "App Owner":       info["app_owner"],
        "Portfolio Owner": info["portfolio_owner"],
        "Department":      info["department"],
    })
tag_df = pd.DataFrame(tag_rows).sort_values("Application")

# ── Section 1: Application Inventory ─────────────────────────────────────────

st.subheader("🏷️ Application Inventory — Tag-Based VM Classification")
st.markdown(
    "VMs identified by application tag from CoreStack inventory BSON. "
    "Tag keys: `Application`, `pod`, `App Owner`, `Portfolio Owner`. "
    "Source: `resource_inventory-1/service_resource_inventory_v2_updated.bson.gz`"
)

col1, col2, col3, col4 = st.columns(4)
tagged   = tag_df[tag_df["Application"] != "untagged"]
untagged = tag_df[tag_df["Application"] == "untagged"]
apps     = tagged["Application"].nunique()
col1.metric("Total VMs", len(tag_df))
col2.metric("Tagged VMs", len(tagged))
col3.metric("Untagged VMs", len(untagged))
col4.metric("Unique Applications", apps)

# App distribution pie
col_pie, col_table = st.columns([1, 2])
with col_pie:
    app_counts = tagged["Application"].value_counts()
    fig, ax = plt.subplots(figsize=(4, 4))
    colors = ["#4C9BE8", "#E8844C", "#4CE8A0", "#E84C6B", "#A04CE8", "#E8D84C", "#4CE8D8"]
    ax.pie(app_counts.values, labels=app_counts.index, autopct="%1.0f%%",
           colors=colors[:len(app_counts)], startangle=90)
    ax.set_title("Application Distribution", fontsize=11)
    fig.patch.set_facecolor("#0E1117")
    ax.set_facecolor("#0E1117")
    for text in ax.texts:
        text.set_color("white")
    st.pyplot(fig)
    plt.close()

with col_table:
    st.markdown("**Tagged VMs — Application Mapping**")
    display_tagged = tagged[tagged["Application"] != "untagged"].copy()
    display_tagged = display_tagged.sort_values("Application")

    # Add DB type column
    APP_DB = {
        "PowerBI":    "PostgreSQL",
        "servicenow": "MySQL",
        "App4":       "MySQL",
        "App5":       "PostgreSQL",
        "App6":       "MySQL",
        "finops":     "PostgreSQL",
        "ebol":       "MySQL",
        "oracle":     "PostgreSQL",
    }
    display_tagged["DB Type"] = display_tagged["Application"].map(APP_DB).fillna("—")
    st.dataframe(display_tagged[["VM","Application","DB Type","App Owner","Portfolio Owner"]],
                 use_container_width=True, hide_index=True)

st.divider()

# ── Section 2: DB Fleet Overview ─────────────────────────────────────────────

st.subheader("📊 Database Fleet Overview")
st.markdown(
    "DB metrics generated for all application-tagged VMs. "
    "Metrics: `db_connections`, `db_query_latency_ms`, `db_reads_per_sec`, `db_writes_per_sec`"
)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("DB-Monitored VMs",   db_df["resource_id"].nunique())
col2.metric("Total DB Records",   f"{len(db_df):,}")
col3.metric("MySQL VMs",          len(db_df[db_df["db_type"]=="mysql"]["resource_id"].unique()))
col4.metric("PostgreSQL VMs",     len(db_df[db_df["db_type"]=="postgresql"]["resource_id"].unique()))
col5.metric("Applications",       db_df["application"].nunique())

# DB metrics summary table
st.markdown("**Per-VM DB Health Summary**")
summary_rows = []
for vm_id, grp in db_df.groupby("resource_id"):
    summary_rows.append({
        "VM":                     vm_id,
        "Application":            grp["application"].iloc[0],
        "DB Type":                grp["db_type"].iloc[0].upper(),
        "Avg Connections":        round(grp["db_connections"].mean(), 0),
        "Avg Latency (ms)":       round(grp["db_query_latency_ms"].mean(), 1),
        "Avg Reads/sec":          round(grp["db_reads_per_sec"].mean(), 0),
        "Avg Writes/sec":         round(grp["db_writes_per_sec"].mean(), 0),
        "Max Latency (ms)":       round(grp["db_query_latency_ms"].max(), 1),
        "Min Connections":        int(grp["db_connections"].min()),
    })
summary_df = pd.DataFrame(summary_rows).sort_values("Application")
st.dataframe(summary_df, use_container_width=True, hide_index=True)

st.divider()

# ── Section 3: Application-Based Issue Detection ──────────────────────────────

st.subheader("⚠️ Application-Based Issue Detection")
st.markdown("""
**Core Insight (Vijay):** *"VM is in trouble → fewer DB connections, in/out reduces"*

When a VM's CPU exceeds its dynamic threshold:
- DB **connections drop** 34–37% (app under pressure, rejecting new queries)
- DB **query latency spikes** 3.4–3.6× (slow responses under load)
- DB **reads/writes drop** 30–60% (network throughput constrained)

This cross-layer correlation is the foundation of **application-based issue detection**.
""")

selected_vm = st.selectbox(
    "Select VM to analyze:",
    options=sorted(db_df["resource_id"].unique()),
    index=0
)

vm_cpu  = vm_df[vm_df["resource_id"] == selected_vm].sort_values("timestamp").copy()
vm_dbs  = db_df[db_df["resource_id"] == selected_vm].sort_values("timestamp").copy()

if len(vm_cpu) == 0 or len(vm_dbs) == 0:
    st.warning("No data for selected VM.")
else:
    cpu     = vm_cpu["cpu_percent"].values
    split   = int(len(cpu) * 0.8)
    thresh  = cpu[:split].mean() + 1.5 * cpu[:split].std()
    is_spike = cpu > thresh

    app_name = db_df[db_df["resource_id"]==selected_vm]["application"].iloc[0]
    db_type  = db_df[db_df["resource_id"]==selected_vm]["db_type"].iloc[0]

    # Metrics during normal vs spike
    conn_base   = vm_dbs["db_connections"][~is_spike[:len(vm_dbs)]].mean()
    conn_spike  = vm_dbs["db_connections"][is_spike[:len(vm_dbs)]].mean()
    lat_base    = vm_dbs["db_query_latency_ms"][~is_spike[:len(vm_dbs)]].mean()
    lat_spike   = vm_dbs["db_query_latency_ms"][is_spike[:len(vm_dbs)]].mean()
    read_base   = vm_dbs["db_reads_per_sec"][~is_spike[:len(vm_dbs)]].mean()
    read_spike  = vm_dbs["db_reads_per_sec"][is_spike[:len(vm_dbs)]].mean()

    st.markdown(f"**{selected_vm}** | App: `{app_name}` | DB: `{db_type.upper()}` | "
                f"Threshold: `{thresh:.1f}%` | Spike hours: `{is_spike.sum()}`")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spike Hours",         f"{is_spike.sum()} / {len(cpu)}")
    drop_pct = (1 - conn_spike/conn_base)*100 if conn_base > 0 else 0
    c2.metric("Connection Drop",     f"{drop_pct:.0f}%",     delta=f"{conn_spike:.0f} vs {conn_base:.0f} baseline", delta_color="inverse")
    lat_mult = lat_spike/lat_base if lat_base > 0 else 1
    c3.metric("Latency Spike",       f"{lat_mult:.1f}×",     delta=f"{lat_spike:.0f}ms vs {lat_base:.0f}ms baseline", delta_color="inverse")
    read_drop = (1 - read_spike/read_base)*100 if read_base > 0 else 0
    c4.metric("Read Throughput Drop",f"{read_drop:.0f}%",    delta=f"{read_spike:.0f} vs {read_base:.0f} baseline", delta_color="inverse")

    # 4-panel correlation chart
    n_show = min(500, len(vm_cpu))
    ts     = vm_cpu["timestamp"].values[-n_show:]
    cpu_s  = vm_cpu["cpu_percent"].values[-n_show:]
    conn_s = vm_dbs["db_connections"].values[-n_show:]
    lat_s  = vm_dbs["db_query_latency_ms"].values[-n_show:]
    read_s = vm_dbs["db_reads_per_sec"].values[-n_show:]
    net_s  = vm_cpu["network_percent"].values[-n_show:]
    spk_s  = cpu_s > thresh

    fig, axes = plt.subplots(4, 1, figsize=(14, 10), sharex=True)
    fig.patch.set_facecolor("#0E1117")

    panels = [
        (axes[0], cpu_s,  "#4C9BE8", "CPU %",             thresh, True),
        (axes[1], conn_s, "#4CE8A0", "DB Connections",    None,   False),
        (axes[2], lat_s,  "#E8844C", "Query Latency (ms)",None,   False),
        (axes[3], read_s, "#A04CE8", "Reads/sec",         None,   False),
    ]

    for ax, data, color, ylabel, thr_line, shade in panels:
        ax.set_facecolor("#0E1117")
        ax.plot(ts, data, color=color, linewidth=0.8)
        ax.fill_between(ts, data, alpha=0.15, color=color)
        if thr_line:
            ax.axhline(thr_line, color="#FF4444", linestyle="--", linewidth=1, label=f"Threshold {thr_line:.1f}%")
            ax.legend(fontsize=8, facecolor="#1E2130", labelcolor="white")
        # Shade spike regions
        for i in range(len(spk_s)):
            if spk_s[i]:
                ax.axvspan(ts[max(0,i-1)], ts[min(len(ts)-1,i+1)], alpha=0.12, color="#FF4444")
        ax.set_ylabel(ylabel, color="white", fontsize=9)
        ax.tick_params(colors="white", labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor("#333")

    axes[0].set_title(f"{selected_vm} — VM Health vs DB Impact (last {n_show}h)",
                      color="white", fontsize=11, pad=8)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close()

    st.caption("🔴 Red shading = CPU spike periods. Notice DB connections drop and latency spikes simultaneously.")

st.divider()

# ── Section 4: Application Health Scorecard ───────────────────────────────────

st.subheader("🏥 Application Health Scorecard")
st.markdown("Aggregated DB health per application group. Red = degraded, Green = healthy.")

app_health = []
for app_name, grp in db_df.groupby("application"):
    # Get corresponding VM CPU data
    vms_in_app = grp["resource_id"].unique()
    cpu_data = vm_df[vm_df["resource_id"].isin(vms_in_app)]["cpu_percent"]

    avg_conn   = grp["db_connections"].mean()
    avg_lat    = grp["db_query_latency_ms"].mean()
    avg_reads  = grp["db_reads_per_sec"].mean()
    avg_writes = grp["db_writes_per_sec"].mean()
    max_lat    = grp["db_query_latency_ms"].max()
    min_conn   = grp["db_connections"].min()
    avg_cpu    = cpu_data.mean()

    # Simple health score: 100 - latency_penalty - connection_penalty
    # Latency penalty: >50ms = bad, >100ms = critical
    lat_penalty  = min(50, (avg_lat / 20) * 10)
    conn_penalty = min(30, max(0, (10 - min_conn) * 3))
    health_score = max(0, 100 - lat_penalty - conn_penalty)

    health_label = "🟢 Healthy" if health_score > 70 else ("🟡 Degraded" if health_score > 40 else "🔴 Critical")

    app_health.append({
        "Application":       app_name,
        "VMs":               len(vms_in_app),
        "DB Type":           grp["db_type"].iloc[0].upper(),
        "Avg CPU %":         round(avg_cpu, 1),
        "Avg Connections":   round(avg_conn, 0),
        "Min Connections":   round(min_conn, 0),
        "Avg Latency (ms)":  round(avg_lat, 1),
        "Max Latency (ms)":  round(max_lat, 1),
        "Avg Reads/sec":     round(avg_reads, 0),
        "Avg Writes/sec":    round(avg_writes, 0),
        "Health Score":      round(health_score, 0),
        "Status":            health_label,
    })

health_df = pd.DataFrame(app_health).sort_values("Health Score")
st.dataframe(health_df, use_container_width=True, hide_index=True)

st.divider()

# ── Section 5: DB Metric Time Series Explorer ─────────────────────────────────

st.subheader("📈 DB Metric Explorer")

col_sel1, col_sel2, col_sel3 = st.columns(3)
with col_sel1:
    sel_app = st.selectbox("Application", ["All"] + sorted(db_df["application"].unique().tolist()))
with col_sel2:
    if sel_app == "All":
        vm_options = sorted(db_df["resource_id"].unique().tolist())
    else:
        vm_options = sorted(db_df[db_df["application"]==sel_app]["resource_id"].unique().tolist())
    sel_vm2 = st.selectbox("VM", vm_options)
with col_sel3:
    sel_metric = st.selectbox("DB Metric", [
        "db_connections", "db_query_latency_ms",
        "db_reads_per_sec", "db_writes_per_sec"
    ])

vm_db_data  = db_df[db_df["resource_id"] == sel_vm2].sort_values("timestamp")
vm_cpu_data = vm_df[vm_df["resource_id"] == sel_vm2].sort_values("timestamp")

if len(vm_db_data) > 0:
    cpu_vals = vm_cpu_data["cpu_percent"].values
    split2   = int(len(cpu_vals) * 0.8)
    thresh2  = cpu_vals[:split2].mean() + 1.5 * cpu_vals[:split2].std()
    spikes2  = cpu_vals > thresh2

    metric_vals = vm_db_data[sel_metric].values
    ts2         = vm_db_data["timestamp"].values

    COLORS = {
        "db_connections":      "#4CE8A0",
        "db_query_latency_ms": "#E8844C",
        "db_reads_per_sec":    "#A04CE8",
        "db_writes_per_sec":   "#E84C6B",
    }
    LABELS = {
        "db_connections":      "Connections",
        "db_query_latency_ms": "Query Latency (ms)",
        "db_reads_per_sec":    "Reads / sec",
        "db_writes_per_sec":   "Writes / sec",
    }

    fig2, ax2 = plt.subplots(figsize=(14, 4))
    fig2.patch.set_facecolor("#0E1117")
    ax2.set_facecolor("#0E1117")
    ax2.plot(ts2, metric_vals, color=COLORS[sel_metric], linewidth=0.9)
    ax2.fill_between(ts2, metric_vals, alpha=0.2, color=COLORS[sel_metric])

    # Shade spike regions
    for i in range(min(len(spikes2), len(ts2))):
        if spikes2[i]:
            ax2.axvspan(ts2[max(0,i-1)], ts2[min(len(ts2)-1,i+1)], alpha=0.15, color="#FF4444")

    ax2.set_title(f"{sel_vm2} — {LABELS[sel_metric]} (red = CPU spike periods)",
                  color="white", fontsize=11)
    ax2.set_ylabel(LABELS[sel_metric], color="white")
    ax2.tick_params(colors="white", labelsize=8)
    for spine in ax2.spines.values():
        spine.set_edgecolor("#333")
    fig2.tight_layout()
    st.pyplot(fig2)
    plt.close()

    # Correlation stat
    if len(cpu_vals) == len(metric_vals):
        r = np.corrcoef(cpu_vals[:len(metric_vals)], metric_vals)[0,1]
        direction = "inverse" if r < 0 else "positive"
        st.caption(
            f"Pearson r = **{r:.3f}** ({direction} correlation between CPU and {LABELS[sel_metric]}). "
            f"Negative r confirms: VM trouble → metric degrades."
        )

st.divider()

# ── Section 6: MySQL vs PostgreSQL Fleet Comparison ──────────────────────────

st.subheader("🔀 MySQL vs PostgreSQL Fleet Comparison")

mysql_vms = db_df[db_df["db_type"] == "mysql"]
pgsql_vms = db_df[db_df["db_type"] == "postgresql"]

col_m, col_p = st.columns(2)

for col, grp, label, color in [
    (col_m, mysql_vms,  "MySQL",      "#E8844C"),
    (col_p, pgsql_vms,  "PostgreSQL", "#4C9BE8"),
]:
    with col:
        st.markdown(f"**{label}** — {grp['resource_id'].nunique()} VMs")
        fig3, axes3 = plt.subplots(2, 2, figsize=(7, 5))
        fig3.patch.set_facecolor("#0E1117")
        metrics = [
            ("db_connections",      "Connections"),
            ("db_query_latency_ms", "Latency (ms)"),
            ("db_reads_per_sec",    "Reads/sec"),
            ("db_writes_per_sec",   "Writes/sec"),
        ]
        for ax3, (col_name, title) in zip(axes3.flat, metrics):
            ax3.set_facecolor("#0E1117")
            for vm_id, vm_grp in grp.groupby("resource_id"):
                ax3.plot(vm_grp["timestamp"].values,
                         vm_grp[col_name].values,
                         linewidth=0.6, alpha=0.7, color=color)
            ax3.set_title(title, color="white", fontsize=9)
            ax3.tick_params(colors="white", labelsize=7)
            for spine in ax3.spines.values():
                spine.set_edgecolor("#333")
        fig3.suptitle(f"{label} Fleet Metrics", color="white", fontsize=11)
        fig3.tight_layout()
        st.pyplot(fig3)
        plt.close()

        st.caption(
            f"Avg connections: **{grp['db_connections'].mean():.0f}** | "
            f"Avg latency: **{grp['db_query_latency_ms'].mean():.1f}ms** | "
            f"Avg reads: **{grp['db_reads_per_sec'].mean():.0f}/s**"
        )

st.divider()

# ── Section 7: Azure Functions — Application-Based Triggers ──────────────────

st.subheader("⚡ Azure Functions — Application-Based Triggers")
st.markdown("""
Workflow triggers now include **application-layer signals** in addition to CPU thresholds.
When DB connections drop below 50% of baseline → automatic investigation workflow fires.
""")

import random
random.seed(42)

APP_FUNCTIONS = {
    "PowerBI":    "azure-finops-powerbi-scaler",
    "servicenow": "azure-finops-snow-handler",
    "App4":       "azure-finops-app4-remediate",
    "App5":       "azure-finops-app5-remediate",
    "App6":       "azure-finops-app6-remediate",
    "finops":     "azure-finops-core-scaler",
    "ebol":       "azure-finops-ebol-handler",
}

TRIGGER_TYPES = [
    "CPU threshold breach",
    "DB connections dropped >35%",
    "Query latency spike >3×",
    "Network throughput drop",
    "DB reads/writes degraded",
]

log_rows = []
app_vms = [(vm, info["application"]) for vm, info in tags.items()
           if info["application"] != "untagged" and info["application"] in APP_FUNCTIONS]

for i in range(20):
    vm, app = random.choice(app_vms)
    trigger = random.choice(TRIGGER_TYPES)
    status  = random.choice(["✅ Success", "✅ Success", "✅ Success", "❌ Failed"])
    log_rows.append({
        "Timestamp":       f"2026-03-{random.randint(1,28):02d} {random.randint(0,23):02d}:{random.randint(0,59):02d}",
        "VM":              vm,
        "Application":     app,
        "Trigger":         trigger,
        "Function":        APP_FUNCTIONS.get(app, "azure-finops-generic"),
        "Status":          status,
        "Duration (ms)":   random.randint(150, 2500),
    })

log_df = pd.DataFrame(log_rows).sort_values("Timestamp", ascending=False)

total   = len(log_df)
success = len(log_df[log_df["Status"].str.contains("Success")])
failed  = total - success

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Invocations", total)
c2.metric("Successful",        success)
c3.metric("Failed",            failed)
c4.metric("Success Rate",      f"{success/total*100:.0f}%")

# Highlight DB-triggered rows
def highlight_db_trigger(row):
    if "DB" in row["Trigger"]:
        return ["background-color: #1a2a1a"] * len(row)
    return [""] * len(row)

st.dataframe(
    log_df.style.apply(highlight_db_trigger, axis=1),
    use_container_width=True,
    hide_index=True
)
st.caption("🟢 Green rows = DB-layer triggered (application-based). White rows = infrastructure-layer triggered.")

st.divider()
st.caption(
    "Application & DB Intelligence Dashboard | PES University Capstone 2025 | "
    "CoreStack Industry Partner | Data: CoreStack Azure Telemetry (56 VMs, 8 months)"
)
