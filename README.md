# Agentic Proactive FinOps Governance

A production-style capstone prototype for CoreStack cloud telemetry. The main demo is now a **FastAPI-backed FinOps Analyst Agent platform**: the browser calls APIs, the API gateway calls the agent, and the UI only visualizes returned system state.

## What This Project Shows

- FastAPI API gateway for the visible FinOps Analyst Agent
- Non-Streamlit web command center served by the API
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

## How The Platform Runs

```text
Browser Command Center
        ->
FastAPI API Gateway
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
        ->
Browser visualizes state
```

Data ingestion and synthetic data generation are treated as **data pipelines/tools**, not as the main user-facing agent. The Streamlit screens remain as backup dashboards, but the primary demo path is API-first.

## Repository Contents

```text
api/main.py                 # FastAPI API gateway and endpoints
frontend/                   # Non-Streamlit command center served by FastAPI
agentic_command_center.py   # Legacy Streamlit command center fallback
agents/analyst.py           # FinOpsAnalystAgent, DatasetProfiler, RequirementChecker
agents/                     # Shared contracts, storage, and operational audit bootstrap
dashboard.py                # Legacy VM forecasting Streamlit dashboard
DbDashboard.py              # Legacy application/DB Streamlit dashboard
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

### 4. Run the API-backed command center

```bash
uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

Open:

```text
http://127.0.0.1:8000
```

API docs:

```text
http://127.0.0.1:8000/docs
```

The command center shows:

- Ask-the-agent question panel
- FastAPI health and API-backed query execution
- Dataset identification
- Data requirement checklist
- Final answer and next action
- Recommendation/evidence table with cost, criticality, approval, incidents, and savings
- Hybrid data profile and source mix
- Architecture showing browser -> API -> agent -> tools
- Operational audit trail below the main agent answer

Prepared demo questions:

- Which VMs can be shut down during low peak hours?
- Which VMs need scale down?
- Which VMs are risky?
- Which applications are degraded?
- Is DB data required for this question?
- Why is this VM recommended?

## Useful API Endpoints

```text
GET  /api/health
GET  /api/questions
GET  /api/dataset-profile
POST /api/query
GET  /api/architecture
GET  /api/operational/summary
GET  /api/operational/audit
POST /api/operational/refresh
```

Example query:

```bash
curl -X POST http://127.0.0.1:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question":"Which VMs can be shut down during low peak hours?","time_window":"latest_48h","cloud":"azure"}'
```

## Optional Legacy Streamlit Dashboards

The project still includes Streamlit dashboards as fallback views.

```bash
streamlit run agentic_command_center.py --server.port 8506
streamlit run dashboard.py --server.port 8501
streamlit run DbDashboard.py --server.port 8502
```

Use the FastAPI command center as the main Vijay demo because it better matches a production platform architecture.

## Regenerate Hybrid Context

The checked-in data already works. To regenerate deterministic enterprise context from the current VM telemetry and tags:

```bash
python tools/generate_enterprise_context.py
```

This creates inventory, cost, incident, action, pipeline, and provenance datasets. It does not require raw CoreStack BSON.

## Recommended Vijay Demo Order

1. Run `uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload`.
2. Open `http://127.0.0.1:8000`.
3. Show the architecture: browser dashboard, FastAPI API gateway, one FinOps Analyst Agent, internal tools, hybrid knowledge context, and data pipelines.
4. Ask: "Which VMs can be shut down during low peak hours?"
5. Show dataset profile, requirement check, answer, recommendations, savings, and evidence.
6. Show the source mix/provenance section for paper-safe claims.
7. Ask: "Which applications are degraded?"
8. Open `http://127.0.0.1:8000/docs` to show the API contract.
9. Show the operational audit trail only after the main agent answer.

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

A command center where the browser visualizes an API-backed FinOps Analyst Agent that identifies current data, checks what is required, answers operational questions, recommends cost/risk actions, and shows evidence for every recommendation.
