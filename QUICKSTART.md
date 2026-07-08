# Quickstart

This is the fastest way for a friend or evaluator to run the demo locally.

## Main Use Case

A FinOps or cloud-ops operator asks:

> Which multi-cloud VMs can be safely shut down or rightsized, why, what is the business risk, and what serverless action would be triggered?

The dashboard then shows the recommendation, evidence, data requirements, provider/source profile, event trail, and action log.

## Clone

```bash
git clone https://github.com/pranyth/proactive-finops-agentic.git
cd proactive-finops-agentic
```

## macOS/Linux/WSL Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run_demo.py
```

Or use the setup script:

```bash
bash scripts/setup.sh
python run_demo.py
```

## Windows PowerShell Setup

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run_demo.py
```

Or use the setup script:

```powershell
.\scripts\setup.ps1
python run_demo.py
```

## Open The Demo

```text
http://127.0.0.1:8000
```

If port 8000 is busy:

```bash
python run_demo.py --port 8010
```

## Vijay Demo Flow

1. Show the top Main Use Case panel.
2. Click **Run Event Demo** to show telemetry events flowing through the Coordinator Agent.
3. Ask **Which VMs can be shut down during low peak hours?**
4. Show recommendations, evidence, savings, risk, provider profile, and action trail.
5. Ask **Which applications are degraded?** to show when DB/application data becomes required.
6. Open `/docs` to show the API contract.

## Raw CoreStack Data

Raw `corestack_data/` files are not required for the normal demo. The checked-in processed and synthetic datasets are enough for clone-and-run evaluation.
