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
  version: 1.2.0
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

### 邮件通知（可选）

如果你需要邮件提醒，可以在 Web 界面的系统设置中配置发件邮箱、收件邮箱和 SMTP 信息。
当前支持测试邮件发送，以及下载开始、下载完成等事件通知。

## 访问控制模式

- `lan`：仅允许本机和局域网访问
- `whitelist`：仅允许白名单 IP 访问，本机始终允许
- `public`：允许局域网和公网访问

## 镜像标签

- `latest`：最新发布版本
- `1.2.0`：当前固定发布版本

## 本地运行

```bash
pip install -r requirements.txt
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

## 开发与检查

开发启动：

```bash
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
