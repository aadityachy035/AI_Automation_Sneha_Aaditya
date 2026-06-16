@echo off
REM ─── VHAL UCL Log Viewer Launcher ───────────────────────────────────────────
REM Always uses the venv Python which has matplotlib, torch, fastapi etc.
cd /d "%~dp0"
echo Starting VHAL Viewer...
"venv\Scripts\python.exe" vhal_viewer.py
