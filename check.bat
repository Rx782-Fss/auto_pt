@echo off
setlocal

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

python tools\run_checks.py
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo [FAIL] Check failed
exit /b 1
