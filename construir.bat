@echo off
rem Doble clic para construir la version portatil (llama a construir.ps1)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0construir.ps1"
pause
