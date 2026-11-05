@echo off
rem Offline install. Messages are in tools\offline_install.ps1 (UTF-8) so Korean is shown correctly.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\offline_install.ps1"
pause
