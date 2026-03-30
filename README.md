# PT Auto Downloader

[简体中文](./README.md) | [English](./README.en.md)

PT Auto Downloader 是一个面向多 PT 站点的自动化下载工具。它可以持续监控各站点 RSS，新种子可按站点规则自动推送到 qBittorrent，并通过 Web 界面统一管理站点、系统设置、运行日志和下载历史。

## 功能特性

- 多 PT 站点统一管理
- 按站点独立设置检查间隔、清理间隔、自动下载、自动清理
- 自动接入 qBittorrent，支持保存路径和分类配置
- Web 管理界面，支持站点管理、系统设置、运行日志、下载历史
- 支持三种访问控制模式：仅局域网、仅白名单 IP、局域网和公网都允许
- 主密钥 + 会话 token 认证机制
- 支持邮件通知测试与下载事件通知（可选）
- 支持 Windows、Linux 和 Docker 部署

## 快速开始

### 方式一：直接使用 Docker Hub 镜像

```bash
docker run -d \
  --name pt-auto-downloader \
  -p 5000:5000 \
  -v ./config:/app/config \
  -v ./data:/app/data \
  -v ./logs:/app/logs \
  -e TZ=Asia/Shanghai \
  -e AUTO_PT_CONFIG_FILE=/app/config/config.yaml \
  -e AUTO_PT_KEY_FILE=/app/data/auto_pt.key \
  --restart unless-stopped \
  futubu/pt-auto-downloader:latest
```

首次启动后会自动生成 `config/config.yaml`。

### 方式二：使用 Compose

以下命令默认在项目根目录执行。
如果你使用的是 GitHub Releases 发布包，请先进入解压后的发布目录再执行。

直接使用 Docker Hub 镜像：

```bash
docker compose -f docker/docker-compose.hub.yaml up -d
```

本地源码构建后运行：

```bash
docker compose -f docker/docker-compose.yaml up -d --build
```

### 访问 Web

```text
http://localhost:5000
```

如果是局域网访问：

```text
http://<你的主机IP>:5000
```

### 首次启动提示

第一次打开页面后，建议按下面顺序完成初始化：

1. 设置主密钥（API 认证密钥）
2. 立即保存一次性恢复码
3. 配置 qBittorrent 连接信息
4. 添加 PT 站点并检查 RSS 配置

## 持久化目录说明

- `config/`：配置目录，首次启动会自动生成 `config.yaml`
- `data/`：运行数据目录，包含下载历史、加密密钥 `auto_pt.key`、会话 token 持久化文件等
- `logs/`：日志目录

建议同时挂载 `config`、`data`、`logs` 三个目录，避免容器重建或重启后丢失关键运行状态。

## 配置示例

当前发布版配置示例：

```yaml
app:
  access_control: lan
  allowed_ips: []
  secret: YOUR_SECRET_KEY_HERE_CHANGE_ME
  session_token_ttl_days: 30
  version: 1.2.1
  web_port: 5000

log_level: WARNING
logging:
  level: INFO
  suppress_request_logs: true
  request_log_level: WARNING

qbittorrent:
  url: ""
  username: ""
  password: ""
  save_path: ""
  category: ""

schedule:
  interval: 600

pt_sites: []
```

站点最小示例：

```yaml
pt_sites:
  - name: hdtime
    passkey: your_passkey
    rss_url: https://example.com/torrentrss.php
```

站点常用完整示例：

```yaml
pt_sites:
  - name: hdtime
    type: mteam
    base_url: https://example.com
    enabled: true
    passkey: your_passkey
    rss_url: https://example.com/torrentrss.php
    tags:
      - hdtime
    schedule:
      interval: 120
      cleanup_interval: 300
    download_settings:
      auto_download: true
      auto_delete: true
      delete_files: false
```

说明：

- `schedule.interval`：站点 RSS 检查间隔
- `schedule.cleanup_interval`：该站点已完成种子的清理间隔，不填时默认跟随检查间隔
- `download_settings.auto_download`：是否自动下载新种子
- `download_settings.auto_delete`：是否自动清理该站点已完成种子
- `download_settings.delete_files`：清理种子时是否同时删除文件
- `app.session_token_ttl_days`：Web 登录会话有效期，默认 30 天；重启后会尽量从 `data/session_tokens.json` 恢复

### 邮件通知（可选）

如果你需要邮件提醒，可以在 Web 界面的系统设置中配置发件邮箱、收件邮箱和 SMTP 信息。
当前支持测试邮件发送，以及下载开始、下载完成等事件通知。

## 访问控制模式

- `lan`：仅允许本机和局域网访问
- `whitelist`：仅允许白名单 IP 访问，本机始终允许
- `public`：允许局域网和公网访问

## 镜像标签

- `latest`：滚动跟随最新发布版本，适合希望持续获取最新更新的部署
- `1.2.1`：固定到当前发布版本，适合希望结果可复现的稳定部署

## 本地运行

```bash
# Windows
py -3 -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt

# Linux
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

复制并编辑配置：

```bash
# Windows
copy config.yaml.example config.yaml

# Linux
cp config.yaml.example config.yaml
```

启动方式：

```bash
# Windows
start.bat

# Linux
chmod +x start.sh
./start.sh
```

说明：

- 启动脚本会优先使用仓库内的 `.venv`。
- Linux 脚本会自动回退到系统 `python3`/`python`。
- Windows 脚本会自动回退到 `py -3` 或 `python`。
- 如果本地没有 `config.yaml`，启动脚本会自动从 `config.yaml.example` 生成一份默认配置。

## 开发与检查

开发启动：

```bash
# 先激活虚拟环境
# Windows: .venv\Scripts\activate
# Linux: source .venv/bin/activate

python main.py -d
python web.py
```

检查脚本：

```bash
# Windows
check.bat

# Linux / Docker
chmod +x check.sh
./check.sh
```

检查脚本会统一执行：

- Python 语法检查
- 前端 JavaScript 语法检查
- `tests/` 下的回归测试
- 发布元数据一致性检查（版本号、主页副标题、Docker 标签等）

## 发布流程

发布操作统一在源码仓库根目录执行，不在导出的 `发布/` 目录里提交代码或打 Git 标签。

发布前建议按下面顺序执行：

```bash
# 1. 在源码仓库根目录完成检查
./check.sh

# 2. 导出干净发布目录，做最终验收
./export-release.sh --target ../发布

# 3. 提交并推送源码
git add .
git commit -m "release: v<version>"
git push origin main

# 4. 打版本标签并推送
git tag v<version>
git push origin v<version>
```

发布规则：

- Git 标签必须与 `config.yaml.example` 中的 `app.version` 一致。
- GitHub Release 页面正文直接从 `CHANGELOG.md` 当前版本条目生成，不再依赖自动生成的 release notes。
- GitHub Actions 会先执行完整检查、版本校验和发布目录白名单校验，再上传 Release 附件。
- Docker 发布会从干净发布目录构建镜像，并同时推送 `futubu/pt-auto-downloader:<version>` 和 `futubu/pt-auto-downloader:latest`。
- 导出的 `发布/` 目录只用于最终验收和对外分发，不包含 `config.yaml`、`auto_pt.key`、`data/`、`logs/`、`.github/`、`AGENTS.md` 等本地或维护信息。

## 常见问题

### 日志存放在哪里？

日志文件位于 `logs/auto_pt.log`，也可以通过 Web 界面查看。

### 为什么建议持久化 `data/` 目录？

因为该目录不仅保存历史数据，还保存加密密钥和会话 token 持久化文件。如果不持久化，容器重建或重启后可能出现认证状态丢失或敏感配置无法正常解密的问题。

### 自动清理清理的是什么？

自动清理针对的是对应站点标签下、在 qBittorrent 中已完成的种子。可选仅删种，或删种并删除文件。

## 许可证

MIT License

## 免责声明

本项目仅供学习和个人使用。请在使用时遵守相关 PT 站点规则以及适用的法律法规。
