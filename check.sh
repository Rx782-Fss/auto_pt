#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

echo "=========================================="
echo "  PT Auto Downloader - Check"
echo "=========================================="
echo ""

echo "[1/3] Python syntax check..."
python -m py_compile main.py web.py src/config.py src/mteam.py tests/test_regression.py
echo "[OK] Python syntax check passed"
echo ""

echo "[2/3] Frontend syntax check..."
node --check static/js/api.js
node --check static/js/config.js
node --check static/js/history.js
node --check static/js/logs.js
node --check static/js/main.js
node --check static/js/panel-manager.js
node --check static/js/preview.js
node --check static/js/sites.js
echo "[OK] Frontend syntax check passed"
echo ""

echo "[3/3] Regression tests..."
python -m unittest discover -s tests -p "test_*.py" -v
echo "[OK] Regression tests passed"
echo ""

echo "=========================================="
echo "  All checks passed"
echo "=========================================="
