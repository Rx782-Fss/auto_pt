#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

resolve_python() {
    if [ -x "${ROOT_DIR}/.venv/bin/python" ]; then
        echo "${ROOT_DIR}/.venv/bin/python"
        return 0
    fi
    if command -v python3 >/dev/null 2>&1; then
        command -v python3
        return 0
    fi
    if command -v python >/dev/null 2>&1; then
        command -v python
        return 0
    fi
    return 1
}

PYTHON_CMD="$(resolve_python || true)"
if [ -z "${PYTHON_CMD}" ]; then
    echo "[FAIL] 未找到可用的 Python 3 解释器。"
    echo "请先安装 Python 3，或在项目根目录创建 .venv 虚拟环境。"
    exit 1
fi

CONFIG_FILE="${AUTO_PT_CONFIG_FILE:-${ROOT_DIR}/config.yaml}"
if [[ "${CONFIG_FILE}" != /* ]]; then
    CONFIG_FILE="${ROOT_DIR}/${CONFIG_FILE}"
fi
export AUTO_PT_CONFIG_FILE="${CONFIG_FILE}"

mkdir -p "${ROOT_DIR}/data" "${ROOT_DIR}/logs" "$(dirname "${CONFIG_FILE}")"
if [ ! -f "${CONFIG_FILE}" ] && [ -f "${ROOT_DIR}/config.yaml.example" ]; then
    cp "${ROOT_DIR}/config.yaml.example" "${CONFIG_FILE}"
    echo "✓ 已自动生成默认配置：${CONFIG_FILE}"
fi

echo "=========================================="
echo "  PT Auto Downloader - Starting"
echo "=========================================="
echo ""
echo "[PYTHON] Using: ${PYTHON_CMD}"
echo "[CONFIG] File: ${AUTO_PT_CONFIG_FILE}"
echo ""

# ==========================================
# 环境变量配置（可选，用于敏感信息）
# 如不设置，则从 config.yaml 读取
# ==========================================
# export QB_HOST=http://127.0.0.1:8585
# export QB_USERNAME=admin
# export QB_PASSWORD=your_password_here
# export APP_SECRET=your_app_secret_here
# export SITE_mteam_PASSKEY=your_mteam_passkey
# export SITE_hdtime_PASSKEY=your_hdtime_passkey
echo "[ENV] Environment variables loaded (if set)"
echo ""

# 启动主程序（守护进程）
echo "[1/2] Starting daemon mode (main.py -d)..."
"${PYTHON_CMD}" main.py -d &
MAIN_PID=$!

# 等待一下确保主程序启动成功
sleep 2

# 使用 kill -0 检查进程是否存在
if kill -0 $MAIN_PID 2>/dev/null; then
    echo "✓ Daemon started (PID: $MAIN_PID)"
else
    echo "✗ Daemon failed to start"
    exit 1
fi

echo ""

# 启动Web界面
echo "[2/2] Starting web interface (web.py)..."
"${PYTHON_CMD}" web.py &
WEB_PID=$!

sleep 2

if kill -0 $WEB_PID 2>/dev/null; then
    echo "✓ Web interface started (PID: $WEB_PID)"
    echo ""
    echo "=========================================="
    echo "  Web UI: http://localhost:5000"
    echo "  Daemon PID: $MAIN_PID"
    echo "  Web PID: $WEB_PID"
    echo "=========================================="
else
    echo "✗ Web interface failed to start"
    kill $MAIN_PID 2>/dev/null
    exit 1
fi

# 捕获退出信号
function cleanup() {
    echo ""
    echo "Stopping services..."
    kill $MAIN_PID $WEB_PID 2>/dev/null
    wait $MAIN_PID $WEB_PID 2>/dev/null
    echo "All services stopped"
    exit 0
}

trap cleanup SIGINT SIGTERM

# 等待所有进程
wait $MAIN_PID $WEB_PID
