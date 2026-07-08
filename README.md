# Agentic Proactive FinOps Governance

A production-style capstone prototype for CoreStack cloud telemetry. The main demo is a single **FinOps Analyst Agent**: the user asks a question, the agent identifies the current dataset, checks what data is required, calls internal tools, and returns recommendations with evidence.

## What This Project Shows

- One visible FinOps Analyst Agent entry point
- Dataset profiling and data requirement checks
- CoreStack Azure VM telemetry analysis
- Synthetic/augmented CPU, memory, disk, network, and DB metrics
- Hybrid enterprise context for inventory, cost, incidents, actions, and pipelines
- Data provenance labels for paper-safe reporting
- Dynamic threshold and Random Forest based forecasting support
- Application and database health correlation
- SQLite-backed operational audit trail
- Simulated Lambda/serverless action logs

## How The Agent Runs

```text
User Question + Dataset Context
        ->
FinOps Analyst Agent
        ->
Dataset Profiler + Requirement Checker
        ->
Internal Tools
  - Recommendation Tool
  - Low-Peak Shutdown Tool
  - Risk Ranking Tool
  - App/DB Health Tool
  - Pipeline/Action Audit Tools
        ->
Answer + Recommendations + Evidence + Next Action
```

Data ingestion and synthetic data generation are treated as **data pipelines/tools**, not as the main user-facing agent.

## Repository Contents

```text
agentic_command_center.py   # Main FinOps Analyst Agent command center
agents/analyst.py           # FinOpsAnalystAgent, DatasetProfiler, RequirementChecker
agents/                     # Shared contracts, storage, and operational audit bootstrap
dashboard.py                # VM forecasting and recommendation dashboard
DbDashboard.py              # Application and database intelligence dashboard
ingestion/                  # Normalized telemetry schema and adapters
tools/                      # Data extraction, augmentation, context generation, DB metric generation
docs/DATA_STRATEGY.md       # Paper-safe data strategy, provenance, and limitations
data/                       # Checked-in demo datasets needed to run dashboards
requirements.txt            # Python dependencies
```

## Data Included

The repo includes processed demo data:

```text
data/augmented_vm_metrics.csv
data/db_metrics.csv
data/vm_tags.json
data/vm_inventory.csv
data/cost_metrics.csv
data/incident_history.csv
data/action_history.csv
data/pipeline_runs.csv
data/data_provenance.csv
```

These files are enough to run the project demo. You do not need the raw `corestack_data/` BSON exports unless you want to regenerate the pipeline from the original CoreStack data.

For paper/demo wording, use:

> The prototype evaluates an agentic FinOps workflow using CoreStack-derived VM telemetry, deterministic synthetic enterprise context, and open-source cloud trace-inspired workload/failure patterns.

More details are in `docs/DATA_STRATEGY.md`.

## Clone and Run

### 1. Clone the repo

```bash
git clone https://github.com/pranyth/proactive-finops-agentic.git
cd proactive-finops-agentic
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

On Windows PowerShell, use:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the FinOps Analyst Agent command center

```bash
streamlit run agentic_command_center.py
```

This is the main Phase 3 demo. It shows:

- Ask-the-agent question panel
- Dataset identification
- Data requirement checklist
- Final answer and next action
- Recommendation/evidence table with cost, criticality, approval, incidents, and savings
- Hybrid data strategy and provenance table
- Architecture showing one visible agent and internal tools
- Operational audit trail below the main demo

Prepared demo questions:

- Which VMs can be shut down during low peak hours?
- Which VMs need scale down?
- Which VMs are risky?
- Which applications are degraded?
- Is DB data required for this question?
- Why is this VM recommended?

### 5. Run the VM forecasting dashboard

Open a second terminal, activate the venv again, then run:

```bash
streamlit run dashboard.py --server.port 8501
```

This shows fleet overview, recommendations, augmentation view, workload classes, predictive model performance, correlation analysis, and workflow execution logs.

### 6. Run the application/DB dashboard

Open another terminal, activate the venv again, then run:

```bash
streamlit run DbDashboard.py --server.port 8502
```

This shows application tags, DB metrics, VM-to-DB health impact, application health scorecard, and application-triggered function logs.

## Regenerate Hybrid Context

The checked-in data already works. To regenerate deterministic enterprise context from the current VM telemetry and tags:

```bash
python tools/generate_enterprise_context.py
```

This creates inventory, cost, incident, action, pipeline, and provenance datasets. It does not require raw CoreStack BSON.

## Recommended Vijay Demo Order

1. Open `agentic_command_center.py`.
2. Show the architecture: one FinOps Analyst Agent, internal tools, hybrid knowledge context, and data pipelines.
3. Ask: "Which VMs can be shut down during low peak hours?"
4. Show dataset profile, requirement check, answer, recommendations, savings, and evidence.
5. Open "Hybrid data strategy for demo and paper" and show provenance.
6. Ask: "Which applications are degraded?"
7. Explain that DB metrics are required for app health questions but not required for VM shutdown questions.
8. Show the operational audit trail only after the main agent answer.

## Where AI Comes In

- **ML AI:** dynamic thresholds and Random Forest forecasting in the VM dashboard.
- **Agentic AI:** dataset understanding, requirement checking, tool selection, and natural-language explanation.
- **Synthetic AI data:** generated memory, disk, network, DB, cost, incident, action, and pipeline data used to test workflows.
- **Open-source trace grounding:** public cloud trace research informs workload/failure patterns for synthetic context; raw trace rows are not copied into the project.

## Optional: Regenerate From Raw CoreStack Data

Only do this if you have the raw CoreStack BSON files in `corestack_data/`.

```bash
python tools/extract_vm_metrics.py
python tools/augment_metrics.py
python tools/extract_app_tags.py
python tools/generate_db_metrics.py
python tools/generate_enterprise_context.py
```

For normal clone-and-run demos, this step is not required.

## Project Theme

**Agentic Proactive FinOps Governance for CoreStack Telemetry**

A command center where one FinOps Analyst Agent identifies current data, checks what is required, answers operational questions, recommends cost/risk actions, and shows evidence for every recommendation.
