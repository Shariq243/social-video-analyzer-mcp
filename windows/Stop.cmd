@echo off
"%~dp0..\.venv\Scripts\python.exe" "%~dp0launcher.py" stop
if errorlevel 1 pause
