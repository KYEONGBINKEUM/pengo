@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -c "import psd_tools, tinycss2" >nul 2>&1
if errorlevel 1 (
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 goto failed
)
.venv\Scripts\python.exe app.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo Setup or launch failed. Python 3.10+ and internet are needed on first launch.
pause
