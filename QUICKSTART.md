# Quick Start

```bash
git clone https://github.com/pranyth/proactive-finops-agentic.git
cd proactive-finops-agentic
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run_demo.py
```

Open http://127.0.0.1:8000.

Windows PowerShell activation:

```powershell
.\venv\Scripts\Activate.ps1
python run_demo.py
```

Use `python run_demo.py --regenerate` to rebuild the deterministic AI-service dataset.

## Try it

Ask these in the **Ask** box to see each routing path:

| Question | Goes to |
|---|---|
| `Which VMs can be shut down during low peak hours?` | Infrastructure |
| `Which VMs need scale up?` | Infrastructure |
| `Which applications are degraded?` | Infrastructure |
| `Which workloads can use a smaller model?` | AI services |
| `Where are we wasting input or output tokens?` | AI services |
| `Where can we save the most money across the estate?` | Both, in one ranked list |

Click any decision to open its evidence and the Lambda payload that would run on approval.
The **Infrastructure** tab has the CPU / memory / disk / network history per machine.

## Tests

```bash
python -m unittest discover -s tests
```
