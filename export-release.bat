@echo off
setlocal

set SCRIPT_DIR=%~dp0

call :resolve_python
if errorlevel 1 exit /b 1

"%PYTHON_EXE%" %PYTHON_ARGS% "%SCRIPT_DIR%tools\export_release.py" %*
exit /b %ERRORLEVEL%

:resolve_python
if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%SCRIPT_DIR%.venv\Scripts\python.exe"
    set "PYTHON_ARGS="
    exit /b 0
)

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
    exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_EXE=python"
    set "PYTHON_ARGS="
    exit /b 0
)

echo [FAIL] Python 3 not found. Please install Python 3 or create .venv first.
exit /b 1
