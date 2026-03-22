@echo off
setlocal

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

echo ==========================================
echo   PT Auto Downloader - Check
echo ==========================================
echo.

echo [1/3] Python syntax check...
python -m py_compile main.py web.py src\config.py src\mteam.py tests\test_regression.py
if errorlevel 1 goto :error
echo [OK] Python syntax check passed
echo.

echo [2/3] Frontend syntax check...
node --check static\js\api.js
if errorlevel 1 goto :error
node --check static\js\config.js
if errorlevel 1 goto :error
node --check static\js\history.js
if errorlevel 1 goto :error
node --check static\js\logs.js
if errorlevel 1 goto :error
node --check static\js\main.js
if errorlevel 1 goto :error
node --check static\js\panel-manager.js
if errorlevel 1 goto :error
node --check static\js\preview.js
if errorlevel 1 goto :error
node --check static\js\sites.js
if errorlevel 1 goto :error
echo [OK] Frontend syntax check passed
echo.

echo [3/3] Regression tests...
python -m unittest discover -s tests -p "test_*.py" -v
if errorlevel 1 goto :error
echo [OK] Regression tests passed
echo.

echo ==========================================
echo   All checks passed
echo ==========================================
exit /b 0

:error
echo.
echo [FAIL] Check failed
exit /b 1
