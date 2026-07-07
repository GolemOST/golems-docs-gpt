@echo off
rem Golem's Docs GPT launcher - seeds the demo corpus (idempotent) and starts
rem the local server. Local-only: binds 127.0.0.1, nothing exposed to your network.
cd /d "%~dp0"
echo [DOCS GPT] Seeding demo corpus (skips if already loaded)...
python seed_demo.py
echo [DOCS GPT] Starting server on http://127.0.0.1:8756 ...
start "" http://127.0.0.1:8756
python server.py
pause
