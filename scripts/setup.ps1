python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python tools/generate_enterprise_context.py
python tools/generate_multicloud_demo_data.py

Write-Host ""
Write-Host "Setup complete. Start the demo with:"
Write-Host "  python run_demo.py"
