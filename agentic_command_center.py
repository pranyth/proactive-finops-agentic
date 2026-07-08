import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from agents.analyst import FinOpsAnalystAgent, PREPARED_QUESTIONS
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


def show_status_table(requirements: list[dict[str, str]]) -> None:
    status_df = pd.DataFrame(requirements)
    st.dataframe(status_df, use_container_width=True, hide_index=True)


def show_dataset_profile(profile: dict) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("VM Rows", f"{profile['vm_rows']:,}")
    col2.metric("VMs", profile["vm_count"])
    col3.metric("DB Rows", f"{profile['db_rows']:,}")
    col4.metric("Tagged VMs", profile["application_tagged_vms"])

    profile_rows = [
        {"Field": "Dataset", "Value": profile["dataset_name"]},
        {"Field": "Types", "Value": ", ".join(profile["dataset_types"])},
        {"Field": "Time Range", "Value": f"{profile['time_range']['start']} -> {profile['time_range']['end']}"},
        {"Field": "Applications", "Value": ", ".join(profile["applications"])},
        {"Field": "Raw CoreStack BSON", "Value": profile["raw_corestack_bson"]},
        {"Field": "Raw BSON Required", "Value": profile["raw_corestack_required"]},
    ]
    st.dataframe(pd.DataFrame(profile_rows), use_container_width=True, hide_index=True)


def show_recommendations(answer_dict: dict) -> None:
    recs = answer_dict.get("recommendations", [])
    if not recs:
        st.info("The agent did not return a table for this question.")
        return

    rec_df = pd.DataFrame(recs)
    st.dataframe(rec_df, use_container_width=True, hide_index=True)

    numeric_cols = [col for col in ["Avg CPU 48h", "Avg Network 48h", "Health Score", "Risk Score", "Confidence"] if col in rec_df.columns]
    label_col = "VM" if "VM" in rec_df.columns else ("Application" if "Application" in rec_df.columns else None)
    if label_col and numeric_cols:
        plot_df = rec_df.head(12).set_index(label_col)[numeric_cols[:2]]
        st.bar_chart(plot_df)


def show_architecture() -> None:
    st.graphviz_chart(
        """
        digraph {
            graph [rankdir=LR, bgcolor="transparent"];
            node [shape=box, style="rounded,filled", color="#334155", fillcolor="#F8FAFC", fontname="Arial"];
            edge [color="#64748B"];

            user [label="User Question\n+ Dataset Context", fillcolor="#FEF3C7"];
            agent [label="FinOps Analyst Agent\n(single visible entry point)", fillcolor="#DCFCE7"];
            profiler [label="Dataset Profiler\nidentifies current data"];
            checker [label="Requirement Checker\nrequired / optional / missing"];
            tools [label="Internal Tools\nrecommendation, risk, DB health, pipeline, actions", fillcolor="#E0F2FE"];
            answer [label="Answer + Recommendations\n+ Evidence + Next Action", fillcolor="#FCE7F3"];
            pipelines [label="Data Pipelines\ningestion + synthetic generation", fillcolor="#F1F5F9"];
            store [label="Demo Data Store\nCSV + SQLite audit", fillcolor="#E0F2FE"];

            pipelines -> store;
            user -> agent;
            store -> profiler;
            agent -> profiler -> checker -> tools -> answer;
            store -> tools;
        }
        """
    )


ensure_demo_data(force=False)
analyst = FinOpsAnalystAgent()

st.title("Agentic Proactive FinOps Governance")
st.markdown("**One visible FinOps Analyst Agent. Data pipelines prepare data; the agent answers questions and chooses internal tools.**")
st.caption("Phase 3 demo: dataset identification, data requirement checks, recommendations, evidence, and architecture for Vijay.")

st.divider()
st.subheader("Ask the FinOps Agent")

left, right = st.columns([2, 1])
with left:
    selected_question = st.selectbox("Prepared Vijay demo questions", PREPARED_QUESTIONS)
    custom_question = st.text_input("Optional custom question", placeholder="Example: Which VMs are risky?")
with right:
    time_window = st.selectbox("Time window", ["latest_48h", "latest_7d", "full_dataset"], index=0)
    cloud = st.selectbox("Cloud", ["azure"], index=0)
    run_clicked = st.button("Run FinOps Analyst Agent", type="primary")

question = custom_question.strip() or selected_question
context = {"time_window": time_window, "cloud": cloud}

if run_clicked or "last_agent_answer" not in st.session_state or st.session_state.get("last_question") != question:
    st.session_state["last_agent_answer"] = analyst.run(question, context).to_dict()
    st.session_state["last_question"] = question

answer = st.session_state["last_agent_answer"]

st.divider()
st.subheader("Agent Response")

resp_left, resp_right = st.columns([2, 1])
with resp_left:
    st.success(answer["answer"])
    st.markdown(f"**Next action:** {answer['next_action']}")
with resp_right:
    st.metric("Detected Intent", answer["intent"])
    st.markdown("**Internal tools used**")
    st.write(", ".join(answer["tools_used"]))

st.divider()
st.subheader("Data Requirement Check")
show_status_table(answer["requirement_check"])

st.divider()
st.subheader("Recommendations + Evidence")
show_recommendations(answer)

with st.expander("Dataset profile: how the agent identifies current data", expanded=True):
    show_dataset_profile(answer["dataset_profile"])

with st.expander("Where is AI coming in?", expanded=True):
    ai_rows = [
        {"Layer": "ML AI", "What it does": "Uses dynamic thresholds and Random Forest forecasting in the VM dashboard to detect/predict risk."},
        {"Layer": "Agentic AI", "What it does": "Profiles data, checks requirements, routes the question to the right internal tool, and explains the answer."},
        {"Layer": "Synthetic AI Data", "What it does": "Generated memory, disk, network, and DB signals make incomplete CoreStack data usable for prediction demos."},
    ]
    st.dataframe(pd.DataFrame(ai_rows), use_container_width=True, hide_index=True)

st.divider()
st.subheader("Architecture: How Everything Runs")
show_architecture()

catalog_df = pd.DataFrame(AGENT_CATALOG)
st.dataframe(catalog_df, use_container_width=True, hide_index=True)

st.info(
    "Demo line for Vijay: The user does not call each level. The user asks one FinOps Analyst Agent; it identifies the dataset, checks what is required, calls internal tools, and returns an answer with evidence."
)

st.divider()
st.subheader("Operational Audit Trail")
st.caption("Meeting 1/2 storage and run history remain for traceability, but they are not the main user-facing agent.")

if st.button("Refresh Operational Demo Runs"):
    created = ensure_demo_data(force=True)
    st.success(f"Regenerated operational audit data and created {created} new run records.")
    st.rerun()

agent_runs = load_table("SELECT * FROM agent_runs ORDER BY created_at DESC")
storage_summary = load_table("SELECT * FROM data_storage_summary ORDER BY dataset")
vm_summary = load_table("SELECT * FROM vm_metric_summary ORDER BY max_cpu DESC")
recommendations = load_table("SELECT * FROM recommendations ORDER BY urgency DESC")
pipeline_runs = load_table("SELECT * FROM pipeline_runs ORDER BY created_at DESC")
actions = load_table("SELECT * FROM serverless_action_logs ORDER BY created_at DESC")

latest_runs = agent_runs.sort_values("created_at").groupby("agent_name").tail(1)
status_counts = agent_runs["status"].value_counts().to_dict() if not agent_runs.empty else {}

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Tool/Pipeline Runs", len(agent_runs))
c2.metric("Successful Runs", status_counts.get("success", 0))
c3.metric("Failed Runs", status_counts.get("failed", 0))
c4.metric("Tracked Components", latest_runs["agent_name"].nunique())

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Run Timeline", "Storage", "VM Summary", "Pipeline Runs", "Serverless Logs"
])

with tab1:
    st.dataframe(
        agent_runs[["created_at", "agent_name", "status", "duration_ms", "records_processed", "summary"]],
        use_container_width=True,
        hide_index=True,
    )

with tab2:
    st.dataframe(storage_summary, use_container_width=True, hide_index=True)

with tab3:
    st.dataframe(
        vm_summary[["resource_id", "workload_class", "records", "mean_cpu", "max_cpu", "mean_network", "mean_memory", "mean_disk"]],
        use_container_width=True,
        hide_index=True,
    )

with tab4:
    by_day = pipeline_runs.copy()
    if not by_day.empty:
        by_day["day"] = pd.to_datetime(by_day["created_at"]).dt.date
        daily = by_day.groupby(["day", "status"]).size().reset_index(name="runs")
        pivot = daily.pivot(index="day", columns="status", values="runs").fillna(0)
        st.bar_chart(pivot)
    st.dataframe(pipeline_runs, use_container_width=True, hide_index=True)

with tab5:
    if not actions.empty:
        action_display = actions.copy()
        action_display["payload_preview"] = action_display["payload"].apply(
            lambda value: json.dumps(json.loads(value), indent=0)[:180]
        )
        st.dataframe(
            action_display[[
                "created_at", "function_name", "trigger_type", "resource_id", "application",
                "status", "duration_ms", "payload_preview", "response_message",
            ]],
            use_container_width=True,
            hide_index=True,
        )

st.divider()
st.caption(f"SQLite audit store: {DB_PATH} | Phase 3: one FinOps Analyst Agent with internal tools and clear entry/exit points.")