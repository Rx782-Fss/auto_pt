"""qBittorrent 状态归一化工具。"""

from __future__ import annotations

from typing import Any, Iterable


_SEEDING_STATES = {"uploading", "stalledup", "forcedup"}
_COMPLETED_STATES = {"pausedup"}
_DOWNLOADING_STATES = {"stalleddl", "downloading", "metadl", "forceddl", "allocating"}
_PAUSED_STATES = {"pauseddl", "stoppeddl", "queueddl", "checkingdl", "checkingresumedata"}


def normalize_qb_progress(progress: Any) -> float:
    """把进度统一归一化到 0~1.0。"""
    try:
        value = float(progress or 0)
    except (TypeError, ValueError):
        return 0.0

    if value < 0:
        return 0.0

    if value > 1.0:
        value /= 100.0

    return min(value, 1.0)


def normalize_qb_state(state: Any) -> str:
    """统一 qBittorrent 状态字符串格式。"""
    return str(state or "").strip().lower()


def qb_state_to_status(progress: Any, state: Any) -> dict[str, str]:
    """把 qB 状态转换为前端/历史使用的主状态。"""
    normalized_state = normalize_qb_state(state)
    progress_value = normalize_qb_progress(progress)

    if normalized_state in _SEEDING_STATES:
        return {"state": "seeding", "label": "做种中", "color": "green"}

    if normalized_state in _COMPLETED_STATES or progress_value >= 1.0:
        return {"state": "completed", "label": "已完成", "color": "green"}

    if normalized_state in _DOWNLOADING_STATES:
        return {"state": "downloading", "label": "下载中", "color": "blue"}

    if normalized_state in _PAUSED_STATES:
        return {"state": "paused", "label": "已暂停", "color": "orange"}

    return {"state": "active", "label": "活动中", "color": "blue"}


def summarize_qb_torrent_states(torrents: Iterable[dict[str, Any]]) -> dict[str, int]:
    """统计 qB 列表中的主状态数量。"""
    counts = {
        "downloading": 0,
        "completed": 0,
        "seeding": 0,
        "paused": 0,
        "active": 0,
    }

    for torrent in torrents or []:
        status = qb_state_to_status(
            torrent.get("progress", 0),
            torrent.get("state", ""),
        ).get("state", "active")
        counts[status] = counts.get(status, 0) + 1

    return counts
