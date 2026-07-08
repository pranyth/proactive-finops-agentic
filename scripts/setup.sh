#!/usr/bin/env bash
set -euo pipefail

python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python tools/generate_enterprise_context.py
python tools/generate_multicloud_demo_data.py

echo ""
echo "Setup complete. Start the demo with:"
echo "  python run_demo.py"
