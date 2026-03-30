import json
import os
from pathlib import Path
from typing import Set
from datetime import datetime, timezone

from .logger_config import get_logger
from .log_constants import LOG_HISTORY

logger = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent


def _resolve_runtime_data_dir() -> Path:
    """解析运行时数据目录，优先跟随密钥文件目录。"""
    env_key_file = os.getenv("AUTO_PT_KEY_FILE", "").strip()
    if env_key_file:
        key_path = Path(env_key_file).expanduser()
        if not key_path.is_absolute():
            key_path = (BASE_DIR / key_path).resolve()
        return key_path.parent
    return BASE_DIR / "data"


def _resolve_history_file() -> str:
    """解析历史记录文件路径，优先使用运行时目录。"""
    env_history_file = os.getenv("AUTO_PT_HISTORY_FILE", "").strip()
    if env_history_file:
        history_path = Path(env_history_file).expanduser()
        if not history_path.is_absolute():
            history_path = (BASE_DIR / history_path).resolve()
        return str(history_path)
    return str(_resolve_runtime_data_dir() / "history.json")


HISTORY_FILE = _resolve_history_file()

_HISTORY_STATUS_ALIASES = {
    "pausedup": "completed",
    "uploading": "seeding",
    "stalledup": "seeding",
    "forcedup": "seeding",
}


def _normalize_history_status(status) -> str:
    """统一历史记录状态，兼容旧数据和 qB 状态值。"""
    normalized = str(status or "").strip().lower()
    return _HISTORY_STATUS_ALIASES.get(normalized, normalized)


def _normalize_progress_value(progress) -> float:
    """把进度统一归一化到 0~1.0。"""
    try:
        value = float(progress or 0)
    except (TypeError, ValueError):
        return 0.0

    if value < 0:
        return 0.0

    # 兼容旧数据中可能出现的 0~100 百分比写法
    if value > 1.0:
        value /= 100.0

    return min(value, 1.0)


def _is_completed_progress(progress) -> bool:
    """判断进度是否已经达到完成。"""
    return _normalize_progress_value(progress) >= 1.0


def _now_iso() -> str:
    """返回带时区的当前时间字符串。"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso_datetime(value):
    """解析 ISO 时间字符串，失败时返回 None。"""
    if not value:
        return None

    try:
        parsed_value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed_value.tzinfo is not None:
            return parsed_value.astimezone().replace(tzinfo=None)
        return parsed_value
    except Exception:
        return None


class DownloadHistory:
    def __init__(self, history_file: str = None):
        self.history_file = history_file or HISTORY_FILE
        self._history: dict = self._load()

    def _load(self) -> dict:
        migrated = False
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 兼容旧格式
                    if "records" in data:
                        result = data["records"]
                        # 为旧记录添加新字段（数据迁移）
                        for tid, record in result.items():
                            if "site_name" not in record:
                                record["site_name"] = ""
                                migrated = True
                            if "category" not in record:
                                record["category"] = ""
                                migrated = True
                            if "size" not in record:
                                record["size"] = 0.0
                                migrated = True
                            progress_history = record.get("progress_history")
                            if not isinstance(progress_history, list):
                                record["progress_history"] = []
                                progress_history = record["progress_history"]
                                migrated = True
                            else:
                                normalized_history = []
                                for item in progress_history:
                                    if isinstance(item, dict):
                                        normalized_item = dict(item)
                                        normalized_progress = _normalize_progress_value(
                                            normalized_item.get("progress", 0)
                                        )
                                        if normalized_item.get("progress") != normalized_progress:
                                            normalized_item["progress"] = normalized_progress
                                            migrated = True
                                        normalized_history.append(normalized_item)
                                    else:
                                        normalized_history.append(item)
                                if normalized_history != progress_history:
                                    record["progress_history"] = normalized_history
                                    progress_history = normalized_history
                                    migrated = True
                            last_progress = 0.0
                            last_progress_time = None
                            if progress_history:
                                last_item = progress_history[-1]
                                if isinstance(last_item, dict):
                                    last_progress = last_item.get("progress", 0)
                                    last_progress_time = last_item.get("time")

                            progress_completed = _is_completed_progress(last_progress)
                            current_status = _normalize_history_status(record.get("status", ""))
                            if not current_status:
                                record["status"] = "completed" if progress_completed else "downloading"
                                migrated = True
                                current_status = record["status"]
                            elif progress_completed and current_status not in {"completed", "seeding"}:
                                record["status"] = "completed"
                                migrated = True
                                current_status = "completed"

                            if current_status in {"completed", "seeding"} and not record.get("completed_time"):
                                record["completed_time"] = (
                                    last_progress_time
                                    or record.get("added_at")
                                    or _now_iso()
                                )
                                migrated = True
                            if "completed_time" not in record:
                                record["completed_time"] = None
                                migrated = True
                            if "download_start_notified_at" not in record:
                                record["download_start_notified_at"] = None
                                migrated = True
                            if "download_complete_notified_at" not in record:
                                if current_status in {"completed", "seeding"}:
                                    record["download_complete_notified_at"] = (
                                        record.get("completed_time")
                                        or record.get("added_at")
                                        or _now_iso()
                                    )
                                else:
                                    record["download_complete_notified_at"] = None
                                migrated = True
                            if self._ensure_record_defaults(record):
                                migrated = True
                        logger.debug(f"{LOG_HISTORY} 加载成功，共 {len(result)} 条记录")
                        if migrated:
                            logger.info(f"{LOG_HISTORY} 执行数据迁移，为旧记录添加新字段")
                            self._history = result
                            self._save()
                        return result
                    elif "ids" in data:
                        # 旧格式转换
                        result = {
                            tid: {
                                "title": "",
                                "hash": "",
                                "added_at": "",
                                "progress_history": [],
                                "site_name": "",
                                "category": "",
                                "size": 0.0,
                                "status": "completed",
                                "completed_time": None,
                                "download_start_notified_at": None,
                                "download_complete_notified_at": None,
                                "deleted_at": None,
                                "deleted_reason": None,
                                "deleted_source": None,
                                "deleted_from_status": None,
                                "deleted_files": False,
                            }
                            for tid in data.get("ids", [])
                        }
                        logger.debug(f"{LOG_HISTORY} 旧格式转换，共 {len(result)} 条记录")
                        self._history = result
                        self._save()
                        return result
            except Exception as e:
                logger.exception(f"{LOG_HISTORY} 加载失败：{e}")
        logger.debug(f"{LOG_HISTORY} 历史记录文件不存在，创建空记录")
        return {}

    def _save(self):
        dir_name = os.path.dirname(self.history_file)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "records": self._history,
                        "updated": _now_iso(),
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"{LOG_HISTORY} 保存失败：{e}")

    @staticmethod
    def _is_deleted_record(record: dict) -> bool:
        if not isinstance(record, dict):
            return False
        if record.get("deleted_at"):
            return True
        return _normalize_history_status(record.get("status", "")) == "deleted"

    @staticmethod
    def _ensure_record_defaults(record: dict) -> bool:
        """为单条记录补齐删除相关字段。"""
        if not isinstance(record, dict):
            return False

        migrated = False
        default_fields = {
            "deleted_at": None,
            "deleted_reason": None,
            "deleted_source": None,
            "deleted_from_status": None,
            "deleted_files": False,
        }

        for field, default_value in default_fields.items():
            if field not in record:
                record[field] = default_value
                migrated = True

        if record.get("deleted_at") and _normalize_history_status(record.get("status", "")) != "deleted":
            record["status"] = "deleted"
            migrated = True

        return migrated

    def contains(self, torrent_id: str) -> bool:
        return torrent_id in self._history
    
    def get_downloaded_ids(self) -> set:
        """获取所有已下载的种子 ID 集合（用于批量查询）"""
        return set(self._history.keys())

    def add(
        self,
        torrent_id: str,
        title: str = "",
        torrent_hash: str = "",
        site_name: str = "",
        category: str = "",
        size: float = 0.0,
    ):
        """添加历史记录
        
        Args:
            torrent_id: 种子 ID
            title: 种子标题
            torrent_hash: 种子 hash
            site_name: 来源站点名称
            size: 种子大小（GB）
        """
        self._history[torrent_id] = {
            "title": title,
            "hash": torrent_hash,
            "site_name": site_name,
            "category": category,
            "size": size,
            "status": "downloading",  # 状态：downloading/completed/paused/seeding
            "added_at": _now_iso(),
            "completed_time": None,  # 完成时间
            "progress_history": [],  # 记录进度变化
            "download_start_notified_at": None,
            "download_complete_notified_at": None,
            "deleted_at": None,
            "deleted_reason": None,
            "deleted_source": None,
            "deleted_from_status": None,
            "deleted_files": False,
        }
        self._save()
        logger.debug(f"{LOG_HISTORY} 已记录：{torrent_id}")

    def mark_notification_sent(self, torrent_id: str, notification_type: str):
        """记录某类通知已发送。"""
        if torrent_id not in self._history:
            return
        if self._is_deleted_record(self._history.get(torrent_id)):
            return

        field_map = {
            "download_start": "download_start_notified_at",
            "download_complete": "download_complete_notified_at",
        }
        field_name = field_map.get(notification_type)
        if not field_name:
            return

        self._history[torrent_id][field_name] = _now_iso()
        self._save()

    def update_progress(self, torrent_id: str, progress: float):
        """更新种子进度"""
        if torrent_id in self._history:
            if self._is_deleted_record(self._history[torrent_id]):
                return
            normalized_progress = _normalize_progress_value(progress)
            self._history[torrent_id]["progress_history"].append({
                "progress": normalized_progress,
                "time": _now_iso()
            })
            # 只保留最近 100 条记录
            if len(self._history[torrent_id]["progress_history"]) > 100:
                self._history[torrent_id]["progress_history"] = self._history[torrent_id]["progress_history"][-100:]
            
            # 如果进度达到 1.0（100%），更新状态和完成时间
            current_status = _normalize_history_status(self._history[torrent_id].get("status", ""))
            if _is_completed_progress(normalized_progress) and current_status not in {"completed", "seeding"}:
                self._history[torrent_id]["status"] = "completed"
                self._history[torrent_id]["completed_time"] = _now_iso()
            
            self._save()
    
    def update_status(self, torrent_id: str, status: str):
        """更新种子状态
        
        Args:
            torrent_id: 种子 ID
            status: 状态（downloading/completed/seeding/paused）
        """
        if torrent_id in self._history:
            if self._is_deleted_record(self._history[torrent_id]):
                return
            normalized_status = _normalize_history_status(status)
            self._history[torrent_id]["status"] = normalized_status
            if normalized_status in {"completed", "seeding"} and not self._history[torrent_id].get("completed_time"):
                self._history[torrent_id]["completed_time"] = _now_iso()
            self._save()

    def find_torrent_ids_by_hash(self, torrent_hash: str) -> list[str]:
        """按 hash 查找历史记录 ID，支持同一 hash 对应多条记录。"""
        normalized_hash = str(torrent_hash or "").strip()
        if not normalized_hash:
            return []

        return [
            torrent_id
            for torrent_id, record in self._history.items()
            if str(record.get("hash", "") or "").strip() == normalized_hash
        ]

    def mark_deleted(
        self,
        torrent_id: str,
        *,
        source: str = "qb_sync",
        reason: str = "",
        delete_files: bool = False,
        deleted_at: str = None,
    ) -> bool:
        """把历史记录标记为已删除，但保留记录。"""
        record = self._history.get(torrent_id)
        if not isinstance(record, dict):
            return False

        if self._is_deleted_record(record):
            changed = self._ensure_record_defaults(record)
            if changed:
                self._save()
            return False

        current_status = _normalize_history_status(record.get("status", "")) or "unknown"
        record["deleted_at"] = deleted_at or _now_iso()
        record["deleted_source"] = str(source or "").strip() or "qb_sync"
        record["deleted_reason"] = str(reason or "").strip() or "unknown_removed"
        record["deleted_from_status"] = current_status
        record["deleted_files"] = bool(delete_files)

        if self._is_completed_record(record) and not record.get("completed_time"):
            record["completed_time"] = self._get_record_completed_time(record) or record["deleted_at"]

        record["status"] = "deleted"
        self._save()
        return True

    def get_record(self, torrent_id: str) -> dict:
        """获取单条记录"""
        return self._history.get(torrent_id, {})

    @staticmethod
    def _is_completed_record(record: dict) -> bool:
        if not isinstance(record, dict):
            return False

        if record.get("completed_time"):
            return True

        if _normalize_history_status(record.get("status", "")) in {"completed", "seeding"}:
            return True

        progress_history = record.get("progress_history", [])
        if not isinstance(progress_history, list) or not progress_history:
            return False

        last_item = progress_history[-1]
        if not isinstance(last_item, dict):
            return False

        return _is_completed_progress(last_item.get("progress", 0))

    @staticmethod
    def _get_record_completed_time(record: dict):
        if not isinstance(record, dict):
            return None

        completed_time = _parse_iso_datetime(record.get("completed_time"))
        if completed_time:
            return completed_time

        if not DownloadHistory._is_completed_record(record):
            return None

        progress_history = record.get("progress_history", [])
        if isinstance(progress_history, list) and progress_history:
            last_item = progress_history[-1]
            if isinstance(last_item, dict):
                last_time = _parse_iso_datetime(last_item.get("time"))
                if last_time:
                    return last_time

        return _parse_iso_datetime(record.get("added_at"))

    def get_max_progress(self, torrent_id: str) -> float:
        """获取种子的最大进度"""
        if torrent_id not in self._history:
            return 0.0
        history = self._history[torrent_id].get("progress_history", [])
        if not history:
            return 0.0
        return max(
            _normalize_progress_value(p.get("progress", 0))
            for p in history
            if isinstance(p, dict)
        ) if any(isinstance(p, dict) for p in history) else 0.0

    def get_completion_statistics(self, now=None) -> dict:
        """获取历史完成统计。"""
        from datetime import timedelta

        current_time = now or datetime.now()
        today_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)

        total_records = len(self._history)
        total_completed = 0
        today_completed = 0
        week_completed = 0
        total_deleted = 0
        today_deleted = 0
        week_deleted = 0

        for record in self._history.values():
            deleted_time = _parse_iso_datetime(record.get("deleted_at"))
            if deleted_time:
                total_deleted += 1
                if deleted_time >= today_start:
                    today_deleted += 1
                if deleted_time >= week_start:
                    week_deleted += 1

            if not self._is_completed_record(record):
                continue

            total_completed += 1
            completed_time = self._get_record_completed_time(record)
            if not completed_time:
                continue

            if completed_time >= today_start:
                today_completed += 1
            if completed_time >= week_start:
                week_completed += 1

        return {
            "today_completed": today_completed,
            "week_completed": week_completed,
            "total_completed": total_completed,
            "total_records": total_records,
            "today_deleted": today_deleted,
            "week_deleted": week_deleted,
            "total_deleted": total_deleted,
        }

    def count(self) -> int:
        return len(self._history)

    def get_all(self) -> dict:
        return self._history

    def cleanup_old_records(self, max_age_days: int = 30) -> int:
        """
        清理超过指定天数的历史记录
        
        Args:
            max_age_days: 最大保存天数，默认 30 天
        
        Returns:
            清理的记录数量
        """
        if max_age_days <= 0:
            logger.debug(f"{LOG_HISTORY} 自动清理已禁用（max_age_days={max_age_days}）")
            return 0
        
        from datetime import timedelta
        
        cutoff = datetime.now() - timedelta(days=max_age_days)
        to_delete = []
        
        for tid, info in self._history.items():
            added_at = info.get('added_at', '')
            if added_at:
                try:
                    # 解析 ISO 格式时间
                    record_time = _parse_iso_datetime(added_at)
                    if record_time and record_time < cutoff:
                        to_delete.append(tid)
                except Exception as e:
                    logger.warning(f"{LOG_HISTORY} 解析时间失败：{tid} - {e}")
        
        # 删除过期记录
        for tid in to_delete:
            del self._history[tid]
        
        if to_delete:
            self._save()
            logger.info(f"{LOG_HISTORY} 自动清理完成，删除 {len(to_delete)} 条超过 {max_age_days} 天 的记录")
        else:
            logger.debug(f"{LOG_HISTORY} 无需清理，所有记录都在 {max_age_days} 天内")
        
        return len(to_delete)
