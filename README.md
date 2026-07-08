# Agentic Proactive FinOps Governance for Multi-Cloud Telemetry

A production-style capstone prototype for multi-cloud telemetry. The main demo is now a **FastAPI-backed, event-driven FinOps Analyst Agent platform**: telemetry/failure events enter an API gateway, a Coordinator Agent routes work through internal tools, and the browser only visualizes returned system state.

## What This Project Shows

- FastAPI API gateway for the visible FinOps Analyst Agent
- SQLite-backed event bus with pending/processed/failed event states
- Coordinator Agent and background worker for event-driven orchestration
- Non-Streamlit web command center served by the API
- One visible FinOps Analyst Agent entry point
- Dataset profiling and data requirement checks
- Multi-cloud telemetry analysis across Azure, AWS, and GCP demo providers
- CoreStack-derived Azure telemetry as the first real provider source
- Open-source workload trace pattern references for AWS/GCP synthetic telemetry
- Synthetic/augmented CPU, memory, disk, network, and DB metrics
- Hybrid enterprise context for inventory, cost, incidents, actions, and pipelines
- Data provenance labels for paper-safe reporting
- Dynamic threshold and Random Forest based forecasting support
- Application and database health correlation
- SQLite-backed operational audit trail
- Simulated Lambda/serverless action logs

## How The Platform Runs

```text
Telemetry/Event API
        ->
SQLite Event Bus
        ->
Coordinator Agent + Background Worker
        ->
Internal Tools
  - Dataset Profiler
  - Requirement Checker
  - Recommendation Tool
  - Low-Peak Shutdown Tool
  - Risk Ranking Tool
  - App/DB Health Tool
  - Serverless Action Router
        ->
Stored events + recommendations + action logs
        ->
Browser visualizes state

Direct user questions still use:

Browser Command Center -> FastAPI /api/query -> FinOps Analyst Agent -> Answer
```

Data ingestion and synthetic data generation are treated as **data pipelines/tools**, not as the main user-facing agent. The Streamlit screens remain as backup dashboards, but the primary demo path is API-first.

## Repository Contents

```text
api/main.py                 # FastAPI API gateway, event endpoints, and coordinator worker startup
frontend/                   # Non-Streamlit command center with agent query, event stream, and audit views
agentic_command_center.py   # Legacy Streamlit command center fallback
agents/analyst.py           # FinOpsAnalystAgent, DatasetProfiler, RequirementChecker
agents/                     # Shared contracts, storage, and operational audit bootstrap
dashboard.py                # Legacy VM forecasting Streamlit dashboard
DbDashboard.py              # Legacy application/DB Streamlit dashboard
ingestion/                  # Provider-neutral telemetry schema and CoreStack/AWS/Azure/GCP adapters
tools/                      # Data extraction, augmentation, context generation, multi-cloud data generation
docs/DATA_STRATEGY.md       # Paper-safe data strategy, provenance, and limitations
docs/MULTICLOUD_ARCHITECTURE.md # Provider-neutral schema and adapter architecture
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
data/open_trace_patterns.csv
data/multicloud_vm_metrics.csv
```

These files are enough to run the project demo. You do not need the raw `corestack_data/` BSON exports unless you want to regenerate the pipeline from the original CoreStack data.

For paper/demo wording, use:

> The prototype evaluates an agentic FinOps workflow using CoreStack-derived Azure telemetry, deterministic synthetic enterprise context, and AWS/GCP telemetry generated from cited open-source cloud workload trace patterns.

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

- Event-driven orchestration panel with Coordinator Agent status
- Event stream for telemetry, forecast, recommendation, pipeline failure, and serverless action events

- Ask-the-agent question panel
- FastAPI health and API-backed query execution
- Dataset identification
- Data requirement checklist
- Final answer and next action
- Recommendation/evidence table with cost, criticality, approval, incidents, and savings
- Hybrid data profile and source mix
- Architecture showing telemetry events -> event bus -> coordinator -> internal tools -> stored results
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
GET  /api/events
POST /api/events/telemetry
POST /api/events/pipeline-failure
POST /api/events/demo-run
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
python tools/generate_multicloud_demo_data.py
```

This creates inventory, cost, incident, action, pipeline, multi-cloud telemetry, open-trace pattern, and provenance datasets. It does not require raw CoreStack BSON.

## Recommended Vijay Demo Order

1. Run `uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload`.
2. Open `http://127.0.0.1:8000`.
3. Show the architecture: event API, SQLite Event Bus, Coordinator Agent, internal tools, hybrid knowledge context, and stored results.
4. Click **Run Event Demo** and show `telemetry.received -> forecast.completed -> recommendation.created -> serverless.action.created`.
5. Show Coordinator State and Event Stream.
6. Ask: "Which VMs can be shut down during low peak hours?"
7. Show dataset profile, requirement check, answer, recommendations, savings, and evidence.
8. Show the source mix/provenance section for paper-safe claims.
9. Ask: "Which applications are degraded?"
10. Open `http://127.0.0.1:8000/docs` to show the API contract.
11. Show the operational audit trail only after the main agent answer.

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
python tools/generate_multicloud_demo_data.py
```

For normal clone-and-run demos, this step is not required.

## Project Theme

**Agentic Proactive FinOps Governance for Multi-Cloud Telemetry**

A command center where the browser visualizes an API-backed multi-cloud FinOps Analyst Agent that identifies current data, checks what is required, answers operational questions, recommends cost/risk actions, and shows evidence for every recommendation.
