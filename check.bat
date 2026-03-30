@echo off
setlocal

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

call :resolve_python
if errorlevel 1 goto :error

echo [PYTHON] Using: %PYTHON_LABEL%
"%PYTHON_EXE%" %PYTHON_ARGS% tools\run_checks.py
if errorlevel 1 goto :error
exit /b 0

:resolve_python
if exist "%ROOT_DIR%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%ROOT_DIR%.venv\Scripts\python.exe"
    set "PYTHON_ARGS="
    set "PYTHON_LABEL=%ROOT_DIR%.venv\Scripts\python.exe"
    exit /b 0
)

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
    set "PYTHON_LABEL=py -3"
    exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_EXE=python"
    set "PYTHON_ARGS="
    set "PYTHON_LABEL=python"
    exit /b 0
)

echo [FAIL] Python 3 not found. Please install Python 3 or create .venv first.
exit /b 1

:error
echo.
echo [FAIL] Check failed
exit /b 1
