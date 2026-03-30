# PT Auto Downloader

[简体中文](./README.md) | [English](./README.en.md)

PT Auto Downloader is an automation tool for multi-site PT workflows. It continuously monitors RSS feeds from PT sites, pushes matched torrents to qBittorrent based on per-site rules, and provides a built-in web interface for site management, system settings, logs, and download history.

## Features

- Unified management for multiple PT sites
- Per-site scheduling for check interval, cleanup interval, auto download, and auto cleanup
- qBittorrent integration with save path and category support
- Built-in web UI for site management, system settings, runtime logs, and download history
- Three access control modes: LAN only, whitelist only, or LAN/public access
- Main secret + session token authentication flow
- Optional email test and download event notifications
- Supports Windows, Linux, and Docker deployment

## Quick Start

### Option 1: Run the Docker Hub image directly

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

### Option 2: Use Compose

Run the following commands from the project root directory.
If you are using a GitHub Releases package, enter the extracted release directory first.

Use the Docker Hub image:

```bash
docker compose -f docker/docker-compose.hub.yaml up -d
```

Build from local source:

```bash
docker compose -f docker/docker-compose.yaml up -d --build
```

### Access the Web UI

```text
http://localhost:5000
```

For LAN access:

```text
http://<your-host-ip>:5000
```

### First-time setup

When you open the page for the first time, it is recommended to initialize in this order:

1. Set the main secret (API authentication key)
2. Save the one-time recovery code immediately
3. Configure qBittorrent connection settings
4. Add PT sites and verify their RSS configuration

## Persistent Directories

- `config/`: configuration directory, `config.yaml` is generated automatically on first start
- `data/`: runtime data, including download history, encryption key `auto_pt.key`, and session token persistence
- `logs/`: log files

Persisting all three directories is strongly recommended to avoid losing critical runtime state after container recreation or restart.

## Configuration Examples

Current release configuration example:

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

Minimal site example:

```yaml
pt_sites:
  - name: hdtime
    passkey: your_passkey
    rss_url: https://example.com/torrentrss.php
```

Typical full site example:

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

Notes:

- `schedule.interval`: RSS polling interval for the site
- `schedule.cleanup_interval`: cleanup interval for completed torrents of that site; when omitted, it follows the check interval
- `download_settings.auto_download`: whether to automatically download newly discovered torrents
- `download_settings.auto_delete`: whether to automatically clean completed torrents for that site
- `download_settings.delete_files`: whether to delete files together with the torrent
- `app.session_token_ttl_days`: Web session lifetime in days. Default is 30 days, and restarts try to recover from `data/session_tokens.json`

### Email Notifications (Optional)

If you need email reminders, you can configure sender, recipient, and SMTP settings in the web UI system settings.
The project currently supports test email delivery and notifications for events such as download start and download completion.

## Access Control Modes

- `lan`: allow localhost and LAN access only
- `whitelist`: allow whitelist IPs only; localhost is always allowed
- `public`: allow both LAN and public access

## Image Tags

- `latest`: rolling tag that follows the newest release, suitable when you want ongoing updates
- `1.2.1`: pinned current release tag, suitable for reproducible and stable deployments

## Local Run

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

Copy and edit the configuration:

```bash
# Windows
copy config.yaml.example config.yaml

# Linux
cp config.yaml.example config.yaml
```

Start the service:

```bash
# Windows
start.bat

# Linux
chmod +x start.sh
./start.sh
```

Notes:

- The start scripts prefer the repository-local `.venv` when it exists.
- Linux scripts automatically fall back to system `python3` or `python`.
- Windows scripts automatically fall back to `py -3` or `python`.
- If `config.yaml` does not exist yet, the start scripts create it from `config.yaml.example`.

## Development and Checks

Development startup:

```bash
# Activate the virtual environment first
# Windows: .venv\Scripts\activate
# Linux: source .venv/bin/activate

python main.py -d
python web.py
```

Check scripts:

```bash
# Windows
check.bat

# Linux / Docker
chmod +x check.sh
./check.sh
```

The check scripts perform:

- Python syntax checks
- Frontend JavaScript syntax checks
- Regression tests under `tests/`
- Release metadata consistency checks, including version strings, homepage version flow, and Docker tags

## Release Process

Run release operations from the source repository root. Do not use the exported `发布/` directory for code commits or Git tags.

Recommended release sequence:

```bash
# 1. Run all checks in the source repository
./check.sh

# 2. Export a clean release directory for final inspection
./export-release.sh --target ../发布

# 3. Commit and push source changes
git add .
git commit -m "release: v<version>"
git push origin main

# 4. Create and push the version tag
git tag v<version>
git push origin v<version>
```

Release rules:

- The Git tag must match `app.version` in `config.yaml.example`.
- The GitHub Release page body is generated directly from the current version section in `CHANGELOG.md` instead of auto-generated release notes.
- GitHub Actions runs the full checks, version validation, and exported-release whitelist validation before uploading the Release artifact.
- Docker publishing builds from the clean exported release directory and pushes both `futubu/pt-auto-downloader:<version>` and `futubu/pt-auto-downloader:latest`.
- The exported `发布/` directory is only for final verification and distribution. It excludes local or maintenance-only files such as `config.yaml`, `auto_pt.key`, `data/`, `logs/`, `.github/`, and `AGENTS.md`.

## FAQ

### Where are logs stored?

Logs are stored in `logs/auto_pt.log`, and can also be viewed in the web UI.

### Why is persisting the `data/` directory strongly recommended?

Because it stores not only history data, but also the encryption key and session token persistence files. Without it, container recreation or restart may lead to lost authentication state or failure to decrypt sensitive configuration values.

### What does auto cleanup actually clean?

Auto cleanup targets completed torrents in qBittorrent under the corresponding site tags. It can either remove only the torrent entry or remove both the torrent and its files.

## License

MIT License

## Disclaimer

This project is intended for learning and personal use only. Please comply with the rules of the PT sites you use and all applicable laws and regulations.
