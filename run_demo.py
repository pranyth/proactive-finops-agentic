#!/usr/bin/env python3
"""Launch the self-contained AI FinOps demo."""

from __future__ import annotations

import argparse

from dotenv import load_dotenv
from ai_finops.storage import ensure_ai_demo_data


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run Agentic FinOps for managed AI services.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--regenerate", action="store_true", help="Rebuild reproducible synthetic AI usage data.")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("Run: pip install -r requirements.txt") from exc

    counts = ensure_ai_demo_data(force=args.regenerate)
    url = f"http://{args.host}:{args.port}"
    print("\nAgentic FinOps Governance for Cloud Infrastructure and AI Services")
    print("Ask one question; the agent routes it to VM utilization, AI-service cost, or both.")
    print(f"Generated AI usage events: {counts['ai_usage_events']:,}")
    print(f"Console:  {url}")
    print(f"API docs: {url}/docs")
    print("Try:      \"Where can we save the most money across the estate?\"")
    print("LLM: set OPENAI_API_KEY, ANTHROPIC_API_KEY, or OLLAMA_MODEL for live generated explanations")
    print("Press Ctrl+C to stop.\n")
    uvicorn.run("api.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
