@echo off
setlocal

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

call :resolve_python
if errorlevel 1 goto :error

set "CONFIG_FILE=%AUTO_PT_CONFIG_FILE%"
if not defined CONFIG_FILE set "CONFIG_FILE=%ROOT_DIR%config.yaml"
if not exist "%ROOT_DIR%data" mkdir "%ROOT_DIR%data" >nul 2>nul
if not exist "%ROOT_DIR%logs" mkdir "%ROOT_DIR%logs" >nul 2>nul
if not exist "%CONFIG_FILE%" (
    if exist "%ROOT_DIR%config.yaml.example" (
        copy /Y "%ROOT_DIR%config.yaml.example" "%CONFIG_FILE%" >nul
        echo [OK] Default config created: %CONFIG_FILE%
    )
)

echo ==========================================
echo   PT Auto Downloader - Starting
echo ==========================================
echo.
echo [PYTHON] Using: %PYTHON_LABEL%
echo [CONFIG] File: %CONFIG_FILE%
echo.

REM ==========================================
REM 环境变量配置（可选，用于敏感信息）
REM 如不设置，则从 config.yaml 读取
REM ==========================================
REM set QB_HOST=http://127.0.0.1:8585
REM set QB_USERNAME=admin
REM set QB_PASSWORD=your_password_here
REM set APP_SECRET=your_app_secret_here
REM set SITE_mteam_PASSKEY=your_mteam_passkey
REM set SITE_hdtime_PASSKEY=your_hdtime_passkey
echo [ENV] Environment variables loaded (if set)
echo.

REM 启动主程序（守护进程）
echo [1/2] Starting daemon mode (main.py -d)...
start /B "" "%PYTHON_EXE%" %PYTHON_ARGS% main.py -d

timeout /t 2 /nobreak >nul

echo [OK] Daemon started

echo.

REM 启动 Web 界面
echo [2/2] Starting web interface (web.py)...
start /B "" "%PYTHON_EXE%" %PYTHON_ARGS% web.py

timeout /t 2 /nobreak >nul

echo [OK] Web interface started

echo.
echo ==========================================
echo   Web UI: http://localhost:5000
echo ==========================================
echo.
echo Press Ctrl+C to stop (note: background processes will continue)
echo To stop manually, close the Python processes in Task Manager
echo.
echo ==========================================
echo   Environment Variables Help
echo ==========================================
echo   QB_HOST       - qBittorrent WebUI address
echo   QB_USERNAME  - qBittorrent username  
echo   QB_PASSWORD  - qBittorrent password
echo   APP_SECRET   - API authentication key
echo   SITE_xxx_PASSKEY - Passkey for site xxx
echo   Example: set QB_PASSWORD=my_pass
echo.

pause
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
echo [FAIL] Startup aborted
exit /b 1
