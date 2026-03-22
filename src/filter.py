import re
from typing import List, Dict, Any
from dataclasses import dataclass

from .logger_config import get_logger
from .log_constants import LOG_FILTER

logger = get_logger(__name__)


@dataclass
class FilterConfig:
    keywords: List[str]
    exclude: List[str]
    min_size: float
    max_size: float
    free_only: bool


class TorrentFilter:
    def __init__(self, config: Dict[str, Any]):
        self.keyword_groups = self._parse_keywords(config.get("keywords", []))
        self.exclude = [e.lower() for e in config.get("exclude", []) if e]
        self.min_size = config.get("min_size", 0)
        self.max_size = config.get("max_size", 0)
        self.free_only = config.get("free_only", False)

    def _parse_keywords(self, keywords: List[str]) -> List[List[str]]:
        groups = []
        
        for kw in keywords:
            if not kw:
                continue
                
            content = kw.strip()
            
            # 检查是否用中括号包裹（支持跨行）
            if content.startswith('[') and content.endswith(']'):
                content = content[1:-1].strip()
            
            if not content:
                continue
            
            # 处理换行符，将跨行内容合并为空格分隔
            content = ' '.join(content.split())
            
            # 逗号分隔 = 或条件，空格分隔 = 且条件
            if ',' in content or '，' in content:
                # 逗号分隔的每个部分是"或"关系，需要分成不同的组
                parts = [p.strip() for p in content.replace(',', ',').split(',') if p.strip()]
                for part in parts:
                    # 每个部分内部按空格分割 = 且条件
                    words = [w.strip().lower() for w in part.split() if w.strip()]
                    if words:
                        groups.append(words)
            else:
                # 无逗号，按空格分割 = 且条件
                words = [w.strip().lower() for w in content.split() if w.strip()]
                if words:
                    groups.append(words)
        return groups

    def _match_keywords(self, title: str) -> bool:
        if not self.keyword_groups:
            return True
        title_lower = title.lower()
        for group in self.keyword_groups:
            if all(word in title_lower for word in group):
                return True
        return False

    def _match_exclude(self, title: str) -> bool:
        if not self.exclude:
            return False
        title_lower = title.lower()
        for exclude in self.exclude:
            if exclude in title_lower:
                return True
        return False

    def _check_size(self, size: float) -> bool:
        if self.min_size > 0 and size < self.min_size:
            return False
        if self.max_size > 0 and size > self.max_size:
            return False
        return True

    def filter(self, torrent) -> bool:
        title = torrent.title
        size = torrent.size
        is_free = torrent.is_free

        if self.free_only and not is_free:
            logger.debug(f"{LOG_FILTER} 跳过 (非免费种): {title}")
            return False

        if not self._match_keywords(title):
            logger.debug(f"{LOG_FILTER} 跳过 (关键词不匹配): {title}")
            return False

        if self._match_exclude(title):
            logger.debug(f"{LOG_FILTER} 跳过 (包含排除词): {title}")
            return False

        if not self._check_size(size):
            logger.debug(f"{LOG_FILTER} 跳过 (大小不符合): {title} ({size}GB)")
            return False

        logger.debug(f"{LOG_FILTER} 匹配：{title}")
        return True
