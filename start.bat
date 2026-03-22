@echo off
echo ==========================================
echo   PT Auto Downloader - Starting
echo ==========================================
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
start /B python main.py -d
set MAIN_PID=%ERRORLEVEL%

timeout /t 2 /nobreak >nul

echo [OK] Daemon started

echo.

REM 启动 Web 界面
echo [2/2] Starting web interface (web.py)...
start /B python web.py
set WEB_PID=%ERRORLEVEL%

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
