#!/bin/bash

echo "=========================================="
echo "  PT Auto Downloader - Starting"
echo "=========================================="
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
python main.py -d &
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
python web.py &
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
