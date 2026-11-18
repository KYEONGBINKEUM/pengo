@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -m PyInstaller --noconfirm --onedir --console --name publisher-engine ^
  --add-data "templates;templates" --add-data "company-rules.json;." ^
  --collect-all psd_tools --collect-all tinycss2 publisher.py
