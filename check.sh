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

echo "[PYTHON] Using: ${PYTHON_CMD}"
"${PYTHON_CMD}" tools/run_checks.py
