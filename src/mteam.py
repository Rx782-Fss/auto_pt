import feedparser
import requests
import re
import random
import time
from typing import List, Dict, Optional
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

from .logger_config import get_logger
from .log_constants import LOG_MTEAM_FETCH, LOG_MTEAM_DOWNLOAD, LOG_MTEAM_PARSE
from .config import Config

logger = get_logger(__name__)

CATEGORY_MAP = {
    "Movie/SD": "電影/SD",
    "Movie/HD": "電影/HD",
    "Movie/DVDiSo": "電影/DVDiSo",
    "Movie/Blu-Ray": "電影/Blu-Ray",
    "Movie/Remux": "電影/Remux",
    "TV Series/SD": "影劇/綜藝/SD",
    "TV Series/HD": "影劇/綜藝/HD",
    "TV Series/BD": "影劇/綜藝/BD",
    "TV Series/DVDiSo": "影劇/綜藝/DVDiSo",
    "Documentary": "紀錄",
    "Record": "紀錄",
    "Music(无损)": "Music(無損)",
    "Music(Lossless)": "Music(無損)",
    "Music": "Music(無損)",
    "Concert": "演唱",
    "PC Game": "PC遊戲",
    "PCGame": "PC遊戲",
    "TV Game": "TV遊戲",
    "TVGame": "TV遊戲",
    "Anime": "動畫",
    "Sport": "運動",
    "Sports": "運動",
    "E-Book": "電子書",
    "EBook": "電子書",
    "Software": "軟體",
    "Audiobook": "有聲書",
    "AudioBook": "有聲書",
    "Educational": "教育影片",
    "Misc": "Misc(其他)",
    "Misc(Other)": "Misc(其他)",
}

SITE_CATEGORY_ID_MAP = {
    "hdtime": {
        "402": "剧集",
        "405": "动漫",
    },
}

NON_CATEGORY_TAG_KEYWORDS = (
    "免费",
    "free",
    "2xfree",
    "twoup",
    "double",
    "置顶",
    "sticky",
    "top",
    "hot",
    "推荐",
)


@dataclass
class Torrent:
    title: str
    link: str
    size: float  # GB
    pub_date: str
    category: str
    is_free: bool = False
    torrent_id: str = ""
    seeders: int = 0      # 做种数/上传人数
    leechers: int = 0     # 下载人数
    snatched: int = 0     # 完成数
    site_name: str = ""   # 来源站点


class MTeamClient:
    def __init__(
        self,
        base_url: str,
        rss_url: str,
        passkey: str = "",
        uid: str = "",
        sign: str = "",
        categories: List[str] = None,
        category_map: Dict[str, str] = None,
        site_name: str = "",  # 站点名称（用于多站点区分）
    ):
        self.base_url = base_url
        self.rss_url = rss_url
        self.passkey = passkey
        self.uid = uid
        self.sign = sign
        self.categories = categories or []
        self.category_map = {
            str(key).strip(): str(value).strip()
            for key, value in (category_map or {}).items()
            if str(key).strip() and str(value).strip()
        }
        self.site_name = site_name  # 保存站点名称
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )

    def _parse_size(self, size_str: str) -> float:
        try:
            size_str = str(size_str).strip().upper()
            
            if not size_str or size_str == "0":
                return 0.0
            
            match = re.search(r"([\d.]+)\s*([KMGT]?B)", size_str, re.IGNORECASE)
            if not match:
                # 尝试解析纯数字（可能是字节）
                try:
                    size_float = float(size_str)
                    if size_float > 0:
                        return size_float / (1024 ** 3)
                except:
                    pass
                return 0.0
            
            size = float(match.group(1))
            unit = match.group(2).upper()
            
            units = {
                "B": 1,
                "KB": 1024,
                "MB": 1024 ** 2,
                "GB": 1024 ** 3,
                "TB": 1024 ** 4,
            }
            
            bytes_size = size * units.get(unit, 1)
            return bytes_size / (1024 ** 3)
        except Exception as e:
            logger.warning(f"{LOG_MTEAM_PARSE} 大小解析失败：{size_str} - {e}")
            return 0.0

    def _extract_id(self, link: str) -> str:
        match = re.search(r"id=(\d+)", link)
        if match:
            return match.group(1)
        match = re.search(r"/(\d+)\.torrent", link)
        return match.group(1) if match else ""

    def _check_free(self, entry) -> bool:
        for tag in getattr(entry, "tags", []) or []:
            term = str(getattr(tag, "term", "") or "")
            if "免费" in term or "free" in term.lower():
                return True
        title = entry.get("title", "")
        return "免费" in title or "free" in title.lower()

    def _map_category(self, category: str) -> str:
        category_text = re.sub(r"\s+", " ", str(category or "").strip())
        return CATEGORY_MAP.get(category_text, category_text)

    def _is_non_category_tag(self, value: str) -> bool:
        normalized = str(value or "").strip()
        if not normalized:
            return True
        lowered = normalized.lower()
        return any(keyword in lowered for keyword in NON_CATEGORY_TAG_KEYWORDS)

    def _extract_category_id_from_scheme(self, scheme: str) -> str:
        if not scheme:
            return ""

        parsed = urlparse(str(scheme))
        query = parse_qs(parsed.query)

        if query.get("cat"):
            category_id = str(query["cat"][0]).strip()
            if category_id:
                return category_id

        for key in query:
            match = re.fullmatch(r"cat(\d+)", str(key))
            if match:
                return match.group(1)

        match = re.search(r"(?:\bcat=|/cat/)(\d+)", str(scheme))
        return match.group(1) if match else ""

    def _resolve_category_from_id(self, category_id: str) -> str:
        if not category_id:
            return ""

        site_key = str(self.site_name or "").strip().lower()
        site_map = SITE_CATEGORY_ID_MAP.get(site_key, {})

        if category_id in self.category_map:
            return self.category_map[category_id]
        if category_id in site_map:
            return site_map[category_id]
        return ""

    def _extract_category(self, entry) -> str:
        category_ids = []

        for tag in getattr(entry, "tags", []) or []:
            term = self._map_category(getattr(tag, "term", ""))
            category_id = self._extract_category_id_from_scheme(getattr(tag, "scheme", ""))
            if category_id:
                category_ids.append(category_id)

            if term and not self._is_non_category_tag(term):
                return self._resolve_category_from_id(category_id) or term

        raw_category = self._map_category(entry.get("category", ""))
        if raw_category and not self._is_non_category_tag(raw_category):
            return raw_category

        for category_id in category_ids:
            resolved = self._resolve_category_from_id(category_id)
            if resolved:
                return resolved

        return ""

    def _build_rss_url(self) -> str:
        url = self.rss_url
        if not url:
            return url
        
        # 自动添加dl=1参数，确保返回下载链接
        if "dl=" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}dl=1"
        
        return url

    def fetch_torrents(self) -> List[Torrent]:
        from requests.exceptions import HTTPError
        
        # 从配置读取重试参数（带默认值）
        config = Config()
        max_retries = config.get('rss_max_retries', 3)
        base_delay = config.get('rss_base_delay', 30)
        max_delay = config.get('rss_max_delay', 300)
        
        # 指数退避参数
        backoff_factor = 2.0
        jitter = 0.2  # ±20% 随机抖动
        
        start_time = time.time()
        torrents = []
        
        try:
            url = self._build_rss_url()
            site_label = f"[{self.site_name}] " if self.site_name else ""
            if not url:
                logger.warning(f"{LOG_MTEAM_FETCH} {site_label}RSS 地址为空，跳过获取")
                return torrents

            parsed_url = urlparse(url)
            if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
                logger.error(f"{LOG_MTEAM_FETCH} {site_label}RSS 地址格式无效，跳过获取")
                return torrents

            logger.info(f"{LOG_MTEAM_FETCH} 开始获取 RSS")
            
            # 429 重试机制：最多重试 max_retries 次
            for attempt in range(max_retries):
                try:
                    resp = self.session.get(url, timeout=30)
                    resp.raise_for_status()
                    break  # 请求成功，跳出重试循环
                    
                except HTTPError as e:
                    if e.response.status_code == 429 and attempt < max_retries - 1:
                        # 429 错误：优先使用 Retry-After 头，否则使用指数退避
                        retry_after = e.response.headers.get('Retry-After')
                        wait_time = None
                        
                        if retry_after:
                            # 尝试解析 Retry-After 头（可能是秒数或 HTTP 日期）
                            try:
                                wait_time = int(retry_after)
                                logger.debug(f"{LOG_MTEAM_FETCH} 使用 Retry-After 头：{wait_time} 秒")
                            except ValueError:
                                # 解析 HTTP 日期格式
                                try:
                                    retry_date = parsedate_to_datetime(retry_after)
                                    wait_time = max(0, int((retry_date - datetime.now(timezone.utc)).total_seconds()))
                                    logger.debug(f"{LOG_MTEAM_FETCH} 使用 Retry-After 日期：{wait_time} 秒")
                                except Exception:
                                    wait_time = None
                        
                        if wait_time is None:
                            # 使用指数退避 + 随机抖动
                            wait_time = min(base_delay * (backoff_factor ** attempt), max_delay)
                            wait_time *= (1 + random.uniform(-jitter, jitter))
                            logger.debug(f"{LOG_MTEAM_FETCH} 使用指数退避：{wait_time:.1f} 秒")
                        
                        logger.warning(f"{LOG_MTEAM_FETCH} 触发限流 (429)，等待 {wait_time:.0f} 秒后重试 ({attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                    else:
                        raise  # 其他错误或最后一次重试失败，抛出异常
            
            feed = feedparser.parse(resp.content)

            # feedparser 的 Bozo 标志用于表示 RSS/Atom 解析错误，修正拼写错误
            if feed.bozo:
                logger.debug(f"{LOG_MTEAM_PARSE} RSS 格式警告：{feed.bozo_exception}")

            for entry in feed.entries:
                title = entry.get("title", "")
                
                link = ""
                enclosures = entry.get("enclosures", [])
                if enclosures:
                    link = enclosures[0].get("href", "")
                if not link:
                    link = entry.get("link", "")

                if not title or not link:
                    continue

                torrent_id = self._extract_id(link)
                if not torrent_id:
                    logger.debug(
                        f"{LOG_MTEAM_PARSE} 跳过非种子 RSS 条目："
                        f"title={title[:60]}..., link={link[:120]}"
                    )
                    continue

                size_str = "0"
                for enclosure in enclosures:
                    if enclosure.get("length"):
                        size_str = enclosure.get("length", "0")
                        break

                category = self._extract_category(entry)

                # 提取统计信息（如果 RSS 支持）
                seeders = 0
                leechers = 0
                snatched = 0
                
                # 尝试从 different 命名空间或 custom 字段提取
                if hasattr(entry, 'seeders'):
                    try:
                        seeders = int(entry.seeders)
                    except (ValueError, TypeError):
                        pass
                
                if hasattr(entry, 'leechers'):
                    try:
                        leechers = int(entry.leechers)
                    except (ValueError, TypeError):
                        pass
                
                if hasattr(entry, 'snatched') or hasattr(entry, 'completed'):
                    try:
                        snatched = int(entry.get('snatched', entry.get('completed', 0)))
                    except (ValueError, TypeError):
                        pass

                torrent = Torrent(
                    title=title,
                    link=link,
                    size=self._parse_size(str(size_str)),
                    pub_date=entry.get("published", ""),
                    category=category,
                    is_free=self._check_free(entry),
                    torrent_id=torrent_id,
                    seeders=seeders,
                    leechers=leechers,
                    snatched=snatched,
                    site_name=self.site_name  # 使用客户端的站点名称
                )
                logger.debug(
                    f"{LOG_MTEAM_PARSE} 创建种子："
                    f"{torrent.title[:50]}... site_name={self.site_name}, "
                    f"category={torrent.category}, size={torrent.size}"
                )
                torrents.append(torrent)

            elapsed = time.time() - start_time
            logger.info(f"{LOG_MTEAM_FETCH} 获取成功，共 {len(torrents)} 个种子 (耗时：{elapsed:.2f}s)")

        except HTTPError as e:
            if e.response.status_code == 429:
                logger.error(f"{LOG_MTEAM_FETCH} 触发限流 (429)，已重试 {max_retries} 次仍失败。建议：1. 增加 RSS 预获取间隔 2. 减少同时请求的站点数")
            else:
                logger.exception(f"{LOG_MTEAM_FETCH} 获取失败：{e}")
        except Exception as e:
            logger.exception(f"{LOG_MTEAM_FETCH} 获取失败：{e}")

        return torrents

    def download_torrent(self, torrent: Torrent) -> Optional[bytes]:
        import time
        start_time = time.time()
        try:
            link = torrent.link
            
            # 添加 passkey 参数（如果需要）
            if self.passkey and "passkey=" not in link and "sign=" not in link:
                sep = "&" if "?" in link else "?"
                link = f"{link}{sep}passkey={self.passkey}"
            
            logger.debug(f"{LOG_MTEAM_DOWNLOAD} 下载中：{torrent.title}")
            logger.debug(f"{LOG_MTEAM_DOWNLOAD} 链接：{link[:100]}...")
            
            resp = self.session.get(link, timeout=30)
            resp.raise_for_status()
            
            # 验证文件大小
            if len(resp.content) < 100:
                logger.error(f"{LOG_MTEAM_DOWNLOAD} 下载的文件太小：{len(resp.content)} 字节 - {torrent.title}")
                logger.debug(f"{LOG_MTEAM_DOWNLOAD} 响应头：{resp.headers}")
                logger.debug(f"{LOG_MTEAM_DOWNLOAD} 响应内容前 200 字节：{resp.content[:200]}")
                return None
            
            # 验证是否为有效的 torrent 文件
            if not resp.content.startswith(b'd'):
                logger.error(f"{LOG_MTEAM_DOWNLOAD} 下载的文件不是有效的 torrent 文件 - {torrent.title}")
                logger.debug(f"{LOG_MTEAM_DOWNLOAD} 文件开头：{resp.content[:20]}")
                return None
            
            elapsed = time.time() - start_time
            logger.info(f"{LOG_MTEAM_DOWNLOAD} 下载成功：{torrent.title} ({len(resp.content)} 字节，耗时：{elapsed:.2f}s)")
            return resp.content
        except Exception as e:
            logger.exception(f"{LOG_MTEAM_DOWNLOAD} 下载失败：{torrent.title} - {e}")
            return None
