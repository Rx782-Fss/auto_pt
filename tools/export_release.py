from __future__ import annotations

import argparse
import fnmatch
import shutil
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = PROJECT_ROOT.parent / "发布"

TOP_LEVEL_FILES = [
    ".gitignore",
    ".dockerignore",
    "README.md",
    "README.en.md",
    "LICENSE",
    "requirements.txt",
    "config.yaml.example",
    "main.py",
    "web.py",
    "start.bat",
    "start.sh",
    "check.bat",
    "check.sh",
]

TOP_LEVEL_DIRS = [
    "docker",
    "src",
    "static",
]

IGNORE_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    "logs",
    "data",
    "runtime",
    "tmp",
    "artifacts",
    "backups",
    "config",
    ".git",
    ".github",
    ".idea",
    ".vscode",
}

IGNORE_FILE_NAMES = {
    "config.yaml",
    "auto_pt.key",
    "session_tokens.json",
    "desktop.ini",
    "nul",
}

IGNORE_PATTERNS = [
    "*.bak",
    "*.tmp",
    "*.temp",
    "*.pyc",
    "*.pyo",
    "*.log",
    "*.sqlite",
    "*.db",
    "*.pem",
    "*.p12",
    "*.pfx",
]


def should_skip(path: Path) -> bool:
    name = path.name

    if path.is_dir() and name in IGNORE_DIR_NAMES:
        return True

    if name in IGNORE_FILE_NAMES:
        return True

    if name.startswith(".env") and name != ".env.example":
        return True

    if name.startswith("config") and name.endswith(".yaml") and name != "config.yaml.example":
        return True

    for pattern in IGNORE_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True

    return False


def iter_files(directory: Path) -> Iterable[Path]:
    for entry in sorted(directory.iterdir(), key=lambda item: item.name.lower()):
        if should_skip(entry):
            continue
        if entry.is_dir():
            yield from iter_files(entry)
        else:
            yield entry


def copy_file(src: Path, dst: Path, dry_run: bool) -> None:
    print(f"[COPY] {src.relative_to(PROJECT_ROOT)} -> {dst}")
    if dry_run:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def export_release(target: Path, dry_run: bool, clean: bool, include_docs: bool) -> None:
    source_root = PROJECT_ROOT.resolve()
    target_root = target.resolve()

    if target_root == source_root:
        raise ValueError("发布目录不能和源码根目录相同")

    if source_root in target_root.parents:
        raise ValueError("发布目录不能放在源码目录内部，请使用外部目录")

    if clean and target.exists():
        print(f"[CLEAN] {target_root}")
        if not dry_run:
            shutil.rmtree(target_root)

    if not dry_run:
        target_root.mkdir(parents=True, exist_ok=True)

    for name in TOP_LEVEL_FILES:
        src = source_root / name
        if not src.exists():
            raise FileNotFoundError(f"缺少发布文件：{src}")
        copy_file(src, target_root / name, dry_run)

    directories = list(TOP_LEVEL_DIRS)
    if include_docs:
        directories.append("docs")

    for name in directories:
        src_dir = source_root / name
        if not src_dir.exists():
            raise FileNotFoundError(f"缺少发布目录：{src_dir}")
        for src_file in iter_files(src_dir):
            relative_path = src_file.relative_to(source_root)
            copy_file(src_file, target_root / relative_path, dry_run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="按白名单导出干净的发布目录，排除本地配置、日志、密钥和测试产物。"
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help=f"发布目录，默认：{DEFAULT_TARGET}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要导出的文件，不实际写入。",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="导出前不清空目标目录。",
    )
    parser.add_argument(
        "--include-docs",
        action="store_true",
        help="把 docs/ 目录一并导出到发布目录。默认不导出文档。",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    export_release(
        target=args.target,
        dry_run=args.dry_run,
        clean=not args.no_clean,
        include_docs=args.include_docs,
    )
    print("[DONE] 发布目录检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
