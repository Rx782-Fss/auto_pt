#!/bin/bash
# Docker 容器启动脚本 - 同时运行守护进程 + Web 界面
# 适用于 Linux/Docker 环境

set -e

echo "=========================================="
echo "  PT Auto Downloader - Starting"
echo "=========================================="
echo ""

# 兼容文件挂载与目录挂载两种配置方式
CONFIG_FILE="${AUTO_PT_CONFIG_FILE:-/app/config.yaml}"
if [ -d "$CONFIG_FILE" ]; then
    CONFIG_FILE="$CONFIG_FILE/config.yaml"
fi
export AUTO_PT_CONFIG_FILE="$CONFIG_FILE"

KEY_FILE="${AUTO_PT_KEY_FILE:-/app/data/auto_pt.key}"
export AUTO_PT_KEY_FILE="$KEY_FILE"

# 确保目录存在
mkdir -p "$(dirname "$CONFIG_FILE")" "$(dirname "$KEY_FILE")" /app/logs /app/data

# 首次启动时自动生成配置文件
if [ ! -f "$CONFIG_FILE" ]; then
    if [ -f /app/config.yaml.example ]; then
        cp /app/config.yaml.example "$CONFIG_FILE"
        echo "✓ 已生成默认配置：$CONFIG_FILE"
    else
        echo "✗ 未找到示例配置 /app/config.yaml.example"
        exit 1
    fi
fi

# 如果检测到旧版示例配置或首次生成的默认空模板，则自动升级为发布版模板
if [ -f /app/config.yaml.example ]; then
    if grep -q "your-pt-site1.com\|your-pt-site2.com" "$CONFIG_FILE" 2>/dev/null; then
        cp /app/config.yaml.example "$CONFIG_FILE"
        echo "✓ 已将旧示例配置升级为发布版模板：$CONFIG_FILE"
    elif grep -q "^[[:space:]]*pt_sites:[[:space:]]*\[\][[:space:]]*$" "$CONFIG_FILE" 2>/dev/null \
        && grep -q "^[[:space:]]*url:[[:space:]]*\"\"[[:space:]]*$" "$CONFIG_FILE" 2>/dev/null \
        && ! grep -q "^[[:space:]]*logging:[[:space:]]*$" "$CONFIG_FILE" 2>/dev/null; then
        cp /app/config.yaml.example "$CONFIG_FILE"
        echo "✓ 已将默认空模板升级为发布版模板：$CONFIG_FILE"
    fi
fi

echo "配置文件：$CONFIG_FILE"
echo "密钥文件：$KEY_FILE"

# 启动主程序（守护进程）
echo "[1/2] Starting daemon mode (main.py -d)..."
python main.py -d &
MAIN_PID=$!

sleep 2

if kill -0 $MAIN_PID 2>/dev/null; then
    echo "✓ Daemon started (PID: $MAIN_PID)"
else
    echo "✗ Daemon failed to start"
    exit 1
fi

echo ""

# 启动 Web 界面
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
