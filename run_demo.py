#!/usr/bin/env python3
"""Friendly local launcher for the Agentic FinOps demo."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REQUIRED_DEMO_FILES = [
    ROOT / "data" / "augmented_vm_metrics.csv",
    ROOT / "data" / "db_metrics.csv",
    ROOT / "data" / "vm_tags.json",
]
ENTERPRISE_FILES = [
    ROOT / "data" / "vm_inventory.csv",
    ROOT / "data" / "cost_metrics.csv",
    ROOT / "data" / "incident_history.csv",
    ROOT / "data" / "pipeline_runs.csv",
]
MULTICLOUD_FILES = [
    ROOT / "data" / "multicloud_vm_metrics.csv",
    ROOT / "data" / "open_trace_patterns.csv",
]


def run_script(relative_path: str) -> None:
    script = ROOT / relative_path
    print(f"[setup] generating {script.name} outputs...")
    subprocess.check_call([sys.executable, str(script)], cwd=str(ROOT))


def ensure_demo_data(skip_generate: bool = False) -> None:
    missing_required = [path for path in REQUIRED_DEMO_FILES if not path.exists()]
    if missing_required:
        missing = "\n".join(f"  - {path.relative_to(ROOT)}" for path in missing_required)
        raise SystemExit(
            "Missing base demo data:\n"
            f"{missing}\n\n"
            "Clone the full repo data files, or regenerate from raw CoreStack exports before running the demo."
        )

    if skip_generate:
        return

    if any(not path.exists() for path in ENTERPRISE_FILES):
        run_script("tools/generate_enterprise_context.py")

    if any(not path.exists() for path in MULTICLOUD_FILES):
        run_script("tools/generate_multicloud_demo_data.py")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Agentic FinOps FastAPI demo.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind. Default: 127.0.0.1")
    parser.add_argument("--port", default=8000, type=int, help="Port to bind. Default: 8000")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload for development.")
    parser.add_argument("--skip-generate", action="store_true", help="Do not auto-generate missing derived demo files.")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: uvicorn.\n"
            "Run: pip install -r requirements.txt\n"
            "Then start again with: python run_demo.py"
        ) from exc

    ensure_demo_data(skip_generate=args.skip_generate)

    dashboard_url = f"http://{args.host}:{args.port}"
    print("\nAgentic Proactive FinOps Governance for Multi-Cloud Telemetry")
    print("Main use case: find safe shutdown/rightsizing opportunities, explain the evidence, and show the action trail.")
    print(f"Dashboard: {dashboard_url}")
    print(f"API docs:  {dashboard_url}/docs")
    print("Press Ctrl+C to stop.\n")

    uvicorn.run("api.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
