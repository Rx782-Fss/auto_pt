#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
CHANGELOG_PATH = ROOT_DIR / "CHANGELOG.md"
RELEASE_ARCHIVE_NAME = "pt-auto-downloader-release.zip"
DOCKER_IMAGE_NAME = "futubu/pt-auto-downloader"


def read_text(relative_path: str) -> str:
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def extract_app_version() -> str:
    config_text = read_text("config.yaml.example")
    in_app_block = False
    app_indent = 0

    for raw_line in config_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if stripped == "app:":
            in_app_block = True
            app_indent = indent
            continue

        if in_app_block and indent <= app_indent and not raw_line.startswith(" " * (app_indent + 1)):
            in_app_block = False

        if in_app_block and stripped.startswith("version:"):
            version = stripped.split(":", 1)[1].strip().strip("'\"")
            if version:
                return version

    raise ValueError("未能从 config.yaml.example 的 app.version 读取版本号")


def extract_changelog_section(version: str) -> tuple[str, list[str]]:
    changelog_lines = CHANGELOG_PATH.read_text(encoding="utf-8").splitlines()
    section_heading_prefix = f"## [{version}]"

    start_index = None
    for index, line in enumerate(changelog_lines):
        if line.startswith(section_heading_prefix):
            start_index = index
            break

    if start_index is None:
        raise ValueError(f"CHANGELOG.md 缺少版本 {version} 的条目")

    end_index = len(changelog_lines)
    for index in range(start_index + 1, len(changelog_lines)):
        if changelog_lines[index].startswith("## ["):
            end_index = index
            break

    section_heading = changelog_lines[start_index]
    section_lines = changelog_lines[start_index + 1 : end_index]

    while section_lines and not section_lines[0].strip():
        section_lines.pop(0)
    while section_lines and not section_lines[-1].strip():
        section_lines.pop()

    bullet_lines = [line for line in section_lines if line.startswith("- ")]
    if not bullet_lines:
        raise ValueError(f"CHANGELOG.md 的版本 {version} 条目没有可发布的更新项")

    return section_heading, bullet_lines


def build_release_notes(version: str) -> str:
    heading, bullet_lines = extract_changelog_section(version)
    release_date = ""
    if " - " in heading:
        release_date = heading.split(" - ", 1)[1].strip()

    lines = [
        f"# PT Auto Downloader v{version}",
        "",
    ]

    if release_date:
        lines.extend(
            [
                f"发布日期：{release_date}",
                "",
            ]
        )

    lines.extend(
        [
            "## 本次更新",
            "",
            *bullet_lines,
            "",
            "## 发布产物",
            "",
            f"- GitHub Release 附件：`{RELEASE_ARCHIVE_NAME}`",
            f"- Docker 镜像：`{DOCKER_IMAGE_NAME}:{version}`",
            f"- Docker 镜像：`{DOCKER_IMAGE_NAME}:latest`",
            "",
            "## 说明",
            "",
            f"- 本页更新内容直接同步自 `CHANGELOG.md` 的 `{version}` 版本条目。",
        ]
    )

    return "\n".join(lines).strip() + "\n"


def write_release_notes(output_path: Path, content: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


def require_contains(relative_path: str, expected_text: str, description: str) -> None:
    content = read_text(relative_path)
    if expected_text not in content:
        raise ValueError(f"{relative_path} 缺少 {description}：{expected_text}")
    print(f"[OK] {relative_path}: {description}")


def require_regex_version(relative_path: str, pattern: str, expected_version: str, description: str) -> None:
    content = read_text(relative_path)
    match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
    if not match:
        raise ValueError(f"{relative_path} 未找到 {description}")

    actual_version = match.group(1).strip()
    if actual_version != expected_version:
        raise ValueError(
            f"{relative_path} 的 {description} 不一致，期望 {expected_version}，实际 {actual_version}"
        )

    print(f"[OK] {relative_path}: {description} = {actual_version}")


def normalize_tag_version(tag: str) -> str:
    normalized = tag.strip()
    if normalized.startswith("refs/tags/"):
        normalized = normalized.removeprefix("refs/tags/")
    if normalized.startswith("v"):
        normalized = normalized[1:]
    return normalized


def check_homepage_version_flow(expected_version: str) -> None:
    require_contains(
        "static/index.html",
        'id="appVersion"',
        "主页副标题版本占位符",
    )
    require_contains(
        "static/js/main.js",
        "apiGet('/api/version')",
        "主页副标题通过 /api/version 读取版本",
    )
    require_contains(
        "static/js/main.js",
        "document.getElementById('appVersion').textContent = data.version || '?'",
        "主页副标题写入版本号",
    )
    require_regex_version(
        "web.py",
        r"return jsonify\(\{'success': True, 'version': '([^']+)'\}\)",
        expected_version,
        "/api/version 返回值",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="校验发布版本元数据是否一致。")
    parser.add_argument(
        "--tag",
        help="可选。校验 Git 标签版本是否与源码版本一致，例如 v1.2.1。",
    )
    parser.add_argument(
        "--write-release-notes",
        type=Path,
        help="可选。把当前版本的 GitHub Release 正文写入指定文件。",
    )
    args = parser.parse_args()

    expected_version = extract_app_version()
    print(f"[INFO] 当前发布版本：{expected_version}")
    changelog_heading, changelog_bullets = extract_changelog_section(expected_version)
    print(f"[OK] CHANGELOG.md: 当前版本条目 = {changelog_heading}")
    print(f"[OK] CHANGELOG.md: 当前版本更新项数量 = {len(changelog_bullets)}")

    require_contains(
        "README.md",
        f"version: {expected_version}",
        "中文 README 配置示例版本号",
    )
    require_contains(
        "README.md",
        f"- `{expected_version}`：固定到当前发布版本",
        "中文 README 固定标签说明",
    )
    require_contains(
        "README.en.md",
        f"version: {expected_version}",
        "英文 README 配置示例版本号",
    )
    require_contains(
        "README.en.md",
        f"- `{expected_version}`: pinned current release tag",
        "英文 README 固定标签说明",
    )
    require_regex_version(
        "docker/docker-compose.hub.yaml",
        r"image:\s+futubu/pt-auto-downloader:([^\s]+)",
        expected_version,
        "Docker Hub 镜像标签",
    )
    require_contains(
        ".github/dockerhub-overview.md",
        f"- `{expected_version}`：当前固定发布版本",
        "Docker Hub 概览中文固定标签说明",
    )
    require_contains(
        ".github/dockerhub-overview.md",
        f"- `{expected_version}`: pinned current release version",
        "Docker Hub 概览英文固定标签说明",
    )
    require_contains(
        ".github/dockerhub-overview.md",
        f"Release: [v{expected_version}]",
        "Docker Hub 概览 Release 链接版本号",
    )
    require_contains(
        ".github/ISSUE_TEMPLATE/bug-report.yml",
        f"版本：v{expected_version}",
        "Bug 模板默认版本号",
    )

    check_homepage_version_flow(expected_version)

    if args.tag:
        tag_version = normalize_tag_version(args.tag)
        if tag_version != expected_version:
            raise ValueError(f"Git 标签版本不一致，期望 v{expected_version}，实际 {args.tag}")
        print(f"[OK] Git 标签版本 = v{tag_version}")

    if args.write_release_notes:
        release_notes = build_release_notes(expected_version)
        write_release_notes(args.write_release_notes, release_notes)
        print(f"[OK] GitHub Release 正文已生成：{args.write_release_notes}")

    print("[DONE] 发布元数据检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
