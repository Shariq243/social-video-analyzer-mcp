@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\Install.ps1"
if errorlevel 1 pause
