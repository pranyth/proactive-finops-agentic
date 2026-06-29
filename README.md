# Agentic Proactive FinOps Governance

A production-style capstone prototype for CoreStack cloud telemetry. The system turns VM and application telemetry into an agentic FinOps command center with stored agent runs, recommendations, pipeline history, and Lambda-style action logs.

## What This Project Shows

- CoreStack Azure VM telemetry analysis
- Synthetic/augmented CPU, memory, disk, network, and DB metrics
- Random Forest based VM spike prediction
- Dynamic threshold based recommendations
- Application and database health correlation
- Agentic FinOps command center with SQLite-backed run history
- Simulated Lambda/serverless action logs

## Repository Contents

```text
agentic_command_center.py   # Agent architecture + Meeting 1/2 command center
dashboard.py                # Main VM forecasting and recommendation dashboard
DbDashboard.py              # Application and database intelligence dashboard
agents/                     # Agent contracts, storage, and Meeting 2 bootstrap agents
ingestion/                  # Normalized telemetry schema and adapters
tools/                      # Data extraction, augmentation, app-tag extraction, DB metric generation
data/                       # Checked-in demo datasets needed to run dashboards
requirements.txt            # Python dependencies
```

## Data Included

The repo includes processed demo data:

```text
data/augmented_vm_metrics.csv
data/db_metrics.csv
data/vm_tags.json
```

These files are enough to run the project demo. You do not need the raw `corestack_data/` BSON exports unless you want to regenerate the pipeline from the original CoreStack data.

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

### 4. Run the Agentic FinOps command center

```bash
streamlit run agentic_command_center.py
```

This is the main Meeting 1/2 demo. It shows:

- Agent architecture diagram
- Agent responsibility table
- Agent Control Center
- Agent run history
- SQLite storage summary
- Seeded recommendations, pipeline runs, and Lambda-style action logs

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

## Recommended Demo Order

1. Start with `agentic_command_center.py` to explain the agentic project theme.
2. Show `dashboard.py` for VM forecasting and recommendations.
3. Show `DbDashboard.py` for application and DB health impact.

## Optional: Regenerate Data

Only do this if you have the raw CoreStack BSON files in `corestack_data/`.

```bash
python tools/extract_vm_metrics.py
python tools/augment_metrics.py
python tools/extract_app_tags.py
python tools/generate_db_metrics.py
```

For normal clone-and-run demos, this step is not required.

## Project Theme

**Agentic Proactive FinOps Governance for CoreStack Telemetry**

A command center where specialized agents ingest cloud telemetry, store operational context, generate missing metrics, predict VM risk, recommend cost actions, monitor pipeline health, and simulate Lambda-based remediation workflows.
