# PT Auto Downloader

[简体中文](#简体中文) | [English](#english)

## 简体中文

PT Auto Downloader 是一个面向多 PT 站点的自动化下载工具。它可以持续监控各站点 RSS，新种子可按站点规则自动推送到 qBittorrent，并通过 Web 界面统一管理站点、系统设置、运行日志和下载历史。

### 功能亮点

- 多 PT 站点统一管理，支持按站点独立调度
- 独立控制检查间隔、清理间隔、自动下载、自动清理
- qBittorrent 集成，支持保存路径和分类配置
- 内置 Web 管理界面，支持站点管理、系统设置、日志和下载历史
- 三种访问控制模式：仅局域网、仅白名单 IP、局域网和公网访问
- 主密钥 + 会话 token 认证机制，并支持恢复码重置
- 可选邮件测试与下载事件通知
- 支持 Windows、Linux 和 Docker 部署

### 快速开始

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

### 持久化目录

- `config/`：配置目录，首次启动会自动生成 `config.yaml`
- `data/`：运行数据目录，包含下载历史、`auto_pt.key` 和会话 token 持久化文件
- `logs/`：日志目录

建议同时挂载 `config`、`data`、`logs` 三个目录，避免容器重建或重启后丢失关键运行状态。

### 镜像标签

- `latest`：滚动跟随最新发布版本
- `1.2.0`：当前固定发布版本

### 相关链接

- GitHub: [Rx782-Fss/auto_pt](https://github.com/Rx782-Fss/auto_pt)
- Release: [v1.2.0](https://github.com/Rx782-Fss/auto_pt/releases/tag/v1.2.0)

### 免责声明

本项目仅供学习和个人使用。请在使用时遵守相关 PT 站点规则以及适用的法律法规。

---

## English

PT Auto Downloader is an automation tool for multi-site PT workflows. It continuously monitors RSS feeds from PT sites, pushes matched torrents to qBittorrent based on per-site rules, and provides a built-in web interface for site management, system settings, logs, and download history.

### Highlights

- Multi-site PT management with per-site scheduling
- Independent control for check interval, cleanup interval, auto download, and auto cleanup
- qBittorrent integration with save path and category support
- Built-in web UI for site management, system settings, logs, and download history
- Three access control modes: LAN only, whitelist only, or LAN/public access
- Main secret + session token authentication flow with recovery-code reset
- Optional email test and download event notifications
- Windows, Linux, and Docker deployment support

### Quick Start

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

The container generates `config/config.yaml` automatically on first start.

### Persistent Directories

- `config/`: configuration directory, `config.yaml` is generated automatically on first start
- `data/`: runtime data, including download history, `auto_pt.key`, and session token persistence
- `logs/`: log files

Persisting all three directories is strongly recommended to avoid losing critical runtime state after container recreation or restart.

### Image Tags

- `latest`: rolling tag that follows the newest release
- `1.2.0`: pinned current release version

### Links

- GitHub: [Rx782-Fss/auto_pt](https://github.com/Rx782-Fss/auto_pt)
- Release: [v1.2.0](https://github.com/Rx782-Fss/auto_pt/releases/tag/v1.2.0)

### Disclaimer

This project is intended for learning and personal use only. Please comply with the rules of the PT sites you use and all applicable laws and regulations.
