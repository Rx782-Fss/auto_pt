from flask import Flask, jsonify, request, send_from_directory, session, g
from flask_cors import CORS
import yaml
import os
import json
import copy
import hashlib
import ipaddress
import time
import requests
import hmac
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from src.logger_config import (
    setup_logging,
    get_logger,
    log_startup_message,
    reload_logging,
    resolve_log_targets,
)
from src.log_constants import (
    LOG_WEB_SERVICE,
    LOG_WEB_ACCESS,
    LOG_WEB_AUTH,
    LOG_WEB_API,
    LOG_WEB_CONFIG,
    LOG_WEB_DOWNLOAD,
    LOG_WEB_HISTORY,
    LOG_WEB_LOGS,
)
from src.notifications import (
    normalize_notification_settings,
    notification_settings_complete,
    send_email_notification,
)
from src.qb_status import qb_state_to_status, summarize_qb_torrent_states
from src.config import get_qbittorrent_host, normalize_qbittorrent_config

BASE_DIR = Path(__file__).parent.resolve()


def _resolve_config_file() -> Path:
    """解析 Web 使用的配置文件路径，支持容器环境覆盖。"""
    env_config = os.getenv("AUTO_PT_CONFIG_FILE", "").strip()
    if env_config:
        config_path = Path(env_config).expanduser()
        if not config_path.is_absolute():
            config_path = (BASE_DIR / config_path).resolve()
        return config_path
    return BASE_DIR / 'config.yaml'


CONFIG_FILE = _resolve_config_file()
_CONFIG_FILE = CONFIG_FILE

# 简单的日志初始化（不依赖 load_config 函数）
# 获取日志配置并初始化日志系统
try:
    with open(_CONFIG_FILE, 'r', encoding='utf-8') as f:
        _INITIAL_CONFIG = yaml.safe_load(f) or {}
except:
    _INITIAL_CONFIG = {}
setup_logging(_INITIAL_CONFIG.get('logging', {}))
MAX_LOG_TAIL_BYTES = 1024 * 1024
MAX_LOG_TAIL_LINES = 1000

app = Flask(__name__, static_folder=BASE_DIR / 'static', static_url_path='')
app.secret_key = os.urandom(24)
# 限制 CORS 为本地来源
CORS(app, origins=["http://localhost:5000", "http://127.0.0.1:5000", "http://localhost:*", "http://127.0.0.1:*"])

logger = get_logger(__name__)

_preview_cache = {}
DEFAULT_SESSION_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60
_session_tokens = {}
_session_tokens_lock = threading.Lock()
_FIRST_TIME_ALLOWED_PATHS = {'/api/config'}
_RECOVERY_CODE_GROUP_SIZE = 4
_SESSION_TOKENS_PERSIST_MIN_INTERVAL_SECONDS = 300
_SESSION_TOKENS_PERSIST_RETRY_DELAYS = (0.05, 0.15, 0.3, 0.6)
_session_tokens_last_persist_at = 0.0
_session_tokens_last_warning_at = 0.0


def _resolve_log_file(config: dict | None = None) -> Path:
    """解析当前生效的主日志文件路径，保持与日志器完全一致。"""
    config_data = config if isinstance(config, dict) else {}
    logging_config = dict(config_data.get('logging', {}) or {})
    return resolve_log_targets(logging_config, base_dir=BASE_DIR)["log_path"]


LOG_FILE = _resolve_log_file(_INITIAL_CONFIG)


def _get_active_log_file() -> Path:
    """获取当前运行时生效的主日志文件路径。"""
    try:
        current_config = load_config()
    except Exception:
        return LOG_FILE
    return _resolve_log_file(current_config)


def _resolve_runtime_data_dir() -> Path:
    """解析运行时数据目录，优先跟随密钥文件目录。"""
    env_key_file = os.getenv("AUTO_PT_KEY_FILE", "").strip()
    if env_key_file:
        key_path = Path(env_key_file).expanduser()
        if not key_path.is_absolute():
            key_path = (BASE_DIR / key_path).resolve()
        return key_path.parent
    return BASE_DIR / 'data'


def _resolve_session_tokens_file() -> Path:
    """解析会话 token 持久化文件路径。"""
    env_tokens_file = os.getenv("AUTO_PT_SESSION_TOKENS_FILE", "").strip()
    if env_tokens_file:
        tokens_path = Path(env_tokens_file).expanduser()
        if not tokens_path.is_absolute():
            tokens_path = (BASE_DIR / tokens_path).resolve()
        return tokens_path
    return _resolve_runtime_data_dir() / 'session_tokens.json'


def _resolve_history_file() -> Path:
    """解析历史记录文件路径，保持与运行时数据目录一致。"""
    env_history_file = os.getenv("AUTO_PT_HISTORY_FILE", "").strip()
    if env_history_file:
        history_path = Path(env_history_file).expanduser()
        if not history_path.is_absolute():
            history_path = (BASE_DIR / history_path).resolve()
        return history_path
    return _resolve_runtime_data_dir() / 'history.json'


def _to_positive_int(value, default: int) -> int:
    """把输入转为正整数，失败时返回默认值。"""
    try:
        normalized = int(value)
    except Exception:
        return int(default)
    return normalized if normalized > 0 else int(default)


def _get_session_token_ttl_seconds(config: dict | None = None) -> int:
    """获取会话 token 有效期，默认 30 天。"""
    env_ttl_seconds = os.getenv("AUTO_PT_SESSION_TOKEN_TTL_SECONDS", "").strip()
    if env_ttl_seconds:
        return _to_positive_int(env_ttl_seconds, DEFAULT_SESSION_TOKEN_TTL_SECONDS)

    current_config = config if isinstance(config, dict) else {}
    if not isinstance(config, dict):
        try:
            current_config = load_config()
        except Exception:
            return DEFAULT_SESSION_TOKEN_TTL_SECONDS
    if not isinstance(current_config, dict):
        return DEFAULT_SESSION_TOKEN_TTL_SECONDS
    app_config = current_config.get('app', {}) if isinstance(current_config, dict) else {}

    ttl_seconds = app_config.get('session_token_ttl_seconds')
    if ttl_seconds not in (None, ''):
        return _to_positive_int(ttl_seconds, DEFAULT_SESSION_TOKEN_TTL_SECONDS)

    ttl_days = app_config.get('session_token_ttl_days')
    if ttl_days not in (None, ''):
        return _to_positive_int(ttl_days, 30) * 24 * 60 * 60

    return DEFAULT_SESSION_TOKEN_TTL_SECONDS


_SESSION_TOKENS_FILE = _resolve_session_tokens_file()
HISTORY_FILE = _resolve_history_file()


def _extract_auth_token(auth_header) -> str:
    """统一提取 Authorization 中的 token。"""
    header_value = str(auth_header or '').strip()
    if not header_value:
        return ''
    if header_value.startswith('Bearer '):
        return header_value[7:].strip()
    return header_value


def _cleanup_expired_session_tokens(now: float | None = None):
    """清理过期会话 token，避免内存中的历史 token 持续堆积。"""
    current_time = now if now is not None else time.time()
    expired_tokens = [
        token for token, expires_at in _session_tokens.items()
        if expires_at <= current_time
    ]
    changed = False
    for token in expired_tokens:
        _session_tokens.pop(token, None)
        changed = True
    return changed


def _build_session_tokens_temp_file() -> Path:
    """生成当前进程/线程专用的临时文件，避免多个实例争用同一个 .tmp 文件。"""
    temp_name = f"{_SESSION_TOKENS_FILE.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    return _SESSION_TOKENS_FILE.with_name(temp_name)


def _persist_session_tokens_to_disk(force: bool = False):
    """把当前会话 token 状态落盘，便于服务重启后恢复。"""
    global _session_tokens_last_persist_at
    global _session_tokens_last_warning_at

    try:
        _SESSION_TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
        current_time = time.time()
        payload = {
            token: expires_at
            for token, expires_at in _session_tokens.items()
            if expires_at > current_time
        }

        if not force and current_time - _session_tokens_last_persist_at < _SESSION_TOKENS_PERSIST_MIN_INTERVAL_SECONDS:
            return

        temp_file = _build_session_tokens_temp_file()
        last_error = None
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass

        try:
            for delay in _SESSION_TOKENS_PERSIST_RETRY_DELAYS:
                try:
                    os.replace(temp_file, _SESSION_TOKENS_FILE)
                    _session_tokens_last_persist_at = time.time()
                    try:
                        os.chmod(_SESSION_TOKENS_FILE, 0o600)
                    except Exception:
                        pass
                    return
                except PermissionError as exc:
                    last_error = exc
                except OSError as exc:
                    last_error = exc
                time.sleep(delay)
        finally:
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except Exception:
                pass

        if last_error and (force or current_time - _session_tokens_last_warning_at >= 60):
            _session_tokens_last_warning_at = current_time
            logger.warning(f'{LOG_WEB_AUTH} 持久化会话 token 失败：{last_error}')
    except Exception as exc:
        if force or time.time() - _session_tokens_last_warning_at >= 60:
            _session_tokens_last_warning_at = time.time()
            logger.warning(f'{LOG_WEB_AUTH} 持久化会话 token 失败：{exc}')


def _load_session_tokens_from_disk():
    """从磁盘恢复会话 token。"""
    if not _SESSION_TOKENS_FILE.exists():
        return

    try:
        with open(_SESSION_TOKENS_FILE, 'r', encoding='utf-8') as f:
            payload = json.load(f) or {}
    except Exception as exc:
        logger.warning(f'{LOG_WEB_AUTH} 读取会话 token 文件失败：{exc}')
        return

    current_time = time.time()
    loaded_tokens = {}
    needs_persist = False

    items = []
    if isinstance(payload, dict):
        items = list(payload.items())
    elif isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, dict):
                items.append((entry.get('token', ''), entry.get('expires_at', 0)))
        needs_persist = True
    else:
        logger.warning(f'{LOG_WEB_AUTH} 会话 token 文件格式不正确，已忽略')
        return

    for token, expires_at in items:
        normalized_token = str(token or '').strip()
        try:
            normalized_expires_at = int(expires_at)
        except Exception:
            needs_persist = True
            continue

        if not normalized_token:
            needs_persist = True
            continue

        if normalized_expires_at <= current_time:
            needs_persist = True
            continue

        loaded_tokens[normalized_token] = normalized_expires_at

    with _session_tokens_lock:
        _session_tokens.clear()
        _session_tokens.update(loaded_tokens)
        if _cleanup_expired_session_tokens(current_time):
            needs_persist = True

    if needs_persist:
        _persist_session_tokens_to_disk(force=True)

def _issue_session_token(ttl_seconds: int | None = None) -> tuple[str, int]:
    """签发短期会话 token。"""
    effective_ttl = _get_session_token_ttl_seconds() if ttl_seconds is None else int(ttl_seconds)
    with _session_tokens_lock:
        now = time.time()
        _cleanup_expired_session_tokens(now)
        session_token = secrets.token_urlsafe(32)
        expires_at = int(now + effective_ttl)
        _session_tokens[session_token] = expires_at
        _persist_session_tokens_to_disk(force=True)
        return session_token, expires_at


def _validate_session_token(token: str, ttl_seconds: int | None = None) -> bool:
    """校验并续期会话 token。"""
    normalized_token = str(token or '').strip()
    if not normalized_token:
        return False

    effective_ttl = _get_session_token_ttl_seconds() if ttl_seconds is None else int(ttl_seconds)
    with _session_tokens_lock:
        now = time.time()
        expires_at = _session_tokens.get(normalized_token)
        if not expires_at:
            return False
        if expires_at <= now:
            _session_tokens.pop(normalized_token, None)
            _persist_session_tokens_to_disk(force=True)
            return False

        _session_tokens[normalized_token] = int(now + effective_ttl)
        _cleanup_expired_session_tokens(now)
        _persist_session_tokens_to_disk()
        return True


def _invalidate_all_session_tokens():
    """主密钥实际变更后，统一使旧会话失效。"""
    with _session_tokens_lock:
        _session_tokens.clear()
        _persist_session_tokens_to_disk(force=True)


def _normalize_recovery_code(code: str) -> str:
    """统一归一化恢复码格式，去掉分隔符后再比较。"""
    return ''.join(ch for ch in str(code or '').strip().upper() if ch.isalnum())


def _format_recovery_code(raw_code: str) -> str:
    """把连续字符串格式化为更易抄写的分组格式。"""
    normalized = _normalize_recovery_code(raw_code)
    if not normalized:
        return ''
    return '-'.join(
        normalized[i:i + _RECOVERY_CODE_GROUP_SIZE]
        for i in range(0, len(normalized), _RECOVERY_CODE_GROUP_SIZE)
    )


def _generate_recovery_code() -> str:
    """生成新的恢复码。"""
    return _format_recovery_code(secrets.token_hex(16).upper())


def _is_recovery_code_valid(stored_code: str, provided_code: str) -> bool:
    """校验恢复码。"""
    normalized_stored = _normalize_recovery_code(stored_code)
    normalized_provided = _normalize_recovery_code(provided_code)
    if not normalized_stored or not normalized_provided:
        return False
    return hmac.compare_digest(normalized_stored, normalized_provided)


def _get_secret_source(config=None) -> str:
    """判断当前密钥来源，便于提示用户是否受环境变量覆盖。"""
    if os.getenv('APP_SECRET'):
        return 'env'

    current_config = config if config is not None else load_config()
    secret = current_config.get('app', {}).get('secret', '')
    placeholder_secrets = {
        '',
        'auto-pt-default-secret-change-me',
        'YOUR_SECRET_KEY_HERE_CHANGE_ME',
    }
    if secret in placeholder_secrets:
        return 'default'
    return 'file'


def _ensure_recovery_code(config, force_new: bool = False) -> str:
    """确保配置中有可用的恢复码，必要时强制生成新的。"""
    if not isinstance(config, dict):
        return ''

    app_config = config.setdefault('app', {})
    current_code = str(app_config.get('recovery_code', '') or '').strip()
    if force_new or not current_code:
        current_code = _generate_recovery_code()
        app_config['recovery_code'] = current_code
        app_config['recovery_code_created_at'] = (
            datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        )
    return current_code


def _try_send_recovery_code_email(config, recovery_code: str, reason_text: str) -> tuple[bool, str]:
    """如果邮件配置完整，则自动发送恢复码。"""
    notifications = normalize_notification_settings(config.get('notifications', {}))
    if not notification_settings_complete(notifications):
        return False, '邮件通知配置不完整，未自动发送恢复码'

    subject = 'Auto PT 恢复码'
    body = (
        f'Auto PT Downloader {reason_text}\n\n'
        f'恢复码：{recovery_code}\n\n'
        '请立即离线保存这段恢复码。它只用于在忘记 API 密钥时重置访问权限。'
    )
    success, message = send_email_notification(
        notifications,
        subject=subject,
        text=body,
        require_enabled=False,
    )
    return success, '' if success else message


def _send_recovery_email_if_configured(config, reason_text: str) -> tuple[bool, str]:
    """邮箱恢复入口：在已配置邮箱信息时，直接发送当前恢复码。"""
    notifications = normalize_notification_settings(config.get('notifications', {}))
    if not notification_settings_complete(notifications):
        return False, '没有设置邮箱信息，请改用恢复码恢复'

    recovery_code = str(config.get('app', {}).get('recovery_code', '') or '').strip()
    if not recovery_code:
        return False, '当前未配置恢复码，无法通过邮箱恢复'

    subject = 'Auto PT 恢复码'
    body = (
        f'Auto PT Downloader {reason_text}\n\n'
        f'恢复码：{recovery_code}\n\n'
        '请立即离线保存这段恢复码。它只用于在忘记 API 密钥时重置访问权限。'
    )
    success, message = send_email_notification(
        notifications,
        subject=subject,
        text=body,
        require_enabled=False,
    )
    return success, '' if success else message


def _validate_auth_token(token: str) -> tuple[bool, str]:
    """校验认证令牌，返回 (是否有效, 类型)。"""
    normalized_token = str(token or '').strip()
    if not normalized_token:
        return False, ''

    if _validate_session_token(normalized_token, ttl_seconds=_get_session_token_ttl_seconds()):
        return True, 'session'

    expected_token = get_app_secret()
    if hmac.compare_digest(normalized_token, str(expected_token)):
        return True, 'legacy-secret'

    return False, ''


_load_session_tokens_from_disk()

# ==================== 访问控制相关 ====================

def is_lan_ip(ip):
    """
    判断 IP 是否为局域网地址
    支持：192.168.x.x, 10.x.x.x, 172.16-31.x.x
    """
    if not ip:
        return False
    
    # 常见的局域网 IP 段
    return ip.startswith('192.168.') or \
           ip.startswith('10.') or \
           ip.startswith('172.16.') or \
           ip.startswith('172.17.') or \
           ip.startswith('172.18.') or \
           ip.startswith('172.19.') or \
           ip.startswith('172.20.') or \
           ip.startswith('172.21.') or \
           ip.startswith('172.22.') or \
           ip.startswith('172.23.') or \
           ip.startswith('172.24.') or \
           ip.startswith('172.25.') or \
           ip.startswith('172.26.') or \
           ip.startswith('172.27.') or \
           ip.startswith('172.28.') or \
           ip.startswith('172.29.') or \
           ip.startswith('172.30.') or \
           ip.startswith('172.31.')


def is_loopback_ip(ip):
    """判断是否为本机回环地址。"""
    return ip in ['127.0.0.1', '::1', 'localhost']


def normalize_access_mode(access_mode):
    """统一访问控制模式，兼容旧配置值。"""
    mode = (access_mode or 'lan').strip().lower()

    aliases = {
        'local': 'lan',
        'all': 'public',
    }
    return aliases.get(mode, mode)


def _ip_matches_wildcard_pattern(client_ip: str, pattern: str) -> bool:
    """支持 203.0.113.x / 203.0.113.* 这种 IPv4 段匹配。"""
    ip_text = str(client_ip or '').strip()
    pattern_text = str(pattern or '').strip()
    if not ip_text or not pattern_text:
        return False

    ip_parts = ip_text.split('.')
    pattern_parts = pattern_text.split('.')
    if len(ip_parts) != 4 or len(pattern_parts) != 4:
        return False

    for ip_part, pattern_part in zip(ip_parts, pattern_parts):
        normalized_part = pattern_part.strip().lower()
        if normalized_part in {'x', '*'}:
            continue
        if ip_part != pattern_part.strip():
            return False
    return True


def is_ip_in_allowed_list(client_ip: str, allowed_ips) -> bool:
    """判断客户端 IP 是否命中白名单，支持精确 IP、CIDR 和 x/* 通配段。"""
    ip_text = str(client_ip or '').strip()
    if not ip_text:
        return False

    try:
        ip_obj = ipaddress.ip_address(ip_text)
    except ValueError:
        ip_obj = None

    for raw_entry in allowed_ips or []:
        entry = str(raw_entry or '').strip()
        if not entry:
            continue
        if entry == ip_text:
            return True
        if ('x' in entry.lower()) or ('*' in entry):
            if _ip_matches_wildcard_pattern(ip_text, entry):
                return True
            continue
        if '/' in entry and ip_obj is not None:
            try:
                if ip_obj in ipaddress.ip_network(entry, strict=False):
                    return True
            except ValueError:
                continue

    return False

def check_access_control():
    """
    访问控制检查 - 在请求处理前调用
    返回：(allowed: bool, error_message: str|None)
    """
    from flask import request
    
    cfg = load_config()
    access_mode = normalize_access_mode(cfg.get('app', {}).get('access_control', 'lan'))
    client_ip = request.remote_addr
    
    logger.debug(f'{LOG_WEB_ACCESS} 客户端 IP: {client_ip}, 模式：{access_mode}')
    
    if access_mode == 'lan':
        # 仅允许本机 + 局域网访问
        if is_loopback_ip(client_ip):
            return True, None
        if is_lan_ip(client_ip):
            logger.debug(f'{LOG_WEB_ACCESS} 允许局域网访问：{client_ip}')
            return True, None
        logger.warning(f'{LOG_WEB_ACCESS} 拒绝公网访问：{client_ip}')
        return False, '禁止公网访问，请在系统设置中修改访问控制模式'
    
    elif access_mode == 'whitelist':
        # IP 白名单模式（本机永远允许）
        if is_loopback_ip(client_ip):
            logger.debug(f'{LOG_WEB_ACCESS} 白名单模式：本机访问允许')
            return True, None
        
        allowed_ips = cfg.get('app', {}).get('allowed_ips', [])
        # 清理 IP 列表（去除空格）
        allowed_ips = [ip.strip() for ip in allowed_ips if ip.strip()]
        
        if not is_ip_in_allowed_list(client_ip, allowed_ips):
            logger.warning(f'{LOG_WEB_ACCESS} IP 不在白名单：{client_ip}')
            return False, f'IP 未授权 ({client_ip})'

        logger.debug(f'{LOG_WEB_ACCESS} 白名单允许访问：{client_ip}')
        return True, None

    if access_mode != 'public':
        logger.warning(f'{LOG_WEB_ACCESS} 未知访问模式：{access_mode}，已按 public 处理')

    # public 时不限制 IP
    # 但所有敏感 API 仍需认证
    return True, None

# ==================== 安全认证相关 ====================

def get_app_secret():
    """获取应用密钥（用于认证）"""
    config = load_config()
    # 优先从 app.secret 获取，否则生成默认值
    return config.get('app', {}).get('secret', 'auto-pt-default-secret-change-me')


def _is_first_time_setup() -> bool:
    """检查是否首次设置密钥（secret 为空）"""
    try:
        config = load_config()
        secret = config.get('app', {}).get('secret', '')
        
        # 也检查环境变量
        env_secret = os.getenv('APP_SECRET', '')
        
        # secret 为空或占位值时认为是首次设置（同时环境变量也没设置）
        placeholder_secrets = {
            '',
            'auto-pt-default-secret-change-me',
            'YOUR_SECRET_KEY_HERE_CHANGE_ME',
        }
        has_secret = (secret not in placeholder_secrets) or bool(env_secret)
        
        return not has_secret
    except:
        return True


def _check_first_time_allowed() -> tuple:
    """检查首次设置时是否允许操作
    
    返回: (allowed: bool, error_message: str)
    首次设置时，只允许：设置 app.secret
    """
    from flask import request, jsonify
    
    # 检查请求内容
    data = request.get_json() or {}
    
    # 只允许设置 app.secret
    allowed_fields = {'app'}
    allowed_app_fields = {'secret', 'access_control', 'allowed_ips', 'web_port', 'version'}
    
    # 检查顶级字段
    for key in data.keys():
        if key not in allowed_fields:
            return False, f'首次设置时不允许修改：{key}'
    
    # 检查 app 字段
    app_data = data.get('app', {})
    for key in app_data.keys():
        if key not in allowed_app_fields:
            return False, f'首次设置时不允许修改 app.{key}'
    
    # 确保 secret 必须提供
    if not app_data.get('secret'):
        return False, '首次设置时必须提供 secret'
    
    return True, ''


def _check_first_time_site_allowed() -> tuple:
    """检查首次设置时是否允许站点操作
    
    返回: (allowed: bool, error_message: str)
    首次设置时，不允许任何站点操作
    """
    return False, '请先设置 API 认证密钥后再管理站点'


def require_auth(f):
    """认证装饰器 - 验证 Authorization header
    
    首次设置密钥时跳过认证，但保留访问控制，并对敏感操作进行限制
    """
    from functools import wraps
    
    @wraps(f)
    def decorated(*args, **kwargs):
        from flask import request, jsonify
        
        # 首次设置密钥时：允许访问，但仍然检查访问控制
        if _is_first_time_setup():
            # 仍然检查访问控制，只是跳过 token 验证
            allowed, error_msg = check_access_control()
            if not allowed:
                logger.error(f'{LOG_WEB_AUTH} 访问控制拒绝：{error_msg}')
                return jsonify({'success': False, 'error': error_msg}), 403

            path = request.path
            if path not in _FIRST_TIME_ALLOWED_PATHS:
                logger.warning(f'{LOG_WEB_AUTH} 首次设置时禁止访问：{path}')
                return jsonify({'success': False, 'error': '请先设置 API 认证密钥'}), 403
            
            return f(*args, **kwargs)
        
        # 非首次设置：完整认证
        allowed, error_msg = check_access_control()
        if not allowed:
            logger.error(f'{LOG_WEB_AUTH} 访问控制拒绝：{error_msg}')
            return jsonify({'success': False, 'error': error_msg}), 403
        
        # 检查 Authorization header
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            logger.warning(f'{LOG_WEB_AUTH} 未提供认证令牌')
            return jsonify({'success': False, 'error': '未提供认证令牌'}), 401
        
        token = _extract_auth_token(auth_header)
        logger.debug(f'{LOG_WEB_AUTH} 已收到认证令牌，开始校验')
        
        token_valid, token_type = _validate_auth_token(token)
        if not token_valid:
            logger.error(f'{LOG_WEB_AUTH} 认证失败：令牌无效')
            return jsonify({'success': False, 'error': '认证失败：令牌无效'}), 401

        g.auth_token_type = token_type
        g.auth_token_value = token
        logger.debug(f'{LOG_WEB_AUTH} 认证成功')
        return f(*args, **kwargs)
    
    return decorated


@app.after_request
def attach_auth_mode_header(response):
    """把认证类型回传给前端，便于将旧主密钥平滑升级为会话 token。"""
    token_type = getattr(g, 'auth_token_type', '')
    if token_type:
        response.headers['X-Auto-PT-Auth-Mode'] = token_type
    return response


@app.route('/api/auth/token', methods=['POST'])
def exchange_auth_token():
    """把主密钥或现有会话 token 换成短期会话 token。"""
    allowed, error_msg = check_access_control()
    if not allowed:
        return jsonify({'success': False, 'error': error_msg}), 403

    if _is_first_time_setup():
        return jsonify({'success': False, 'error': '请先设置 API 认证密钥'}), 400

    auth_header = request.headers.get('Authorization')
    token = _extract_auth_token(auth_header)
    token_valid, token_type = _validate_auth_token(token)
    if not token_valid:
        return jsonify({'success': False, 'error': '认证失败：令牌无效'}), 401

    session_token, expires_at = _issue_session_token()
    logger.info(f'{LOG_WEB_AUTH} 已签发会话 token，来源：{token_type}')

    return jsonify({
        'success': True,
        'token': session_token,
        'expires_at': expires_at,
        'token_type': 'session',
        'source_type': token_type,
    })


@app.route('/api/auth/recover', methods=['POST'])
def recover_auth_secret():
    """使用恢复码重置 API 密钥。"""
    allowed, error_msg = check_access_control()
    if not allowed:
        return jsonify({'success': False, 'error': error_msg}), 403

    if _get_secret_source() == 'env':
        return jsonify({
            'success': False,
            'error': '当前由 APP_SECRET 环境变量管理密钥，页面重置不会生效，请先修改启动脚本或环境变量'
        }), 400

    data = request.get_json(silent=True) or {}
    recovery_code = str(data.get('recovery_code', '') or '').strip()
    new_secret = str(data.get('secret', '') or '').strip()

    if not recovery_code:
        return jsonify({'success': False, 'error': '请提供恢复码'}), 400
    if not new_secret:
        return jsonify({'success': False, 'error': '请提供新的 API 密钥'}), 400

    current_config = load_config()
    stored_recovery_code = str(current_config.get('app', {}).get('recovery_code', '') or '').strip()
    if not stored_recovery_code:
        return jsonify({'success': False, 'error': '当前未配置恢复码，无法重置密钥'}), 400

    if not _is_recovery_code_valid(stored_recovery_code, recovery_code):
        return jsonify({'success': False, 'error': '恢复码无效'}), 401

    merged_config = copy.deepcopy(current_config)
    if 'app' not in merged_config:
        merged_config['app'] = {}
    merged_config['app']['secret'] = new_secret
    new_recovery_code = _ensure_recovery_code(merged_config, force_new=True)

    try:
        save_config(merged_config)

        recovery_code_sent = False
        recovery_code_send_error = ''
        if new_recovery_code:
            recovery_code_sent, recovery_code_send_error = _try_send_recovery_code_email(
                merged_config,
                new_recovery_code,
                '恢复码重置后生成',
            )

        _invalidate_all_session_tokens()
        session_token, expires_at = _issue_session_token()

        logger.info(f'{LOG_WEB_AUTH} 恢复码重置成功，已签发新的会话 token')
        response_payload = {
            'success': True,
            'message': '密钥已重置',
            'secret': new_secret,
            'auth': {
                'session_token': session_token,
                'expires_at': expires_at,
                'token_type': 'session',
            },
            'recovery_code': new_recovery_code,
            'recovery_code_sent': recovery_code_sent,
            'config': filter_sensitive_config(load_config(), include_secret=False),
        }
        if recovery_code_send_error:
            response_payload['recovery_code_send_error'] = recovery_code_send_error

        return jsonify(response_payload)
    except Exception as exc:
        logger.exception(f'{LOG_WEB_AUTH} 恢复码重置失败：{exc}')
        return jsonify({'success': False, 'error': f'重置失败：{exc}'}), 500


@app.route('/api/auth/recovery-email', methods=['POST'])
def send_recovery_email():
    """通过已配置邮箱发送当前恢复码。"""
    allowed, error_msg = check_access_control()
    if not allowed:
        return jsonify({'success': False, 'error': error_msg}), 403

    if _is_first_time_setup():
        return jsonify({'success': False, 'error': '请先设置 API 认证密钥'}), 400

    current_config = load_config()
    success, send_message = _send_recovery_email_if_configured(current_config, '邮箱恢复请求')
    if not success:
        status_code = 400 if '没有设置邮箱信息' in send_message or '当前未配置恢复码' in send_message else 500
        return jsonify({'success': False, 'error': send_message}), status_code

    logger.info(f'{LOG_WEB_AUTH} 已发送邮箱恢复邮件')
    return jsonify({
        'success': True,
        'message': '已向邮箱发送验证信息，请查收邮件',
    })


@app.route('/api/notifications/test', methods=['POST'])
@require_auth
def test_notification_email():
    """测试邮件通知配置是否可用。"""
    try:
        allowed, error_msg = check_access_control()
        if not allowed:
            return jsonify({'success': False, 'message': error_msg}), 403

        data = request.get_json(silent=True) or {}
        current_config = load_config()
        merged_notifications = copy.deepcopy(current_config.get('notifications', {}))
        incoming_notifications = data.get('notifications', {})
        if isinstance(incoming_notifications, dict):
            merged_notifications.update(incoming_notifications)

        normalized_notifications = normalize_notification_settings(merged_notifications)
        subject = str(data.get('subject', 'Auto PT 邮件通知测试') or '').strip() or 'Auto PT 邮件通知测试'
        message = str(data.get('message', '') or '').strip() or '这是一封来自 Auto PT Downloader 的测试邮件，用于验证邮件通知配置是否可用。'

        success, send_message = send_email_notification(
            normalized_notifications,
            subject=subject,
            text=message,
            require_enabled=False,
        )
        if success:
            return jsonify({'success': True, 'message': send_message or '测试邮件已发送'})

        return jsonify({'success': False, 'message': send_message or '邮件发送失败'}), 400
    except Exception as exc:
        logger.exception(f'{LOG_WEB_CONFIG} 邮件通知测试失败：{exc}')
        return jsonify({'success': False, 'message': f'测试失败：{exc}'}), 500


def filter_sensitive_config(cfg, include_secret=False):
    """过滤配置中的敏感信息
    
    Args:
        cfg: 配置对象
        include_secret: 兼容旧调用参数，当前不再返回 secret 明文
    """
    if not cfg:
        return {}

    secret_value = cfg.get('app', {}).get('secret', '')
    env_secret = os.getenv('APP_SECRET', '')
    placeholder_secrets = {
        '',
        'auto-pt-default-secret-change-me',
        'YOUR_SECRET_KEY_HERE_CHANGE_ME',
    }
    auth_configured = (secret_value not in placeholder_secrets) or bool(env_secret)
    secret_source = _get_secret_source(cfg)
    recovery_code_configured = bool(str(cfg.get('app', {}).get('recovery_code', '') or '').strip())
    logging_settings = cfg.get('logging', {}) if isinstance(cfg.get('logging', {}), dict) else {}
    logging_level = str(logging_settings.get('level', cfg.get('log_level', 'INFO')) or 'INFO').upper()
    notification_settings = normalize_notification_settings(cfg.get('notifications', {}))
    notification_configured = notification_settings_complete(notification_settings)
    qb_password_configured = bool(str(cfg.get('qbittorrent', {}).get('password', '') or '').strip())
    
    app_config = {
        'version': cfg.get('app', {}).get('version', 'unknown'),
        # 系统设置相关配置
        'access_control': normalize_access_mode(cfg.get('app', {}).get('access_control', 'lan')),
        'allowed_ips': cfg.get('app', {}).get('allowed_ips', []),
        'web_port': cfg.get('app', {}).get('web_port', 5000),
        'auth_configured': auth_configured,
        'secret_source': secret_source,
        'recovery_code_configured': recovery_code_configured,
    }
    
    safe_config = {
        'app': app_config,
        'qbittorrent': {
            'host': cfg.get('qbittorrent', {}).get('host') or cfg.get('qbittorrent', {}).get('url', ''),
            'username': cfg.get('qbittorrent', {}).get('username', ''),
            # 不返回 password
            'save_path': cfg.get('qbittorrent', {}).get('save_path', ''),
            'category': cfg.get('qbittorrent', {}).get('category', ''),
            'configured': qb_password_configured,
        },
        'schedule': cfg.get('schedule', {}),
        'log_level': logging_level,
        'logging': {
            'level': logging_level,
        },
        'notifications': {
            'enabled': notification_settings.get('enabled', False),
            'download_start_enabled': notification_settings.get('download_start_enabled', False),
            'download_complete_enabled': notification_settings.get('download_complete_enabled', False),
            'smtp_host': notification_settings.get('smtp_host', ''),
            'smtp_port': notification_settings.get('smtp_port', 465),
            'transport_mode': notification_settings.get('transport_mode', 'ssl'),
            'sender_email': notification_settings.get('sender_email', ''),
            'sender_name': notification_settings.get('sender_name', ''),
            'smtp_username': notification_settings.get('smtp_username', ''),
            'recipient_email': notification_settings.get('recipient_email', ''),
            'configured': notification_configured,
        },
        'pt_sites': []
    }
    
    # 处理站点配置，过滤敏感信息
    for site in cfg.get('pt_sites', []):
        safe_site = {
            'name': site.get('name', ''),
            'base_url': site.get('base_url', ''),
            'schedule': site.get('schedule', {}),
            'download_settings': site.get('download_settings', {}),
            # 不返回：rss_url, passkey, rss_key
        }
        safe_config['pt_sites'].append(safe_site)
    
    return safe_config


def build_site_schedule_status(config):
    """构建站点级调度状态，供状态接口和前端展示复用。"""
    site_statuses = []

    for site in config.pt_sites:
        schedule = site.get('schedule', {}) or {}
        download_settings = site.get('download_settings', {}) or {}

        check_interval = schedule.get('interval', 300)
        cleanup_interval = schedule.get('cleanup_interval', 0)
        cleanup_follows_check_interval = cleanup_interval <= 0
        effective_cleanup_interval = check_interval if cleanup_follows_check_interval else cleanup_interval

        site_statuses.append({
            'name': site.get('name', 'unknown'),
            'enabled': site.get('enabled', True),
            'check_interval': check_interval,
            'cleanup_interval': cleanup_interval,
            'effective_cleanup_interval': effective_cleanup_interval,
            'cleanup_follows_check_interval': cleanup_follows_check_interval,
            'auto_download': download_settings.get('auto_download', False),
            'auto_delete': download_settings.get('auto_delete', False),
        })

    return site_statuses


def _normalize_site_name(site_name) -> str:
    """统一清洗站点名称输入。"""
    return site_name.strip() if isinstance(site_name, str) else ''


def _prune_legacy_single_site_config(config: dict) -> dict:
    """多站点配置存在时，移除旧版 pt.mteam 残留，避免再次写回配置文件。"""
    if not isinstance(config, dict):
        return config

    cleaned_config = dict(config)
    pt_sites = cleaned_config.get('pt_sites')
    if not isinstance(pt_sites, list) or not pt_sites:
        return cleaned_config

    pt_config = cleaned_config.get('pt')
    if not isinstance(pt_config, dict) or 'mteam' not in pt_config:
        return cleaned_config

    cleaned_pt_config = dict(pt_config)
    cleaned_pt_config.pop('mteam', None)
    if cleaned_pt_config:
        cleaned_config['pt'] = cleaned_pt_config
    else:
        cleaned_config.pop('pt', None)

    return cleaned_config


def _resolve_site_config(config, requested_site_name: str = ''):
    """根据请求解析站点配置，兼容多站点和旧版单站点配置。"""
    site_name = _normalize_site_name(requested_site_name)
    if site_name:
        return config.get_site_by_name(site_name)

    if config.pt_sites:
        enabled_sites = config.get_enabled_sites()
        if len(enabled_sites) == 1:
            return enabled_sites[0]

        if len(config.pt_sites) == 1:
            return config.pt_sites[0]

        return None

    legacy_site = config.get('pt.mteam', {}) or {}
    if legacy_site and any(
        legacy_site.get(key) for key in ('base_url', 'rss_url', 'passkey', 'uid')
    ):
        resolved_legacy_site = dict(legacy_site)
        resolved_legacy_site.setdefault('name', 'mteam')
        resolved_legacy_site.setdefault('type', 'mteam')
        return resolved_legacy_site

    return None


def _validate_site_rss_url(site_config) -> str:
    """验证站点 RSS 地址，避免空串直接落到 requests 层报错。"""
    if not site_config:
        return '未找到站点配置'

    site_name = site_config.get('name', 'unknown')
    rss_url = str(site_config.get('rss_url', '') or '').strip()
    if not rss_url:
        return f'站点 {site_name} 未配置 RSS 地址'

    parsed = urlparse(rss_url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return f'站点 {site_name} 的 RSS 地址格式无效，请填写完整的 http/https 链接'

    return ''


def _create_site_client(site_config):
    """按站点类型创建客户端，统一复用 runner 中的工厂逻辑。"""
    from src.runner import create_site_client

    return create_site_client(site_config.get('type', 'mteam'), site_config)


def _build_download_link(link: str, site_config) -> str:
    """按站点配置补全下载链接所需的 passkey。"""
    download_link = (link or '').strip()
    if not download_link:
        return ''

    passkey = ''
    if isinstance(site_config, dict):
        passkey = str(site_config.get('passkey', '') or '').strip()

    if passkey and "passkey=" not in download_link and "sign=" not in download_link:
        sep = "&" if "?" in download_link else "?"
        download_link = f"{download_link}{sep}passkey={passkey}"

    return download_link


def _get_site_tags(site_config) -> list:
    """统一解析站点 tags 配置。"""
    if not isinstance(site_config, dict):
        return ['auto_pt']

    site_tags_from_config = site_config.get('tags', [])
    if isinstance(site_tags_from_config, str):
        site_tags = [tag.strip() for tag in site_tags_from_config.split(',') if tag.strip()]
    elif isinstance(site_tags_from_config, list):
        site_tags = [tag for tag in site_tags_from_config if tag]
    else:
        site_tags = []

    return site_tags or ['auto_pt']

# ==================== 安全认证相关 ====================


def load_config():
    """统一委托 src.config 加载配置，并补齐 Web 层兼容归一化。"""
    from src.config import Config as RuntimeConfig

    config = copy.deepcopy(RuntimeConfig(str(CONFIG_FILE))._config)
    config = _prune_legacy_single_site_config(config)

    # 统一访问控制模式，兼容旧配置值
    if 'app' in config:
        config['app']['access_control'] = normalize_access_mode(
            config['app'].get('access_control', 'lan')
        )
    
    return config


def _strip_runtime_only_config_fields(config):
    """移除只用于前端展示的运行态字段。"""
    if not isinstance(config, dict):
        return config

    cleaned_config = copy.deepcopy(config)
    cleaned_config.pop('auth', None)

    app_config = cleaned_config.get('app')
    if isinstance(app_config, dict):
        app_config.pop('auth_configured', None)
        app_config.pop('secret_source', None)
        app_config.pop('recovery_code_configured', None)

    notifications_config = cleaned_config.get('notifications')
    if isinstance(notifications_config, dict):
        notifications_config.pop('configured', None)

    qb_config = cleaned_config.get('qbittorrent')
    if isinstance(qb_config, dict):
        qb_config.pop('configured', None)

    return cleaned_config


def _sync_logging_config_fields(config):
    """同步顶层 log_level 与 logging.level，避免页面显示和实际生效值不一致。"""
    if not isinstance(config, dict):
        return config

    synced_config = copy.deepcopy(config)
    raw_logging = synced_config.get('logging')
    logging_config = raw_logging if isinstance(raw_logging, dict) else {}
    level = str(logging_config.get('level', synced_config.get('log_level', 'INFO')) or 'INFO').upper()
    logging_config['level'] = level
    synced_config['logging'] = logging_config
    synced_config['log_level'] = level
    return synced_config


def save_config(config):
    """统一委托 src.config 保存配置，保留 Web 层日志与异常包装。"""
    try:
        from src.config import save_config as persist_config

        normalized_config = _prune_legacy_single_site_config(_strip_runtime_only_config_fields(config))
        normalized_config = _sync_logging_config_fields(normalized_config)
        persist_config(normalized_config, str(CONFIG_FILE))
    except Exception as e:
        logger.exception(f"{LOG_WEB_CONFIG} 保存失败：{e}")
        raise


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # 兼容旧格式
            if "records" in data:
                return data
            elif "ids" in data:
                # 旧格式转换为新格式
                return {
                    "records": {tid: {"title": "", "hash": "", "added_at": "", "progress_history": []} for tid in data.get("ids", [])},
                    "updated": data.get("updated", "")
                }
    return {"records": {}, "updated": ""}


def save_history(history):
    dir_name = os.path.dirname(HISTORY_FILE)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2)


def load_logs():
    try:
        log_file = _get_active_log_file()
        logger.debug(f"{LOG_WEB_LOGS} 日志文件路径：{log_file}, 存在：{log_file.exists()}")
        if not log_file.exists():
            return ''

        with log_file.open('rb') as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            start_pos = max(file_size - MAX_LOG_TAIL_BYTES, 0)
            f.seek(start_pos)

            if start_pos > 0:
                # 从文件中间截断时，丢弃第一行残缺内容，避免首行乱码或半行。
                f.readline()

            content_bytes = f.read()

        content = content_bytes.decode('utf-8', errors='replace')
        lines = content.splitlines()
        tail_lines = lines[-MAX_LOG_TAIL_LINES:]
        logger.debug(f"{LOG_WEB_LOGS} 已加载 {len(tail_lines)} 行 / {len(content_bytes)} 字节")
        return '\n'.join(tail_lines)
    except Exception as e:
        logger.exception(f"{LOG_WEB_LOGS} 加载失败：{e}")
        return f"Error loading logs: {e}"


@app.route('/')
def index():
    # 先检查访问控制
    allowed, error_msg = check_access_control()
    if not allowed:
        return f"拒绝访问: {error_msg}", 403
    
    response = send_from_directory('static', 'index.html')
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/favicon.ico')
def favicon():
    """兼容浏览器默认 favicon 请求，复用首页 logo 风格图标。"""
    return send_from_directory(app.static_folder, 'favicon.svg')


@app.route('/api/config', methods=['GET'])
@require_auth
def get_config():
    # 先检查访问控制
    allowed, error_msg = check_access_control()
    if not allowed:
        return jsonify({'success': False, 'error': error_msg}), 403
    
    config = load_config()
    logger.debug(f"{LOG_WEB_CONFIG} 读取配置：{CONFIG_FILE}, 存在：{os.path.exists(CONFIG_FILE)}")
    safe_config = filter_sensitive_config(config, include_secret=False)
    return jsonify({'success': True, 'config': safe_config})


@app.route('/api/config/file', methods=['GET'])
@require_auth
def get_config_file_info():
    """获取配置文件信息（用于调试）"""
    return jsonify({
        'path': str(CONFIG_FILE),
        'exists': os.path.exists(CONFIG_FILE),
        'size': os.path.getsize(CONFIG_FILE) if os.path.exists(CONFIG_FILE) else 0,
        'mtime': os.path.getmtime(CONFIG_FILE) if os.path.exists(CONFIG_FILE) else 0
    })


@app.route('/api/config', methods=['POST'])
@require_auth
def update_config():
    new_config = request.get_json(silent=True) or {}
    new_config = _strip_runtime_only_config_fields(new_config)
    old_config = load_config()
    old_secret = old_config.get('app', {}).get('secret', '')
    new_secret = new_config.get('app', {}).get('secret', '') if isinstance(new_config, dict) else ''
    secret_changed = bool(new_secret) and new_secret != old_secret
    first_time_setup = _is_first_time_setup()
    issued_auth = None
    recovery_code = ''
    
    # 首次设置密钥时（未认证），只允许设置 app.secret
    if first_time_setup:
        # 提取 app.secret，其他字段忽略
        new_secret = new_config.get('app', {}).get('secret', '')
        
        if not new_secret:
            return jsonify({'success': False, 'error': '请设置 API 认证密钥'}), 400
        
        # 只更新 secret，保留其他所有原有配置
        merged_config = old_config.copy()
        if 'app' not in merged_config:
            merged_config['app'] = {}
        merged_config['app']['secret'] = new_secret
        recovery_code = _ensure_recovery_code(merged_config, force_new=True)
        secret_changed = new_secret != old_secret
        
        changes = [f"新增设置：app.secret", "生成恢复码：app.recovery_code"]
    else:
        # 正式认证后，允许完整配置更新
        # 关键修复：深度合并配置，保留未修改的字段
        # 特别是 pt_sites 等站点配置必须保留
        merged_config = deep_merge_configs(old_config, new_config)
        merged_config = _prune_legacy_single_site_config(merged_config)
        merged_config = normalize_qbittorrent_config(merged_config)
        
        # 安全处理：如果密码为空且原密码存在，保留原密码
        if merged_config.get('qbittorrent', {}).get('password') == '':
            if 'qbittorrent' not in merged_config:
                merged_config['qbittorrent'] = {}
            merged_config['qbittorrent']['password'] = old_config.get('qbittorrent', {}).get('password', '')
        
        changes = []
        
        def compare_configs(old, new, prefix=''):
            for key in new:
                path = f"{prefix}.{key}" if prefix else key
                if key not in old:
                    changes.append(f"新增设置：{path}")
                elif old[key] != new[key]:
                    if isinstance(old[key], dict) and isinstance(new[key], dict):
                        compare_configs(old[key], new[key], path)
                    else:
                        old_val = old[key] if old[key] is not None else '空'
                        new_val = new[key] if new[key] is not None else '空'
                        changes.append(f"修改设置：{path}")
            for key in old:
                if key not in new:
                    path = f"{prefix}.{key}" if prefix else key
                    changes.append(f"删除设置：{path}")
        
        compare_configs(old_config, merged_config)

        # 兼容旧配置：如果之前没有恢复码，而这次修改了密钥，则自动补发一个。
        if secret_changed and not str(old_config.get('app', {}).get('recovery_code', '') or '').strip():
            recovery_code = _ensure_recovery_code(merged_config, force_new=True)
            changes.append("生成恢复码：app.recovery_code")
    
    try:
        save_config(merged_config)
        reload_logging(merged_config.get('logging', {}))
        recovery_code_sent = False
        recovery_code_send_error = ''
        if recovery_code:
            recovery_code_sent, recovery_code_send_error = _try_send_recovery_code_email(
                merged_config,
                recovery_code,
                '首次设置时生成' if first_time_setup else '密钥更新后生成',
            )
        if secret_changed:
            _invalidate_all_session_tokens()
            session_token, expires_at = _issue_session_token()
            issued_auth = {
                'session_token': session_token,
                'expires_at': expires_at,
                'token_type': 'session',
            }
        logger.info(f"{LOG_WEB_CONFIG} 配置已保存到：{CONFIG_FILE}")
        
        # 验证保存是否成功 - 检查关键字段
        saved_config = load_config()
        failed_fields = []
        
        # 验证 qbittorrent.host
        if saved_config.get('qbittorrent', {}).get('host') != merged_config.get('qbittorrent', {}).get('host'):
            failed_fields.append(f"qbittorrent.host")

        # 验证 pt_sites 是否存在（关键！）
        if 'pt_sites' in merged_config and 'pt_sites' not in saved_config:
            failed_fields.append("pt_sites (重要：站点配置丢失)")
        
        if failed_fields:
            logger.error(f"{LOG_WEB_CONFIG} 配置保存后验证失败！以下字段未正确保存：{', '.join(failed_fields)}")
            return jsonify({'success': False, 'message': f'配置保存失败，请检查文件权限。未保存的字段：{", ".join(failed_fields)}'})
    except Exception as e:
        logger.exception(f"{LOG_WEB_CONFIG} 保存异常：{e}")
        return jsonify({'success': False, 'message': f'保存失败：{str(e)}'})
    
    if changes:
        for change in changes:
            logger.info(f"{LOG_WEB_CONFIG} {change}")
    
    # 返回保存后的配置（不再包含 secret 明文）
    saved_config = load_config()
    safe_config = filter_sensitive_config(saved_config, include_secret=False)
    
    response_payload = {
        'success': True,
        'message': '配置已保存',
        'changes': changes,
        'config': safe_config,
    }
    if issued_auth:
        response_payload['auth'] = issued_auth
    if recovery_code:
        response_payload['recovery_code'] = recovery_code
        response_payload['recovery_code_sent'] = recovery_code_sent
        if recovery_code_send_error:
            response_payload['recovery_code_send_error'] = recovery_code_send_error

    return jsonify(response_payload)


def _merge_pt_sites(old_sites, new_sites):
    """按站点名合并站点列表，避免安全裁剪后的 payload 覆盖掉站点详情。"""
    if not isinstance(new_sites, list):
        return new_sites

    if not new_sites:
        return old_sites if isinstance(old_sites, list) else []

    if not isinstance(old_sites, list) or not old_sites:
        return new_sites

    old_sites_by_name = {}
    old_site_order = []
    old_sites_without_name = []

    for site in old_sites:
        if isinstance(site, dict):
            site_name = _normalize_site_name(site.get('name'))
            if site_name and site_name not in old_sites_by_name:
                old_sites_by_name[site_name] = site
                old_site_order.append(site_name)
                continue
        old_sites_without_name.append(site)

    merged_sites = []
    seen_old_site_names = set()

    for site in new_sites:
        if not isinstance(site, dict):
            merged_sites.append(site)
            continue

        site_name = _normalize_site_name(site.get('name'))
        old_site = old_sites_by_name.get(site_name)
        if not old_site:
            merged_sites.append(site)
            continue

        merged_sites.append(deep_merge_configs(old_site, site))
        seen_old_site_names.add(site_name)

    # /api/config 并不是站点管理入口，未出现在 payload 中的旧站点继续保留。
    for site_name in old_site_order:
        if site_name not in seen_old_site_names:
            merged_sites.append(old_sites_by_name[site_name])

    merged_sites.extend(old_sites_without_name)
    return merged_sites


def deep_merge_configs(old, new):
    """
    深度合并配置对象
    保留 old 中未被 new 覆盖的字段（特别是 pt_sites）
    """
    if not isinstance(old, dict) or not isinstance(new, dict):
        return new
    
    result = old.copy()
    
    for key, value in new.items():
        if key == 'pt_sites':
            result[key] = _merge_pt_sites(result.get(key, []), value)
        elif key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # 递归合并字典
            result[key] = deep_merge_configs(result[key], value)
        else:
            # 其他字段直接覆盖
            result[key] = value
    
    return result


@app.route('/api/history', methods=['GET'])
@require_auth
def get_history():
    from src.history import DownloadHistory
    from datetime import datetime, timedelta
    
    try:
        history = DownloadHistory()
        all_records = history.get_all()
        
        # 获取筛选参数
        try:
            page = int(request.args.get('page', 1) or '1')
            page_size = int(request.args.get('page_size', 20) or '20')
            search = request.args.get('search', '')
            days = int(request.args.get('days', 0) or '0')
            include_hidden = str(request.args.get('include_hidden', '0')).strip().lower() in {
                '1', 'true', 'yes', 'on'
            }
        except:
            page = 1
            page_size = 20
            search = ''
            days = 0
            include_hidden = False
        
        # 过滤记录
        filtered_records = {}
        now = datetime.now()
        
        for tid, info in all_records.items():
            # 默认跳过隐藏的记录，按需返回给前端做精细恢复
            if info.get('hidden', False) and not include_hidden:
                continue
            
            # 搜索过滤
            if search:
                title = info.get('title', '')
                if search.lower() not in title.lower() and search.lower() not in tid.lower():
                    continue
            
            # 时间过滤
            if days > 0:
                added_at = info.get('added_at', '')
                if added_at:
                    try:
                        record_time = datetime.fromisoformat(added_at.replace('Z', '+00:00'))
                        if (now - record_time).days > days:
                            continue
                    except:
                        continue
            
            filtered_records[tid] = info
        
        # 分页
        total = len(filtered_records)
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 1
        start = (page - 1) * page_size
        end = start + page_size
        
        # 返回分页数据
        page_records = list(filtered_records.items())[start:end]
        
        return jsonify({
            'success': True,
            'records': [
                {
                    'id': tid,
                    'title': info.get('title', ''),
                    'hash': info.get('hash', ''),
                    'site_name': info.get('site_name', ''),
                    'category': info.get('category', ''),
                    'size': info.get('size', 0),
                    'status': (
                        'deleted'
                        if info.get('deleted_at') and str(info.get('status', '') or '').strip().lower() != 'deleted'
                        else info.get('status', 'downloading')
                    ),
                    'hidden': bool(info.get('hidden', False)),
                    'added_at': info.get('added_at', ''),
                    'completed_time': info.get('completed_time'),
                    'progress_history': info.get('progress_history', []),
                    'deleted_at': info.get('deleted_at'),
                    'deleted_reason': info.get('deleted_reason'),
                    'deleted_source': info.get('deleted_source'),
                    'deleted_from_status': info.get('deleted_from_status'),
                    'deleted_files': bool(info.get('deleted_files', False)),
                }
                for tid, info in page_records
            ],
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages
        })
    except Exception as e:
        logger.exception(f"{LOG_WEB_HISTORY} 获取历史记录失败：{e}")
        return jsonify({
            'success': False,
            'message': '获取历史记录失败'
        }), 500


def _get_torrent_status(torrent_hash, title, qb_status, added_at=None, progress_history=None):
    """判断种子状态 - 基于进度历史和 QB 状态"""
    from datetime import datetime, timedelta
    
    # ==================== 第一步：检查是否在 QB 中 ====================
    
    # 1.1 用 hash 精确查询
    if torrent_hash and torrent_hash in qb_status:
        t = qb_status[torrent_hash]
        progress = t.get('progress', 0)
        state = t.get('state', '')
        return qb_state_to_status(progress, state)
    
    # 1.2 hash 查询不到，用标题模糊匹配（处理重新下载的情况）
    if title:
        matched = _match_torrent_by_title(title, qb_status)
        if matched:
            return qb_state_to_status(matched['progress'], matched['state'])
    
    # ==================== 第二步：不在 QB 中，根据历史判断 ====================
    
    # 2.1 有进度历史 → 根据最高进度判断
    if progress_history and len(progress_history) > 0:
        max_progress = max(p.get('progress', 0) for p in progress_history)
        if max_progress >= 1.0:
            return {'state': 'completed', 'label': '已完成', 'color': 'green'}
        else:
            return {'state': 'cancelled', 'label': '已取消', 'color': 'red'}
    
    # 2.2 无进度历史，根据添加时间判断（新记录可能刚下载就被删除）
    if added_at:
        try:
            record_time = datetime.fromisoformat(added_at.replace('Z', '+00:00').replace('+00:00', ''))
            hours_ago = (datetime.now() - record_time).total_seconds() / 3600
            if hours_ago < 2:  # 2 小时内的记录
                return {'state': 'cancelled', 'label': '已取消', 'color': 'red'}
        except:
            pass
    
    # 2.3 其他情况（旧记录）→ 默认已完成
    return {'state': 'completed', 'label': '已完成', 'color': 'green'}


def _qb_state_to_status(progress, state):
    """兼容旧调用点的 qB 状态转换包装器。"""
    return qb_state_to_status(progress, state)


def _match_torrent_by_title(title, qb_status):
    """通过标题关键词匹配 QB 中的种子"""
    import re
    
    def extract_keywords(t):
        episodes = re.findall(r'(?:S\d{1,2}E\d{1,2}|EP\d{1,3}|第\d{1,2}集)', t, re.IGNORECASE)
        words = re.findall(r'[a-zA-Z0-9一-龥]+', t.lower())
        skip_words = {'s', 'e', 'hd', 'sd', 'bluray', 'web', 'dl', 'mweb', 'the', 'a', 'an', 'p'}
        other_words = set(w for w in words if len(w) > 2 and w not in skip_words)
        return set(episodes) | other_words
    
    title_keywords = extract_keywords(title)
    
    for hash_key, t in qb_status.items():
        qb_title = t.get('name', '')
        qb_keywords = extract_keywords(qb_title)
        
        # 计算关键词重叠度
        common = title_keywords & qb_keywords
        if len(common) >= 3:  # 至少 3 个共同关键词
            return t
    
    return None



@app.route('/api/history/<torrent_id>', methods=['DELETE'])
@require_auth
def delete_single_history(torrent_id):
    from src.history import DownloadHistory
    from urllib.parse import parse_qs
    history = DownloadHistory()
    
    if torrent_id in history._history:
        # 检查是否是彻底删除
        action = request.args.get('action', 'hide')
        
        if action == 'delete':
            # 彻底删除
            del history._history[torrent_id]
            history._save()
            return jsonify({'success': True, 'message': '已彻底删除'})
        else:
            # 仅隐藏
            history._history[torrent_id]['hidden'] = True
            history._save()
            return jsonify({'success': True, 'message': '已从列表隐藏'})
    else:
        return jsonify({'success': False, 'message': '记录不存在'})


@app.route('/api/history/<torrent_id>/restore', methods=['POST'])
@require_auth
def restore_single_history(torrent_id):
    from src.history import DownloadHistory
    history = DownloadHistory()
    
    if torrent_id in history._history:
        # 移除 hidden 标记
        if 'hidden' in history._history[torrent_id]:
            del history._history[torrent_id]['hidden']
        history._save()
        return jsonify({'success': True, 'message': '已恢复'})
    else:
        return jsonify({'success': False, 'message': '记录不存在'})


@app.route('/api/history/hide', methods=['POST'])
@require_auth
def hide_history_batch():
    """批量隐藏历史记录（仅从列表隐藏，不删除种子）"""
    from src.history import DownloadHistory
    
    data = request.get_json()
    ids = data.get('ids', [])
    
    history = DownloadHistory()
    hidden_count = 0
    
    for torrent_id in ids:
        if torrent_id in history._history:
            history._history[torrent_id]['hidden'] = True
            hidden_count += 1
    
    history._save()
    
    return jsonify({'success': True, 'hidden': hidden_count})


@app.route('/api/history/restore', methods=['POST'])
@require_auth
def restore_history_batch():
    """恢复隐藏的历史记录，支持全部恢复或按 IDs 恢复"""
    from src.history import DownloadHistory

    data = request.get_json(silent=True) or {}
    ids = data.get('ids', [])
    history = DownloadHistory()
    restored_count = 0

    if ids:
        for torrent_id in ids:
            if torrent_id in history._history and history._history[torrent_id].get('hidden', False):
                del history._history[torrent_id]['hidden']
                restored_count += 1
    else:
        for torrent_id in list(history._history.keys()):
            if history._history[torrent_id].get('hidden', False):
                del history._history[torrent_id]['hidden']
                restored_count += 1
    
    history._save()
    
    return jsonify({'success': True, 'restored': restored_count})


@app.route('/api/history', methods=['DELETE'])
@require_auth
def delete_history():
    """
    删除历史记录
    支持三种方式:
    1. 批量删除指定 IDs: DELETE /api/history {"ids": ["123", "456"]}
    2. 按天数删除：DELETE /api/history?days=30
    3. 全部删除：DELETE /api/history?days=0
    """
    from src.history import DownloadHistory
    from datetime import datetime, timedelta
    
    history = DownloadHistory()
    
    # 检查是否是批量删除（JSON body 中有 ids）
    if request.is_json and request.json:
        ids = request.json.get('ids', [])
        if ids:
            deleted = 0
            for tid in ids:
                if tid in history._history:
                    del history._history[tid]
                    deleted += 1
            history._save()
            return jsonify({
                'success': True,
                'deleted': deleted,
                'message': f'成功删除 {deleted} 条记录'
            })
    
    # 按天数删除
    try:
        days = int(request.args.get('days', '0') or '0')
    except:
        days = 0
    
    if days > 0:
        # 删除指定天数前的记录
        cutoff = datetime.now() - timedelta(days=days)
        to_delete = []
        for tid, info in history._history.items():
            added_at = info.get('added_at', '')
            if added_at:
                try:
                    record_time = datetime.fromisoformat(added_at.replace('Z', '+00:00'))
                    if record_time < cutoff:
                        to_delete.append(tid)
                except:
                    pass
        for tid in to_delete:
            del history._history[tid]
        history._save()
        return jsonify({
            'success': True,
            'deleted': len(to_delete),
            'message': f'已删除 {len(to_delete)} 条{days}天前的记录'
        })
    else:
        # 清空所有
        count = len(history._history)
        history._history = {}
        history._save()
        return jsonify({
            'success': True,
            'deleted': count,
            'message': '已清空所有历史记录'
        })


@app.route('/api/logs', methods=['GET'])
@require_auth
def get_logs():
    logs = load_logs()
    return jsonify({'logs': logs})


@app.route('/api/logs', methods=['DELETE'])
@require_auth
def clear_logs():
    try:
        log_file = _get_active_log_file()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write('')
        return jsonify({'success': True, 'message': '日志已清除'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/run', methods=['POST'])
@require_auth
def api_run_check():
    """执行一次种子检查"""
    try:
        from src.config import Config
        from src.runner import run_check, sync_download_completion_notifications
        config = Config()
        _, count = run_check(config)
        sync_download_completion_notifications(config)
        return jsonify({'success': True, 'added': count, 'message': f'检查完成，新增 {count} 个种子'})
    except Exception as e:
        logger.exception(f"{LOG_WEB_API} 执行检查异常：{e}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/status', methods=['GET'])
@require_auth
def get_status():
    """获取系统运行状态"""
    try:
        from src.config import Config
        from src.history import DownloadHistory
        from src.qbittorrent import QBittorrentClient
        
        config = Config()
        global_schedule = config.get('schedule', {}) or {}
        site_schedules = build_site_schedule_status(config)
        
        # 获取 QB 状态
        qb_connected = False
        qb_version = None
        try:
            qb = QBittorrentClient(
                host=get_qbittorrent_host(config.qbittorrent),
                username=config.qbittorrent.get('username', ''),
                password=config.qbittorrent.get('password', '')
            )
            qb_version = qb.get_version()
            qb_connected = qb_version is not None
        except:
            pass
        
        # 获取历史统计
        history = DownloadHistory()
        
        # 获取日志文件状态
        log_size = 0
        log_file = _get_active_log_file()
        if os.path.exists(log_file):
            log_size = os.path.getsize(log_file)
        
        return jsonify({
            'success': True,
            'qb_connected': qb_connected,
            'qb_version': qb_version,
            'history_count': history.count(),
            'log_size': log_size,
            'config_file': str(CONFIG_FILE),
            'config_file_exists': os.path.exists(CONFIG_FILE),
            'global_schedule': global_schedule,
            'check_interval': global_schedule.get('interval', 300),
            'cleanup_interval': global_schedule.get('cleanup_interval', 1800),
            'auto_delete': any(site.get('auto_delete', False) for site in site_schedules),
            'site_schedules': site_schedules,
            'sites_count': len(site_schedules),
            'enabled_sites_count': len([site for site in site_schedules if site.get('enabled')]),
        })
    except Exception as e:
        logger.exception(f"{LOG_WEB_API} 获取状态异常：{e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/version', methods=['GET'])
def get_version():
    """获取应用版本号"""
    return jsonify({'success': True, 'version': '1.2.1'})


@app.route('/api/stats', methods=['GET'])
@require_auth
def get_stats():
    """获取统计信息（qb 状态、历史数量等）"""
    try:
        from src.config import Config
        from src.history import DownloadHistory
        from src.qbittorrent import QBittorrentClient
        
        config = Config()
        history = DownloadHistory()
        global_schedule = config.get('schedule', {}) or {}
        site_schedules = build_site_schedule_status(config)
        
        # 获取 QB 状态
        qb_connected = False
        qb_downloading = 0
        qb_completed = 0
        qb_seeding = 0
        qb_paused = 0
        qb_total = 0
        qb_ratio = 0.0
        try:
            qb = QBittorrentClient(
                host=get_qbittorrent_host(config.qbittorrent),
                username=config.qbittorrent.get('username', ''),
                password=config.qbittorrent.get('password', '')
            )
            qb_version = qb.get_version()
            qb_connected = qb_version is not None
            if qb_connected:
                torrents = qb.get_torrents()
                qb_state_counts = summarize_qb_torrent_states(torrents)
                qb_downloading = qb_state_counts.get('downloading', 0)
                qb_completed = qb_state_counts.get('completed', 0)
                qb_seeding = qb_state_counts.get('seeding', 0)
                qb_paused = qb_state_counts.get('paused', 0)
                qb_total = len(torrents)
                qb_ratio = 0.0  # 需要计算总分享率
        except:
            pass
        
        history_stats = history.get_completion_statistics()
        total_count = history_stats['total_records']
        total_completed = history_stats['total_completed']
        
        return jsonify({
            'success': True,
            'history_stats': history_stats,
            'download_trend': {
                'today': history_stats['today_completed'],
                'week': history_stats['week_completed'],
                'total': total_completed
            },
            'qb_stats': {
                'downloading': qb_downloading,
                'completed': qb_completed,
                'seeding': qb_seeding,
                'paused': qb_paused,
                'total': qb_total,
                'ratio': qb_ratio
            },
            'qb_connected': qb_connected,
            'history_count': total_count,
            'history_completed_count': total_completed,
            'global_schedule': global_schedule,
            'check_interval': global_schedule.get('interval', 300),
            'cleanup_interval': global_schedule.get('cleanup_interval', 1800),
            'site_schedules': site_schedules,
            'sites_count': len(site_schedules),
            'enabled_sites_count': len([site for site in site_schedules if site.get('enabled')]),
        })
    except Exception as e:
        logger.exception(f"{LOG_WEB_API} 获取统计信息失败：{e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/sites', methods=['GET'])
@require_auth
def get_sites():
    """获取所有站点列表"""
    try:
        from src.config import Config
        config = Config()
        
        sites = []
        for site in config.pt_sites:  # 返回所有站点，包括未启用的
            sites.append({
                'name': site.get('name'),
                'type': site.get('type', 'mteam'),
                'base_url': site.get('base_url', ''),
                'rss_url': site.get('rss_url', ''),
                'passkey': site.get('passkey', ''),
                'uid': site.get('uid', ''),
                'enabled': site.get('enabled', True),
                'interval': site.get('schedule', {}).get('interval', 300),
                'cleanup_interval': site.get('schedule', {}).get('cleanup_interval', 0),
                'filter': site.get('filter', {}),
                'schedule': site.get('schedule', {}),
                'download_settings': site.get('download_settings', {}),
                'pause_added': site.get('download_settings', {}).get('paused', False),
                'auto_download': site.get('download_settings', {}).get('auto_download', False),
                'auto_delete': site.get('download_settings', {}).get('auto_delete', False),
                'delete_files': site.get('download_settings', {}).get('delete_files', False),
                'tags': site.get('tags', [])
            })
        
        return jsonify({'success': True, 'sites': sites})
    except Exception as e:
        logger.exception(f"{LOG_WEB_API} 获取站点列表失败：{e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/sites', methods=['POST'])
@require_auth
def create_site():
    """创建新站点"""
    try:
        from src.config import Config
        
        config = Config()
        data = request.get_json()
        
        if not data or not data.get('name'):
            return jsonify({'success': False, 'error': '缺少站点名称'}), 400
        
        site_name = data['name']
        sites_config = config.pt_sites or []
        
        # 检查是否已存在同名站点
        for site in sites_config:
            if site.get('name') == site_name:
                return jsonify({'success': False, 'error': f'站点 {site_name} 已存在'}), 400
        
        # 创建新站点
        new_site = {
            'name': site_name,
            'type': data.get('type', 'mteam'),
            'base_url': data.get('base_url', ''),
            'rss_url': data.get('rss_url', ''),
            'passkey': data.get('passkey', ''),
            'uid': data.get('uid', ''),
            'enabled': data.get('enabled', False),
            'tags': data.get('tags', []),
            'filter': data.get('filter', {
                'keywords': [],
                'exclude': [],
                'min_size': 0,
                'max_size': 0
            }),
            'schedule': data.get('schedule', {
                'interval': 120,
                'auto_download': False,
                'cleanup_interval': 3600
            })
        }
        
        # 处理下载设置
        if 'download_settings' in data:
            new_site['download_settings'] = data['download_settings']
        elif 'auto_download' in data:
            new_site['download_settings'] = {
                'auto_download': data['auto_download']
            }
        
        sites_config.append(new_site)
        
        # 保存配置
        config._config['pt_sites'] = sites_config
        from src.config import save_config as save_config_file
        save_config_file(config._config, str(config.config_path))
        
        return jsonify({'success': True, 'message': f'站点 {site_name} 创建成功'})
    except Exception as e:
        logger.exception(f"{LOG_WEB_API} 创建站点失败：{e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/sites/<site_name>', methods=['PUT'])
@require_auth
def update_site(site_name):
    """更新或创建站点配置"""
    try:
        from src.config import Config
        import copy
        
        config = Config()
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': '缺少配置数据'}), 400
        
        # 加载当前配置
        sites_config = config.pt_sites or []
        
        # 查找是否已存在该站点
        site_index = None
        for i, site in enumerate(sites_config):
            if site.get('name') == site_name:
                site_index = i
                break
        
        if site_index is not None:
            # 更新现有站点
            site = sites_config[site_index]
            
            # 更新基本字段
            if 'name' in data:
                site['name'] = data['name']
            if 'type' in data:
                site['type'] = data['type']
            if 'base_url' in data:
                site['base_url'] = data['base_url']
            if 'rss_url' in data:
                site['rss_url'] = data['rss_url']
            # passkey 和 uid 允许为空（用户可以清空）
            if 'passkey' in data:
                site['passkey'] = data['passkey']
            if 'uid' in data:
                site['uid'] = data['uid']
            if 'enabled' in data:
                site['enabled'] = data['enabled']
            if 'tags' in data:
                site['tags'] = data['tags']
            
            # 更新过滤器配置
            if 'filter' in data:
                site['filter'] = data['filter']
            
            # 更新调度配置
            if 'schedule' in data:
                site['schedule'] = data['schedule']
            
            # 更新下载设置（兼容旧格式）
            if 'download_settings' in data:
                site['download_settings'] = data['download_settings']
            
            # 兼容旧格式：直接设置 auto_download
            if 'auto_download' in data:
                if 'download_settings' not in site:
                    site['download_settings'] = {}
                site['download_settings']['auto_download'] = data['auto_download']
        else:
            # 创建新站点
            new_site = {
                'name': site_name,
                'type': data.get('type', 'mteam'),
                'base_url': data.get('base_url', ''),
                'rss_url': data.get('rss_url', ''),
                'passkey': data.get('passkey', ''),
                'uid': data.get('uid', ''),
                'enabled': data.get('enabled', False),
                'tags': data.get('tags', []),
                'filter': data.get('filter', {
                    'keywords': [],
                    'exclude': [],
                    'min_size': 0,
                    'max_size': 0
                }),
                'schedule': data.get('schedule', {
                    'interval': 120,
                    'auto_download': False,
                    'cleanup_interval': 3600
                })
            }
            
            # 处理下载设置
            if 'download_settings' in data:
                new_site['download_settings'] = data['download_settings']
            elif 'auto_download' in data:
                new_site['download_settings'] = {
                    'auto_download': data['auto_download']
                }
            
            sites_config.append(new_site)
        
        # 保存配置
        config._config['pt_sites'] = sites_config
        from src.config import save_config as save_config_file
        save_config_file(config._config, str(config.config_path))
        
        return jsonify({'success': True, 'message': f'站点 {site_name} 配置已保存'})
    except Exception as e:
        logger.exception(f"{LOG_WEB_API} 更新站点配置失败：{e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/sites/<site_name>', methods=['DELETE'])
@require_auth
def delete_site(site_name):
    """删除站点配置"""
    try:
        from src.config import Config
        
        config = Config()
        sites_config = config.pt_sites or []
        
        # 查找并删除站点
        new_sites = [s for s in sites_config if s.get('name') != site_name]
        
        if len(new_sites) == len(sites_config):
            return jsonify({'success': False, 'error': f'站点 {site_name} 不存在'}), 404
        
        # 保存配置
        config._config['pt_sites'] = new_sites
        from src.config import save_config as save_config_file
        save_config_file(config._config, str(config.config_path))
        
        return jsonify({'success': True, 'message': f'站点 {site_name} 已删除'})
    except Exception as e:
        logger.exception(f"{LOG_WEB_API} 删除站点失败：{e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/preview', methods=['POST'])
@require_auth
def preview_torrents():
    try:
        from src.config import Config
        from src.filter import TorrentFilter
        from src.history import DownloadHistory
        
        data = request.get_json(silent=True) or {}
        requested_site_name = _normalize_site_name(data.get('site_name'))
        config = Config()
        site_config = _resolve_site_config(config, requested_site_name)
        if not site_config:
            message = (
                f'站点 {requested_site_name} 不存在'
                if requested_site_name
                else '当前存在多个站点，请从站点管理中选择要预览的站点'
            )
            logger.warning(f"{LOG_WEB_API} preview: {message}")
            return jsonify({'success': False, 'message': message}), 400

        rss_error = _validate_site_rss_url(site_config)
        if rss_error:
            logger.warning(f"{LOG_WEB_API} preview: {rss_error}")
            return jsonify({'success': False, 'message': rss_error}), 400

        site_name = site_config.get('name', requested_site_name or 'unknown')
        filter_config = site_config.get('filter', {})

        logger.debug(f"{LOG_WEB_API} preview: site={site_name}")
        logger.debug(f"{LOG_WEB_API} preview: rss_url={repr(site_config.get('rss_url', ''))}")
        logger.debug(f"{LOG_WEB_API} preview: keywords={filter_config.get('keywords', [])}")

        site_client = _create_site_client(site_config)
        torrent_filter = TorrentFilter(filter_config)
        history = DownloadHistory()

        torrents = site_client.fetch_torrents()
        logger.debug(f"{LOG_WEB_API} preview: RSS 获取成功，{len(torrents)} 个种子")

        filtered = [t for t in torrents if torrent_filter.filter(t)]
        logger.debug(f"{LOG_WEB_API} preview: 过滤后 {len(filtered)} 个种子")

        result = {
            'new': [],
            'downloaded': []
        }

        cache_key = hashlib.md5(json.dumps({
            'site_name': site_name,
            'rss_url': site_config.get('rss_url', ''),
            'keywords': filter_config.get('keywords', []),
            'exclude': filter_config.get('exclude', []),
        }, sort_keys=True).encode()).hexdigest()

        _preview_cache[cache_key] = {}

        for t in filtered:
            torrent_site_name = t.site_name or site_name
            torrent_info = {
                'id': t.torrent_id,
                'title': t.title,
                'size': round(t.size, 2),
                'category': t.category,
                'link': t.link,
                'site_name': torrent_site_name,
                'pub_date': t.pub_date,
            }
            _preview_cache[cache_key][t.torrent_id] = {
                'title': t.title,
                'link': t.link,
                'size': t.size,
                'category': t.category,
                'site_name': torrent_site_name,
                'pub_date': t.pub_date,
            }

            try:
                if history.contains(t.torrent_id):
                    result['downloaded'].append(torrent_info)
                    logger.debug(f"{LOG_WEB_API} preview: 已下载 {t.title[:50]}...")
                else:
                    result['new'].append(torrent_info)
                    logger.debug(f"{LOG_WEB_API} preview: 新种子 {t.title[:50]}...")
            except Exception as e:
                logger.exception(f"{LOG_WEB_API} preview: 历史记录检查失败：{e}")
        
        logger.info(f"{LOG_WEB_API} preview: 完成，新种子={len(result['new'])}, 已下载={len(result['downloaded'])}")
        
        return jsonify({
            'success': True,
            'cache_key': cache_key,
            'new_count': len(result['new']),
            'downloaded_count': len(result['downloaded']),
            'torrents': result
        })
    except Exception as e:
        logger.exception(f"{LOG_WEB_API} preview: 异常：{e}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/download_single', methods=['POST'])
@require_auth
def download_single_torrent():
    try:
        from src.config import Config
        from src.qbittorrent import QBittorrentClient
        from src.history import DownloadHistory

        data = request.get_json(silent=True) or {}
        torrent_id = data.get('id')
        cache_key = data.get('cache_key')

        if not torrent_id:
            return jsonify({'success': False, 'message': '没有种子 ID'})

        config = Config()
        qb_config = config.qbittorrent

        qb = QBittorrentClient(
            host=get_qbittorrent_host(qb_config),
            username=qb_config.get('username', ''),
            password=qb_config.get('password', ''),
        )

        history = DownloadHistory()

        torrent_info = None
        requested_site_name = _normalize_site_name(data.get('site_name'))

        # 从缓存获取种子信息
        if cache_key and cache_key in _preview_cache:
            torrent_info = _preview_cache[cache_key].get(torrent_id)
            if not torrent_info:
                return jsonify({'success': False, 'message': '种子信息已过期，请重新预览'})

        effective_site_name = requested_site_name or _normalize_site_name(
            (torrent_info or {}).get('site_name')
        )
        site_config = _resolve_site_config(config, effective_site_name)
        if not site_config and effective_site_name:
            return jsonify({'success': False, 'message': f'站点 {effective_site_name} 不存在'}), 404

        torrent_link = (torrent_info or {}).get('link') or data.get('link')
        if not torrent_link:
            return jsonify({'success': False, 'message': '缺少种子链接'})

        download_link = _build_download_link(torrent_link, site_config or {})
        with requests.Session() as download_session:
            resp = download_session.get(download_link, timeout=30)
            resp.raise_for_status()
            if len(resp.content) < 100:
                return jsonify({'success': False, 'message': f'种子文件太小：{len(resp.content)} 字节'})
            torrent_data = resp.content

        final_tags = _get_site_tags(site_config or {})
        success, torrent_hash = qb.add_torrent(
            torrent_data=torrent_data,
            torrent_title=data.get('title', ''),
            save_path=qb_config.get('save_path', ''),
            category=qb_config.get('category', ''),
            tags=final_tags,
            is_paused=qb_config.get('pause_added', False),
        )

        if success:
            resolved_site_name = effective_site_name or (site_config or {}).get('name', '')
            history.add(
                torrent_id,
                data.get('title', ''),
                torrent_hash,
                site_name=resolved_site_name,
                category=str(data.get('category') or (torrent_info or {}).get('category') or ''),
                size=float(data.get('size') or (torrent_info or {}).get('size') or 0),
            )
            logger.info(f"{LOG_WEB_DOWNLOAD} 已添加到 qBittorrent: {data.get('title', '')}")
            return jsonify({
                'success': True,
                'message': f'已添加到 qBittorrent: {data.get("title", "")}'
            })
        else:
            return jsonify({'success': False, 'message': '添加失败'})
    except Exception as e:
        logger.exception(f"{LOG_WEB_DOWNLOAD} 单个下载异常：{e}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/download', methods=['POST'])
@require_auth
def download_torrents():
    try:
        from src.config import Config
        from src.qbittorrent import QBittorrentClient
        from src.history import DownloadHistory

        data = request.get_json(silent=True) or {}
        torrents = data.get('torrents', [])

        logger.info(f"{LOG_WEB_DOWNLOAD} 收到下载请求：{len(torrents)} 个种子")
        logger.debug(f"{LOG_WEB_DOWNLOAD} 种子数据：{torrents}")

        if not torrents:
            logger.warning(f"{LOG_WEB_DOWNLOAD} 没有选择种子，请求数据：{data}")
            return jsonify({'success': False, 'message': '没有选择种子'})

        config = Config()
        qb_config = config.qbittorrent

        qb = QBittorrentClient(
            host=get_qbittorrent_host(qb_config),
            username=qb_config.get('username', ''),
            password=qb_config.get('password', ''),
        )

        history = DownloadHistory()

        downloaded_count = 0
        failed = []

        for torrent in torrents:
            torrent_id = torrent.get('id', '')
            title = torrent.get('title', '')
            link = torrent.get('link', '')
            site_name = _normalize_site_name(torrent.get('site_name'))
            site_config = _resolve_site_config(config, site_name)

            if not torrent_id or not link:
                failed.append(title or torrent_id)
                logger.warning(f"{LOG_WEB_DOWNLOAD} 种子数据不完整：{torrent}")
                continue

            if not site_config and site_name:
                failed.append(title or torrent_id)
                logger.warning(f"{LOG_WEB_DOWNLOAD} 站点不存在：{site_name} - {torrent}")
                continue

            # 下载种子文件（带重试）
            # 每个种子使用独立的 session，避免并发冲突
            torrent_data = None
            download_session = requests.Session()
            try:
                for retry in range(3):
                    try:
                        # 添加 passkey 参数（如果需要）
                        download_link = _build_download_link(link, site_config or {})
                        resp = download_session.get(download_link, timeout=30)
                        resp.raise_for_status()
                        if len(resp.content) < 100:  # 有效的.torrent 文件至少有这么多字节
                            raise ValueError(f'种子文件太小：{len(resp.content)} 字节')
                        torrent_data = resp.content
                        logger.info(f"{LOG_WEB_DOWNLOAD} 种子文件下载成功：{title} ({len(resp.content)} 字节)")
                        break
                    except Exception as e:
                        if retry < 2:
                            logger.warning(f"{LOG_WEB_DOWNLOAD} 种子文件下载失败，{retry + 1}/3 重试：{title} - {e}")
                            time.sleep(1)
                        else:
                            logger.error(f"{LOG_WEB_DOWNLOAD} 种子文件下载失败：{title} - {e}")
                            failed.append(title)
                            continue
            finally:
                download_session.close()
            
            if not torrent_data:
                continue

            final_tags = _get_site_tags(site_config or {})
            # 添加到 qBittorrent
            success, torrent_hash = qb.add_torrent(
                torrent_data=torrent_data,
                torrent_title=title,
                save_path=qb_config.get('save_path', ''),
                category=qb_config.get('category', ''),
                tags=final_tags,
                is_paused=qb_config.get('pause_added', False),
            )

            if success:
                resolved_site_name = site_name or (site_config or {}).get('name', '')
                history.add(
                    torrent_id,
                    title,
                    torrent_hash,
                    site_name=resolved_site_name,
                    category=str(torrent.get('category') or ''),
                    size=float(torrent.get('size') or 0),
                )
                logger.info(f"{LOG_WEB_DOWNLOAD} 已添加到 qBittorrent: {title}")
                downloaded_count += 1
            else:
                logger.error(f"{LOG_WEB_DOWNLOAD} 添加失败：{title}")
                failed.append(title)
        
        message = f'成功下载 {downloaded_count} 个种子'
        if failed:
            message += f'，失败 {len(failed)} 个'
        
        return jsonify({
            'success': True,
            'downloaded': downloaded_count,
            'failed': failed,
            'message': message
        })
    except Exception as e:
        logger.exception(f"{LOG_WEB_DOWNLOAD} 批量下载异常：{e}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/qb/status', methods=['GET'])
@require_auth
def qb_status():
    try:
        from src.config import Config
        from src.qbittorrent import QBittorrentClient
        config = Config()
        qb_config = config.qbittorrent
        qb = QBittorrentClient(
            host=get_qbittorrent_host(qb_config),
            username=qb_config.get('username', ''),
            password=qb_config.get('password', '')
        )
        version = qb.get_version()
        torrents = qb.get_torrents()
        return jsonify({
            'connected': version is not None,
            'version': version,
            'count': len(torrents)
        })
    except Exception as e:
        return jsonify({'connected': False, 'error': str(e)})


@app.route('/api/qb/test', methods=['POST'])
@require_auth
def qb_test():
    try:
        from src.qbittorrent import QBittorrentClient
        data = request.get_json(silent=True) or {}
        current_config = load_config()
        merged_qb = copy.deepcopy(current_config.get('qbittorrent', {}))

        if 'host' in data or 'url' in data:
            merged_qb['host'] = get_qbittorrent_host(data)
        if 'username' in data:
            merged_qb['username'] = data.get('username', '')

        incoming_password = data.get('password', None)
        if incoming_password not in (None, ''):
            merged_qb['password'] = incoming_password

        qb = QBittorrentClient(
            host=get_qbittorrent_host(merged_qb),
            username=merged_qb.get('username', ''),
            password=merged_qb.get('password', '')
        )
        version = qb.get_version()
        if version:
            return jsonify({
                'success': True,
                'version': version,
                'message': f'连接成功！qBittorrent v{version}'
            })
        else:
            return jsonify({
                'success': False,
                'message': '连接失败，请检查地址和端口'
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'连接失败: {str(e)}'
        })


if __name__ == '__main__':
    os.makedirs(BASE_DIR / 'data', exist_ok=True)
    
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    
    # 加载配置，读取 Web 端口
    config = load_config()
    # 如果配置文件不存在，使用默认端口 6000
    web_port = config.get('app', {}).get('web_port', 5000)

    log_config = dict(config.get('logging', {}) or {})
    log_config['use_color'] = not debug_mode
    log_config.setdefault('level', 'DEBUG' if debug_mode else 'INFO')
    
    setup_logging(log_config)
    
    logger = get_logger(LOG_WEB_SERVICE)
    log_startup_message(logger, f"{LOG_WEB_SERVICE} 服务启动：http://0.0.0.0:{web_port}")
    log_startup_message(logger, f"{LOG_WEB_SERVICE} 调试模式：{'开启' if debug_mode else '关闭'}")
    log_startup_message(logger, f"{LOG_WEB_SERVICE} Web 端口：{web_port} (配置：app.web_port)")
    
    app.run(host='0.0.0.0', port=web_port, debug=debug_mode)
