#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
PYTHON_FILES = [
    "main.py",
    "web.py",
    "src/config.py",
    "src/mteam.py",
    "tests/test_regression.py",
]
FRONTEND_FILES = [
    "static/js/api.js",
    "static/js/config.js",
    "static/js/history.js",
    "static/js/logs.js",
    "static/js/main.js",
    "static/js/panel-manager.js",
    "static/js/preview.js",
    "static/js/sites.js",
]


def _print_header() -> None:
    print("==========================================", flush=True)
    print("  PT Auto Downloader - Check", flush=True)
    print("==========================================", flush=True)
    print(flush=True)


def _run_command(command: list[str]) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT_DIR, check=True)


def run_python_syntax_check() -> None:
    print("[1/3] Python syntax check...", flush=True)
    _run_command([sys.executable, "-m", "py_compile", *PYTHON_FILES])
    print("[OK] Python syntax check passed", flush=True)
    print(flush=True)


def run_frontend_syntax_check() -> None:
    print("[2/3] Frontend syntax check...", flush=True)
    for frontend_file in FRONTEND_FILES:
        _run_command(["node", "--check", frontend_file])
    print("[OK] Frontend syntax check passed", flush=True)
    print(flush=True)


def run_regression_tests() -> None:
    print("[3/3] Regression tests...", flush=True)
    _run_command([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"])
    print("[OK] Regression tests passed", flush=True)
    print(flush=True)


def run_all_checks() -> None:
    _print_header()
    run_python_syntax_check()
    run_frontend_syntax_check()
    run_regression_tests()
    print("==========================================", flush=True)
    print("  All checks passed", flush=True)
    print("==========================================", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run project checks.")
    parser.add_argument(
        "--section",
        choices=("all", "python", "frontend", "tests"),
        default="all",
        help="Only run a specific check section.",
    )
    args = parser.parse_args()

    if args.section == "all":
        run_all_checks()
        return 0
    if args.section == "python":
        run_python_syntax_check()
        return 0
    if args.section == "frontend":
        run_frontend_syntax_check()
        return 0

    run_regression_tests()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
