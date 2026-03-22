# Contributing

欢迎提交 Issue 和 Pull Request。

## 开发环境

建议使用以下环境：

- Python 3.11
- Node.js 20
- Git
- Docker（用于镜像验证时）

安装依赖：

```bash
pip install -r requirements.txt
```

## 本地检查

提交前请至少运行一次检查脚本：

```bash
# Windows
check.bat

# Linux / macOS / Git Bash
chmod +x check.sh
./check.sh
```

检查内容包括：

- Python 语法检查
- 前端 JavaScript 语法检查
- `tests/` 下的回归测试

## 配置与敏感信息

请不要提交以下内容：

- `config.yaml`
- `config.*.yaml` 中的本地配置变体
- `.env`、`.env.*`
- `auto_pt.key`、其他密钥文件
- `logs/`、`data/`、`runtime/`、`backups/`
- 带有真实 qBittorrent 地址、账号、密码、邮箱、白名单 IP、站点 RSS/Passkey 的截图或日志

如果需要提供配置示例，请更新 `config.yaml.example`，不要直接上传你的本地配置。

## 发布流程

项目采用以下发布模式：

- GitHub 主仓库维护源码
- Docker Hub 发布镜像
- GitHub Releases 提供干净的发布包

导出发布包请使用：

```bash
# Windows
export-release.bat

# Linux / macOS / Git Bash
./export-release.sh
```

该脚本会按白名单导出文件，自动排除本地配置、密钥、日志和临时文件。
默认不会导出 `docs/`，如需附带文档，请追加 `--include-docs`。

## Pull Request 建议

- 尽量保持改动范围集中
- 涉及配置字段变更时同步更新示例配置和文档
- 涉及前端交互变更时附上截图，但请先确认截图中没有敏感信息
