import requests
import os
import time
import hashlib
import threading
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin, urlparse

from .logger_config import get_logger
from .log_constants import LOG_QB_CONNECT, LOG_QB_LOGIN, LOG_QB_ADD, LOG_QB_GET, LOG_QB_DEL

logger = get_logger(__name__)


# 登录失败退避状态，避免短时间内反复撞 qB 导致 IP 封禁。
_LOGIN_FAILURE_LOCK = threading.Lock()
_LOGIN_FAILURE_STATE: Dict[str, Dict[str, Any]] = {}
_LOGIN_FAILURE_COOLDOWN_SECONDS = 300
_LOGIN_TEMP_FAILURE_COOLDOWN_SECONDS = 60


def _normalize_qb_host(host: str) -> str:
    """把 qBittorrent 主机地址规范化成可用于 requests 的基础 URL。"""
    raw_host = str(host or "").strip()
    if not raw_host:
        return ""

    if raw_host.startswith("//"):
        raw_host = f"http:{raw_host}"

    parsed = urlparse(raw_host)
    if not parsed.scheme and parsed.netloc:
        raw_host = f"http://{raw_host}"
        parsed = urlparse(raw_host)
    elif not parsed.scheme and not parsed.netloc:
        if raw_host.startswith("/"):
            return ""
        raw_host = f"http://{raw_host}"
        parsed = urlparse(raw_host)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""

    normalized_path = parsed.path.rstrip("/")
    parsed = parsed._replace(path=normalized_path, params="", query="", fragment="")
    return parsed.geturl().rstrip("/")


def _build_api_url(base_url: str, endpoint: str) -> str:
    """基于基础地址拼出 qBittorrent API URL。"""
    normalized_base = _normalize_qb_host(base_url)
    if not normalized_base:
        return ""
    return urljoin(f"{normalized_base}/", str(endpoint or "").lstrip("/"))


def _build_origin(base_url: str) -> str:
    """提取请求 Origin，只保留 scheme://host:port。"""
    normalized_base = _normalize_qb_host(base_url)
    if not normalized_base:
        return ""
    parsed = urlparse(normalized_base)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _build_login_fingerprint(host: str, username: str, password: str) -> str:
    """构建登录失败退避的共享键。"""
    raw_value = f"{_normalize_qb_host(host)}|{username or ''}|{password or ''}"
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()


def _get_login_failure_state(fingerprint: str) -> Dict[str, Any]:
    """获取仍在冷却期内的登录失败状态。"""
    now = time.monotonic()
    with _LOGIN_FAILURE_LOCK:
        state = _LOGIN_FAILURE_STATE.get(fingerprint)
        if not state:
            return {}
        expires_at = float(state.get("expires_at", 0) or 0)
        if expires_at <= now:
            _LOGIN_FAILURE_STATE.pop(fingerprint, None)
            return {}
        return dict(state)


def _set_login_failure_state(
    fingerprint: str,
    reason: str,
    cooldown_seconds: int,
) -> None:
    """记录登录失败并设置冷却期。"""
    cooldown = max(1, int(cooldown_seconds or 0))
    now = time.monotonic()
    with _LOGIN_FAILURE_LOCK:
        _LOGIN_FAILURE_STATE[fingerprint] = {
            "reason": reason,
            "expires_at": now + cooldown,
            "updated_at": now,
        }


def _clear_login_failure_state(fingerprint: str) -> None:
    """清理登录失败状态。"""
    with _LOGIN_FAILURE_LOCK:
        _LOGIN_FAILURE_STATE.pop(fingerprint, None)


class QBittorrentClient:
    def __init__(
        self,
        host: str,
        username: str = "",
        password: str = "",
    ):
        self.host = _normalize_qb_host(host)
        self.username = username
        self.password = password
        self.session = requests.Session()
        self._authenticated = False

    def login(self) -> bool:
        # 检查 host 是否为空
        if not self.host or not self.host.strip():
            logger.warning(f"{LOG_QB_LOGIN} 跳过：qBittorrent URL 未配置或格式无效")
            self._authenticated = False
            return False
            
        if not self.username and not self.password:
            self._authenticated = True
            logger.debug(f"{LOG_QB_LOGIN} 无认证信息，跳过登录")
            return True

        fingerprint = _build_login_fingerprint(self.host, self.username, self.password)
        failure_state = _get_login_failure_state(fingerprint)
        if failure_state:
            remaining = int(max(0, float(failure_state.get("expires_at", 0) or 0) - time.monotonic()))
            logger.debug(f"{LOG_QB_LOGIN} 冷却中，跳过登录（剩余 {remaining} 秒）")
            self._authenticated = False
            return False

        logger.debug(f"{LOG_QB_LOGIN} 正在连接：{self.host}")
        try:
            url = _build_api_url(self.host, "/api/v2/auth/login")
            if not url:
                logger.warning(f"{LOG_QB_LOGIN} 跳过：无法构建登录地址")
                self._authenticated = False
                return False
            
            # qBittorrent 需要正确的 Content-Type 和Referer 头
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': _build_api_url(self.host, "/login"),
                'Origin': _build_origin(self.host) or self.host
            }
            
            # 使用正确的登录参数格式
            data = {
                "username": self.username,
                "password": self.password,
            }
            
            resp = self.session.post(url, headers=headers, data=data, timeout=10)
            
            # 检查响应状态
            if resp.status_code in {401, 403}:
                _set_login_failure_state(
                    fingerprint,
                    reason=f"HTTP {resp.status_code}",
                    cooldown_seconds=_LOGIN_FAILURE_COOLDOWN_SECONDS,
                )
                logger.warning(
                    f"{LOG_QB_LOGIN} 失败：HTTP {resp.status_code}，"
                    f"已进入 {_LOGIN_FAILURE_COOLDOWN_SECONDS} 秒冷却"
                )
                self._authenticated = False
                return False
            
            resp.raise_for_status()
            result = resp.text.lower() == "ok."
            self._authenticated = result
            
            if result:
                _clear_login_failure_state(fingerprint)
                logger.debug(f"{LOG_QB_LOGIN} 成功")
            else:
                _set_login_failure_state(
                    fingerprint,
                    reason=f"响应：{resp.text}",
                    cooldown_seconds=_LOGIN_FAILURE_COOLDOWN_SECONDS,
                )
                logger.warning(
                    f"{LOG_QB_LOGIN} 失败：认证被拒绝 (响应：{resp.text})，"
                    f"已进入 {_LOGIN_FAILURE_COOLDOWN_SECONDS} 秒冷却"
                )
            return result
        except requests.exceptions.RequestException as e:
            _set_login_failure_state(
                fingerprint,
                reason=str(e),
                cooldown_seconds=_LOGIN_TEMP_FAILURE_COOLDOWN_SECONDS,
            )
            logger.warning(
                f"{LOG_QB_LOGIN} 失败：{e}，"
                f"已进入 {_LOGIN_TEMP_FAILURE_COOLDOWN_SECONDS} 秒冷却"
            )
            self._authenticated = False
            return False
        except Exception as e:
            _set_login_failure_state(
                fingerprint,
                reason=str(e),
                cooldown_seconds=_LOGIN_TEMP_FAILURE_COOLDOWN_SECONDS,
            )
            logger.error(f"{LOG_QB_LOGIN} 异常：{e}")
            self._authenticated = False
            return False

    def add_torrent(
        self,
        torrent_data: bytes = None,
        torrent_url: str = None,
        save_path: str = "",
        category: str = "",
        tags: List[str] = None,
        is_paused: bool = False,
        torrent_title: str = "",
        retry: bool = True,
    ) -> tuple:
        """返回 (成功与否，torrent hash)"""
        if not self.host or not self.host.strip():
            logger.error(f"{LOG_QB_ADD} 失败：qBittorrent 地址未配置或格式无效")
            return (False, '')

        if not self._authenticated:
            if not self.login():
                return (False, '')

        try:
            url = _build_api_url(self.host, "/api/v2/torrents/add")
            if not url:
                logger.error(f"{LOG_QB_ADD} 失败：无法构建 qBittorrent API 地址")
                return (False, '')
            
            if torrent_data:
                # qBittorrent API v2 需要特定的字段名
                data = {
                    "savepath": save_path or "",
                    "category": category or "",
                    "tags": ",".join(tags) if tags else "",
                    "paused": "true" if is_paused else "false",
                    "autoTMM": "false",
                    "contentLayout": "Original",
                    "skip_checking": "false",
                    "sequential": "false",
                    "firstLastPiecePriority": "false",
                }
                # 移除空字段
                data = {k: v for k, v in data.items() if v != ""}
                
                files = {"torrents": ("torrent.torrent", torrent_data, "application/x-bittorrent")}
                resp = self.session.post(url, data=data, files=files, timeout=30)
            elif torrent_url:
                data = {
                    "urls": torrent_url,
                    "savepath": save_path or "",
                    "category": category or "",
                    "tags": ",".join(tags) if tags else "",
                    "paused": "true" if is_paused else "false",
                    "autoTMM": "false",
                }
                # 移除空字段
                data = {k: v for k, v in data.items() if v != ""}
                
                resp = self.session.post(url, data=data, timeout=30)
            else:
                logger.error(f"{LOG_QB_ADD} 失败：没有提供种子数据或 URL")
                return (False, '')

            # 检查响应状态
            if resp.status_code == 415:
                logger.error(f"{LOG_QB_ADD} 失败：415 错误 - qBittorrent 版本可能过旧或不支持该格式")
                return (False, '')
            
            resp.raise_for_status()
            logger.info(f"{LOG_QB_ADD} 成功")
            
            # 计算或查找 torrent hash
            if torrent_data:
                # 从种子文件直接计算 hash（更可靠，不受批量操作影响）
                torrent_hash = self._calculate_info_hash(torrent_data)
                if not torrent_hash:
                    logger.warning(f"{LOG_QB_ADD} 计算 info_hash 失败，尝试通过标题查找")
                    torrent_hash = self._find_torrent_hash_by_title(torrent_title)
            else:
                # URL 方式使用标题查找
                time.sleep(0.5)
                torrent_hash = self._find_torrent_hash_by_title(torrent_title)
            
            return (True, torrent_hash)
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if retry and ("403" in error_msg or "Unauthorized" in error_msg or "401" in error_msg):
                logger.warning(f"{LOG_QB_ADD} 认证失效，尝试重新登录")
                self._authenticated = False
                if self.login():
                    return self.add_torrent(
                        torrent_data=torrent_data,
                        torrent_url=torrent_url,
                        save_path=save_path,
                        category=category,
                        tags=tags,
                        is_paused=is_paused,
                        torrent_title=torrent_title,
                        retry=False
                    )
            logger.warning(f"{LOG_QB_ADD} 请求失败：{e}")
            return (False, '')
        except Exception as e:
            logger.error(f"{LOG_QB_ADD} 异常：{e}")
            return (False, '')

    def _calculate_info_hash(self, torrent_data: bytes) -> str:
        """从种子文件数据直接计算 info_hash（不依赖 QB 返回）"""
        try:
            import bencodepy
            torrent_dict = bencodepy.decode(torrent_data)
            info_dict = torrent_dict[b'info']
            info_bencoded = bencodepy.encode(info_dict)
            return hashlib.sha1(info_bencoded).hexdigest()
        except Exception as e:
            logger.warning(f"{LOG_QB_ADD} 计算 info_hash 失败：{e}")
            return ""

    def _find_torrent_hash_by_title(self, title: str) -> str:
        """通过种子标题查找 hash（仅作为 URL 方式的后备方案）"""
        if not title:
            return ''
        try:
            torrents = self.get_torrents()
            if torrents:
                # 查找标题包含匹配的种子
                for t in torrents:
                    t_name = t.get('name', '')
                    # 标题互相包含，认为是同一个
                    if title in t_name or t_name in title:
                        return t.get('hash', '')
                # 如果没有匹配，返回第一个（最新添加的）
                return torrents[0].get('hash', '')
        except:
            pass
        return ''

    def get_torrents(self, raise_on_error: bool = False) -> List[Dict[str, Any]]:
        # 检查 host 是否为空
        if not self.host or not self.host.strip():
            return []
            
        if not self._authenticated:
            if not self.login():
                return []

        try:
            url = _build_api_url(self.host, "/api/v2/torrents/info")
            if not url:
                return []
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if "403" in error_msg or "Unauthorized" in error_msg or "401" in error_msg:
                self._authenticated = False
                if self.login():
                    try:
                        url = _build_api_url(self.host, "/api/v2/torrents/info")
                        if not url:
                            return []
                        resp = self.session.get(url, timeout=10)
                        resp.raise_for_status()
                        return resp.json()
                    except Exception:
                        if raise_on_error:
                            raise
                        pass
            if raise_on_error:
                raise
            logger.warning(f"{LOG_QB_GET} 列表请求失败：{e}")
            return []
        except Exception as e:
            if raise_on_error:
                raise
            logger.error(f"{LOG_QB_GET} 列表异常：{e}")
            return []

    def get_version(self) -> Optional[str]:
        # 检查 host 是否为空
        if not self.host or not self.host.strip():
            return None
            
        if not self._authenticated:
            if not self.login():
                return None
        try:
            url = _build_api_url(self.host, "/api/v2/app/version")
            if not url:
                return None
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.RequestException as e:
            logger.warning(f"{LOG_QB_GET} 版本请求失败：{e}")
            return None
        except Exception as e:
            logger.error(f"{LOG_QB_GET} 版本异常：{e}")
            return None

    def delete_torrent(self, torrent_hash: str, delete_files: bool = False) -> bool:
        if not self.host or not self.host.strip():
            logger.error(f"{LOG_QB_DEL} 失败：qBittorrent 地址未配置或格式无效")
            return False

        if not self._authenticated:
            if not self.login():
                return False
        try:
            url = _build_api_url(self.host, "/api/v2/torrents/delete")
            if not url:
                return False
            data = {
                "hashes": torrent_hash,
                "deleteFiles": "true" if delete_files else "false"
            }
            resp = self.session.post(url, data=data, timeout=10)
            resp.raise_for_status()
            logger.info(f"{LOG_QB_DEL} 成功：{torrent_hash}")
            return True
        except requests.exceptions.RequestException as e:
            logger.warning(f"{LOG_QB_DEL} 请求失败：{e}")
            return False
        except Exception as e:
            logger.error(f"{LOG_QB_DEL} 异常：{e}")
            return False

    def get_completed_torrents(self, tag: str = None) -> List[Dict[str, Any]]:
        torrents = self.get_torrents()
        completed = []
        for t in torrents:
            if t.get("progress", 0) >= 1.0:
                if tag is None or tag in t.get("tags", ""):
                    completed.append(t)
        return completed
