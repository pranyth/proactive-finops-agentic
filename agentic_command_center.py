import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from agents.core import AGENT_CATALOG
from agents.meeting2 import bootstrap_meeting2
from agents.storage import DB_PATH, fetch_df, get_connection, init_db, table_count


st.set_page_config(
    page_title="Agentic FinOps Command Center",
    page_icon="AF",
    layout="wide",
)


def load_table(query: str) -> pd.DataFrame:
    return fetch_df(query)


def ensure_demo_data(force: bool = False) -> int:
    with get_connection(DB_PATH) as conn:
        init_db(conn)
        before = table_count(conn, "agent_runs")
        bootstrap_meeting2(conn, force=force)
        after = table_count(conn, "agent_runs")
    return after - before


ensure_demo_data(force=False)

st.title("Agentic Proactive FinOps Governance")
st.markdown(
    "**CoreStack telemetry -> agents -> SQLite storage -> command center -> Lambda-style actions**"
)
st.caption(
    "Meeting 1/2 implementation: agent architecture, common output shape, persistent run history, and storage summary."
)

if st.button("Refresh Meeting 2 Demo Runs"):
    created = ensure_demo_data(force=True)
    st.success(f"Regenerated Meeting 2 demo storage and created {created} new agent run records.")
    st.rerun()

agent_runs = load_table("SELECT * FROM agent_runs ORDER BY created_at DESC")
storage_summary = load_table("SELECT * FROM data_storage_summary ORDER BY dataset")
vm_summary = load_table("SELECT * FROM vm_metric_summary ORDER BY max_cpu DESC")
recommendations = load_table("SELECT * FROM recommendations ORDER BY urgency DESC")
pipeline_runs = load_table("SELECT * FROM pipeline_runs ORDER BY created_at DESC")
actions = load_table("SELECT * FROM serverless_action_logs ORDER BY created_at DESC")

st.divider()

st.subheader("Meeting 1 - Agent Architecture Over Current System")

st.graphviz_chart(
    """
    digraph {
        graph [rankdir=LR, bgcolor="transparent"];
        node [shape=box, style="rounded,filled", color="#334155", fillcolor="#F8FAFC", fontname="Arial"];
        edge [color="#64748B"];

        data [label="CoreStack BSON/CSV\nTelemetry"];
        ingest [label="Ingestion Agent"];
        synthetic [label="Synthetic Data Agent"];
        store [label="SQLite\nOperational Store", fillcolor="#E0F2FE"];
        forecast [label="Forecasting Agent"];
        recommend [label="Recommendation Agent"];
        apphealth [label="Application Health Agent"];
        pipeline [label="Pipeline Monitor Agent"];
        serverless [label="Serverless Action Agent"];
        dashboard [label="Agentic FinOps\nCommand Center", fillcolor="#DCFCE7"];
        query [label="Query Agent"];

        data -> ingest -> store;
        synthetic -> store;
        store -> forecast;
        store -> recommend;
        store -> apphealth;
        pipeline -> store;
        recommend -> serverless;
        store -> dashboard;
        dashboard -> query;
    }
    """
)

catalog_df = pd.DataFrame(AGENT_CATALOG)
st.dataframe(catalog_df, use_container_width=True, hide_index=True)

st.info(
    "Demo line for Vijay: Earlier this was script-based. Now every script becomes an operational agent with a specific responsibility and output."
)

st.divider()
st.subheader("Agent Control Center")

latest_runs = agent_runs.sort_values("created_at").groupby("agent_name").tail(1)
status_counts = agent_runs["status"].value_counts().to_dict() if not agent_runs.empty else {}

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Agent Runs", len(agent_runs))
c2.metric("Successful Runs", status_counts.get("success", 0))
c3.metric("Failed Runs", status_counts.get("failed", 0))
c4.metric("Active Agents", latest_runs["agent_name"].nunique())

card_cols = st.columns(3)
for idx, row in latest_runs.sort_values("agent_name").reset_index(drop=True).iterrows():
    with card_cols[idx % 3]:
        st.markdown(f"**{row['agent_name']}**")
        st.caption(row["summary"])
        st.metric("Records Processed", f"{int(row['records_processed']):,}")
        st.caption(f"Last run: {row['created_at']} | {row['duration_ms']} ms")

st.divider()
st.subheader("Meeting 2 - Agent Run History + Data Storage")

left, right = st.columns([1, 1])
with left:
    st.markdown("**Agent Run Timeline**")
    run_display = agent_runs[
        [
            "created_at",
            "agent_name",
            "status",
            "duration_ms",
            "records_processed",
            "summary",
        ]
    ].copy()
    st.dataframe(run_display, use_container_width=True, hide_index=True)

with right:
    st.markdown("**Storage View**")
    st.dataframe(storage_summary, use_container_width=True, hide_index=True)

    total_rows = int(storage_summary["rows_count"].sum()) if not storage_summary.empty else 0
    vm_count = int(vm_summary["resource_id"].nunique()) if not vm_summary.empty else 0
    app_tagged = int(
        storage_summary.loc[storage_summary["dataset"] == "vm_tags", "entity_count"].iloc[0]
    ) if "vm_tags" in set(storage_summary["dataset"]) else 0
    db_rows = int(
        storage_summary.loc[storage_summary["dataset"] == "db_metrics", "rows_count"].iloc[0]
    ) if "db_metrics" in set(storage_summary["dataset"]) else 0

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Stored Rows", f"{total_rows:,}")
    s2.metric("VMs", vm_count)
    s3.metric("Tagged VMs", app_tagged)
    s4.metric("DB Rows", f"{db_rows:,}")

st.divider()
st.subheader("Stored Insights")

tab1, tab2, tab3, tab4 = st.tabs(
    ["VM Metric Summary", "Recommendations Seed", "Pipeline Runs Seed", "Serverless Logs Seed"]
)

with tab1:
    st.dataframe(
        vm_summary[
            [
                "resource_id",
                "workload_class",
                "records",
                "mean_cpu",
                "max_cpu",
                "mean_network",
                "mean_memory",
                "mean_disk",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

with tab2:
    rec_counts = recommendations["action"].value_counts().reset_index()
    rec_counts.columns = ["Action", "VM Count"]
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.bar(rec_counts["Action"], rec_counts["VM Count"], color=["#2E86AB", "#F18F01", "#6A994E", "#C73E1D"][: len(rec_counts)])
    ax.set_ylabel("VM Count")
    ax.set_title("Recommendation Agent Output Seed")
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)
    st.dataframe(
        recommendations[
            ["vm", "action", "urgency", "avg_cpu_48h", "max_cpu_48h", "threshold", "reason"]
        ].head(20),
        use_container_width=True,
        hide_index=True,
    )

with tab3:
    by_day = pipeline_runs.copy()
    by_day["day"] = pd.to_datetime(by_day["created_at"]).dt.date
    daily = by_day.groupby(["day", "status"]).size().reset_index(name="runs")
    st.dataframe(pipeline_runs, use_container_width=True, hide_index=True)
    if not daily.empty:
        pivot = daily.pivot(index="day", columns="status", values="runs").fillna(0)
        st.bar_chart(pivot)

with tab4:
    if not actions.empty:
        action_display = actions.copy()
        action_display["payload_preview"] = action_display["payload"].apply(
            lambda value: json.dumps(json.loads(value), indent=0)[:180]
        )
        st.dataframe(
            action_display[
                [
                    "created_at",
                    "function_name",
                    "trigger_type",
                    "resource_id",
                    "application",
                    "status",
                    "duration_ms",
                    "payload_preview",
                    "response_message",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

st.divider()
st.caption(
    f"SQLite store: {DB_PATH} | Meetings 3-6 remain planned future work: query UX, full pipeline monitor, live-style serverless trigger flow, final command center polish."
)
