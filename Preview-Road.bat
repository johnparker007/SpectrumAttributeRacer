@echo off
cd /d "%~dp0"
python tools\preview_flat.py
if errorlevel 1 pause
