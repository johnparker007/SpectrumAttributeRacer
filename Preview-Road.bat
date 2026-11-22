@echo off
cd /d "%~dp0"
python tools\preview_road.py
if errorlevel 1 pause
