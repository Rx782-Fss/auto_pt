"""
种子检查运行器 - 独立于 main.py 和 web.py

用途:
- 提供统一的种子检查入口
- 支持多站点遍历
- 可被 main.py 和 web.py 共同使用
- 避免循环导入和日志系统冲突
"""

import time
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any
from .config import Config, get_qbittorrent_host
from .mteam import MTeamClient
from .qbittorrent import QBittorrentClient
from .filter import TorrentFilter
from .history import DownloadHistory
from .qb_status import qb_state_to_status
from .notifications import (
    normalize_notification_settings,
    notification_settings_complete,
    send_email_notification,
)
from .logger_config import get_logger, PerformanceTimer
from .log_constants import LOG_MAIN, LOG_QB_GET, LOG_SITE_CHECK, LOG_SITE_DOWNLOAD, LOG_SITE_CLEANUP


# 站点类型到客户端类的映射
SITE_CLIENTS = {
    "mteam": MTeamClient,
    # 未来可以添加更多站点类型
    # "hdsky": HDSkyClient,
    # "ourbits": OurBitsClient,
}

# 模块级别的清理状态，用于记录各站点最近一次清理的时间戳
_cleanup_state = {
    "last_cleanup": {}  # 站点名称 -> 最后清理时间戳
}


def create_site_client(site_type: str, site_config: Dict[str, Any]):
    """工厂模式创建站点客户端"""
    client_class = SITE_CLIENTS.get(site_type)
    if not client_class:
        logger = get_logger(__name__)
        logger.warning(f"{LOG_SITE_CHECK} 未知的站点类型：{site_type}，使用 MTeamClient")
        client_class = MTeamClient
    
    return client_class(
        base_url=site_config.get("base_url", ""),
        rss_url=site_config.get("rss_url", ""),
        passkey=site_config.get("passkey", ""),
        uid=site_config.get("uid", ""),
        categories=site_config.get("categories", []),
        category_map=site_config.get("category_map", {}),
        site_name=site_config.get("name", "Unknown"),  # 传递站点名称
    )


def _format_torrent_size(size: Any) -> str:
    """把种子大小格式化为邮件里更易读的文本。"""
    try:
        size_value = float(size)
    except Exception:
        return "未知"

    if size_value <= 0:
        return "未知"
    return f"{size_value:.2f} GB"


def _build_download_notification_body(
    event_label: str,
    site_name: str,
    title: str,
    size: Any,
    category: str,
    torrent_hash: str,
) -> str:
    """构建下载类邮件正文。"""
    return (
        f"Auto PT Downloader {event_label}\n\n"
        f"站点：{site_name or '未知'}\n"
        f"种子：{title or '未知'}\n"
        f"大小：{_format_torrent_size(size)}\n"
        f"分类：{category or '未知'}\n"
        f"Hash：{torrent_hash or '未知'}\n"
        f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    )


def _send_download_notification(
    notification_settings: Dict[str, Any],
    event_key: str,
    subject: str,
    body: str,
) -> tuple[bool, str]:
    """发送下载事件邮件通知。"""
    normalized_notifications = normalize_notification_settings(notification_settings or {})
    if not normalized_notifications.get(event_key, False):
        return False, "通知未启用"

    if not notification_settings_complete(normalized_notifications):
        return False, "邮件通知配置不完整"

    return send_email_notification(
        normalized_notifications,
        subject=subject,
        text=body,
        require_enabled=False,
    )


def _infer_deleted_reason(record: Dict[str, Any]) -> str:
    """根据历史记录推断删除原因，尽量区分完成后删除与下载中删除。"""
    status = str(record.get("status", "") or "").strip().lower()

    if record.get("completed_time"):
        return "manual_removed_after_complete"

    if status == "completed":
        return "manual_removed_after_complete"

    progress_history = record.get("progress_history", [])
    if isinstance(progress_history, list) and progress_history:
        last_item = progress_history[-1]
        if isinstance(last_item, dict):
            try:
                if float(last_item.get("progress", 0) or 0) >= 1.0:
                    return "manual_removed_after_complete"
            except Exception:
                pass

    if status == "paused":
        return "manual_removed_paused"

    return "manual_removed_during_download"


def process_single_site(
    site: Dict[str, Any],
    qb: QBittorrentClient,
    qb_config: Dict[str, Any],
    history: DownloadHistory,
    dry_run: bool = False,
    notification_settings: Optional[Dict[str, Any]] = None,
) -> Tuple[int, int]:
    """
    处理单个站点的种子检查
    
    Args:
        site: 站点配置
        qb: qBittorrent 客户端实例（所有站点共用）
        qb_config: qBittorrent 配置
        history: 下载历史记录
        dry_run: 是否为预检模式
    
    Returns:
        (filtered_count, new_count) - 筛选后的种子数和新增种子数
    """
    logger = get_logger(__name__)
    perf_timer = PerformanceTimer(logger)
    
    site_name = site.get("name", "unknown")
    site_type = site.get("type", "mteam")
    site_filter_config = site.get("filter", {})
    
    # 检查自动下载开关
    auto_download = site.get("download_settings", {}).get("auto_download", False)
    
    logger.info(f"{LOG_SITE_CHECK} [{site_name}] 开始检查种子...")
    
    # 创建站点客户端
    site_client = create_site_client(site_type, site)
    
    # 创建筛选器
    torrent_filter = TorrentFilter(site_filter_config)
    
    # 获取种子
    perf_timer.start(f"fetch_{site_name}")
    torrents = site_client.fetch_torrents()
    perf_timer.end(f"fetch_{site_name}")
    logger.info(f"{LOG_SITE_CHECK} [{site_name}] 获取到 {len(torrents)} 个种子")
    
    # 筛选种子
    perf_timer.start(f"filter_{site_name}")
    filtered = [t for t in torrents if torrent_filter.filter(t)]
    perf_timer.end(f"filter_{site_name}")
    logger.info(f"{LOG_SITE_CHECK} [{site_name}] 筛选后剩余 {len(filtered)} 个种子")
    
    # 处理种子
    new_count = 0
    skipped_count = 0
    
    for torrent in filtered:
        if history.contains(torrent.torrent_id):
            logger.debug(f"{LOG_SITE_CHECK} [{site_name}] 已下载过：{torrent.title}")
            skipped_count += 1
            continue
        
        logger.info(f"{LOG_SITE_DOWNLOAD} [{site_name}] 处理：{torrent.title}")
        
        # 检查自动下载开关：如果关闭，只记录不下载
        if not auto_download:
            logger.debug(f"{LOG_SITE_DOWNLOAD} [{site_name}] 自动下载已关闭，跳过：{torrent.title}")
            skipped_count += 1
            continue
        
        # 预检模式只返回种子列表，不下载
        if dry_run:
            new_count += 1
            continue
        
        # 下载种子文件
        perf_timer.start(f"download_{site_name}")
        torrent_data = site_client.download_torrent(torrent)
        perf_timer.end(f"download_{site_name}")
        
        if not torrent_data:
            logger.error(f"{LOG_SITE_DOWNLOAD} [{site_name}] 下载失败：{torrent.title}")
            continue
        
        # 添加到 qBittorrent（所有站点共用同一个实例）
        perf_timer.start(f"qb_add_{site_name}")
        
        # 获取站点 tags：优先使用站点配置，其次全局配置，最后默认值
        site_tags_from_config = site.get("tags", [])  # 站点配置的 tags（可能是数组或字符串）
        
        # 统一处理为数组
        if isinstance(site_tags_from_config, str):
            # 如果是字符串，逗号分隔
            site_tags = [t.strip() for t in site_tags_from_config.split(",") if t.strip()]
        elif isinstance(site_tags_from_config, list):
            site_tags = site_tags_from_config
        else:
            site_tags = []
        
        # 如果站点 tags 为空，使用默认值
        final_tags = site_tags if site_tags else ["auto_pt"]
        
        # 记录日志
        logger.info(f"{LOG_SITE_DOWNLOAD} [{site_name}] 使用标签：{final_tags}")
        
        success, torrent_hash = qb.add_torrent(
            torrent_data=torrent_data,
            save_path=qb_config.get("save_path", ""),
            category=qb_config.get("category", ""),
            tags=final_tags,
            is_paused=qb_config.get("pause_added", False),
            torrent_title=torrent.title,
        )
        perf_timer.end(f"qb_add_{site_name}")
        
        if success:
            # 添加历史记录，包含站点名称和大小
            logger.debug(
                f"{LOG_SITE_DOWNLOAD} [{site_name}] 准备写入历史记录："
                f"torrent_id={torrent.torrent_id}, source_site={torrent.site_name}, size={torrent.size}"
            )
            history.add(
                torrent.torrent_id, 
                torrent.title, 
                torrent_hash,
                site_name=torrent.site_name,
                category=torrent.category,
                size=torrent.size
            )

            if notification_settings and not qb_config.get("pause_added", False):
                start_subject = f"Auto PT 下载开始 - {site_name}"
                start_body = _build_download_notification_body(
                    "下载开始",
                    site_name=site_name,
                    title=torrent.title,
                    size=torrent.size,
                    category=torrent.category,
                    torrent_hash=torrent_hash or torrent.torrent_id,
                )
                start_success, start_message = _send_download_notification(
                    notification_settings,
                    "download_start_enabled",
                    start_subject,
                    start_body,
                )
                if start_success:
                    try:
                        history.mark_notification_sent(torrent.torrent_id, "download_start")
                    except Exception as notify_exc:
                        logger.debug(f"{LOG_SITE_DOWNLOAD} [{site_name}] 标记开始通知失败：{notify_exc}")
                    logger.info(f"{LOG_SITE_DOWNLOAD} [{site_name}] 已发送下载开始邮件：{torrent.title}")
                elif start_message not in {"通知未启用", "邮件通知配置不完整"}:
                    logger.warning(f"{LOG_SITE_DOWNLOAD} [{site_name}] 下载开始邮件发送失败：{start_message}")

            # 更新初始进度
            if torrent_hash:
                time.sleep(0.5)
                try:
                    torrents_list = qb.get_torrents()
                    for t in torrents_list:
                        if t.get('hash') == torrent_hash:
                            history.update_progress(torrent.torrent_id, t.get('progress', 0))
                            break
                except Exception as e:
                    logger.debug(f"{LOG_QB_GET} 获取初始进度失败：{e}")

            new_count += 1
            logger.info(f"{LOG_SITE_DOWNLOAD} [{site_name}] 已添加到 qBittorrent：{torrent.title}")
        else:
            logger.error(f"{LOG_SITE_DOWNLOAD} [{site_name}] 添加失败：{torrent.title}")
    
    logger.info(f"{LOG_SITE_CHECK} [{site_name}] 检查完成，新增 {new_count} 个种子，跳过 {skipped_count} 个")
    
    # 输出性能统计
    perf_timer.report(level="debug")
    
# 清理逻辑已移除：由 main.run_daemon 统一调度清理，保留 RSS 检查和下载

    
    return len(filtered), new_count


def run_check(config: Optional[Config] = None, dry_run: bool = False) -> Tuple[int, int]:
    """
    执行一次种子检查（支持多站点遍历）
    
    Args:
        config: 配置对象，为 None 时自动加载
        dry_run: 是否为预检模式（仅获取种子，不下载）
    
    Returns:
        (total_count, new_count) - 总种子数和新增种子数
    """
    if config is None:
        config = Config()
    
    logger = get_logger(__name__)
    perf_timer = PerformanceTimer(logger)
    
    perf_timer.start("run_check")
    logger.info(f"{LOG_MAIN} 开始检查种子...")
    
    # 获取所有启用的站点
    enabled_sites = config.get_enabled_sites()
    
    if not enabled_sites:
        logger.warning(f"{LOG_MAIN} 没有启用的站点")
        return 0, 0
    
    logger.info(f"{LOG_MAIN} 共有 {len(enabled_sites)} 个启用的站点")
    
    # 初始化 qBittorrent 客户端（所有站点共用）
    qb_config = config.qbittorrent
    qb = QBittorrentClient(
        host=get_qbittorrent_host(qb_config),
        username=qb_config.get("username", ""),
        password=qb_config.get("password", ""),
    )
    
    # 初始化历史记录
    history = DownloadHistory()
    
    # 遍历所有启用的站点
    total_filtered = 0
    total_new = 0
    
    # 从配置读取站点间隔（带默认值）
    site_interval = config.get('site_interval', 5)
    
    for i, site in enumerate(enabled_sites):
        try:
            # 站点间间隔：避免同时请求触发限流（429）
            if i > 0 and site_interval > 0:
                time.sleep(site_interval)  # 使用配置值
            
            filtered_count, new_count = process_single_site(
                site=site,
                qb=qb,
                qb_config=qb_config,
                history=history,
                dry_run=dry_run,
                notification_settings=config.notifications,
            )
            total_filtered += filtered_count
            total_new += new_count
        except Exception as e:
            logger.error(f"{LOG_SITE_CHECK} 站点 [{site.get('name')}] 处理失败：{e}")
            continue
    
    perf_timer.end("run_check")
    logger.info(f"{LOG_MAIN} 所有站点检查完成，总计新增 {total_new} 个种子")
    
    # 输出性能统计
    perf_timer.report(level="debug")
    
    return total_filtered, total_new


def sync_download_completion_notifications(config: Optional[Config] = None) -> int:
    """
    同步检查已完成的下载并发送完成通知。

    Args:
        config: 配置对象，为 None 时自动加载

    Returns:
        本次发送的完成通知数量
    """
    if config is None:
        config = Config()

    logger = get_logger(__name__)
    notification_settings = normalize_notification_settings(config.notifications)
    notification_ready = notification_settings_complete(notification_settings)
    complete_notification_enabled = bool(notification_settings.get("download_complete_enabled", False))
    if not notification_ready:
        logger.debug(f"{LOG_SITE_DOWNLOAD} 邮件通知配置不完整，仅同步状态，不发送完成邮件")
    elif not complete_notification_enabled:
        logger.debug(f"{LOG_SITE_DOWNLOAD} 下载完成邮件通知未启用，仅同步状态，不发送完成邮件")

    qb_config = config.qbittorrent
    qb = QBittorrentClient(
        host=get_qbittorrent_host(qb_config),
        username=qb_config.get("username", ""),
        password=qb_config.get("password", ""),
    )
    history = DownloadHistory()

    try:
        torrents = qb.get_torrents()
    except Exception as exc:
        logger.warning(f"{LOG_QB_GET} 获取 qBittorrent 列表失败，跳过完成通知同步：{exc}")
        return 0

    torrent_map = {
        str(t.get("hash", "") or "").strip(): t
        for t in torrents
        if str(t.get("hash", "") or "").strip()
    }

    notified_count = 0
    for torrent_id, record in history.get_all().items():
        if record.get("deleted_at"):
            continue

        torrent_hash = str(record.get("hash", "") or "").strip()
        if not torrent_hash:
            continue

        qb_torrent = torrent_map.get(torrent_hash)
        if not qb_torrent:
            continue

        qb_status = qb_state_to_status(
            qb_torrent.get("progress", 0),
            qb_torrent.get("state", ""),
        )
        if qb_status.get("state") not in {"completed", "seeding"}:
            continue
        desired_status = "seeding" if qb_status.get("state") == "seeding" else "completed"

        site_name = str(record.get("site_name", "") or "").strip() or "未知站点"
        title = str(record.get("title", "") or "").strip() or str(qb_torrent.get("name", "") or "").strip() or "未知"
        category = str(record.get("category", "") or "").strip() or str(qb_torrent.get("category", "") or "").strip()
        size = record.get("size", qb_torrent.get("size", 0))

        try:
            if str(record.get("status", "") or "").strip().lower() != desired_status or not record.get("completed_time"):
                history.update_status(torrent_id, desired_status)
        except Exception as sync_exc:
            logger.debug(f"{LOG_SITE_DOWNLOAD} [{site_name}] 同步完成状态失败：{sync_exc}")

        if record.get("download_complete_notified_at"):
            continue

        if not (notification_ready and complete_notification_enabled):
            continue

        subject = f"Auto PT 下载完成 - {site_name}"
        body = _build_download_notification_body(
            "下载完成",
            site_name=site_name,
            title=title,
            size=size,
            category=category,
            torrent_hash=torrent_hash,
        )
        success, message = _send_download_notification(
            notification_settings,
            "download_complete_enabled",
            subject,
            body,
        )
        if not success:
            if message not in {"通知未启用", "邮件通知配置不完整"}:
                logger.warning(f"{LOG_SITE_DOWNLOAD} [{site_name}] 下载完成邮件发送失败：{message}")
            continue

        try:
            history.mark_notification_sent(torrent_id, "download_complete")
        except Exception as notify_exc:
            logger.debug(f"{LOG_SITE_DOWNLOAD} [{site_name}] 标记完成通知失败：{notify_exc}")

        logger.info(f"{LOG_SITE_DOWNLOAD} [{site_name}] 已发送下载完成邮件：{title}")
        notified_count += 1

    return notified_count


def cleanup_completed(config: Optional[Config] = None) -> int:
    """
    清理已完成的种子（基于站点配置）
    
    Args:
        config: 配置对象，为 None 时自动加载
    
    Returns:
        删除的种子数量
    """
    if config is None:
        config = Config()
    
    logger = get_logger(__name__)
    qb_config = config.qbittorrent
    
    # 获取所有启用的站点
    enabled_sites = config.get_enabled_sites()
    
    if not enabled_sites:
        logger.debug(f"{LOG_SITE_CLEANUP} 没有启用的站点，跳过清理")
        return 0
    
    # 初始化 qBittorrent 客户端
    qb = QBittorrentClient(
        host=get_qbittorrent_host(qb_config),
        username=qb_config.get("username", ""),
        password=qb_config.get("password", ""),
    )
    history = DownloadHistory()
    
    total_deleted = 0
    
    # 遍历每个站点，根据站点配置清理
    for site in enabled_sites:
        site_name = site.get("name", "unknown")
        
        # 检查站点是否启用自动删除
        download_settings = site.get("download_settings", {})
        auto_delete = download_settings.get("auto_delete", False)
        
        if not auto_delete:
            logger.debug(f"{LOG_SITE_CLEANUP} [{site_name}] 未启用自动删除，跳过")
            continue
        # 获取站点级清理间隔并进行站点级限流判断
        cleanup_interval = site.get("schedule", {}).get("cleanup_interval", 0)
        rss_interval = site.get("schedule", {}).get("interval", 300)
        if cleanup_interval <= 0:
            cleanup_interval = rss_interval
        # 当前时间戳，用于判断距离上次清理的间隔
        site_current_time = time.time()
        last_cleanup = _cleanup_state["last_cleanup"].get(site_name, 0)
        if site_current_time - last_cleanup < cleanup_interval:
            logger.debug(
                f"{LOG_SITE_CLEANUP} [{site_name}] 距离上次清理 "
                f"{site_current_time - last_cleanup:.0f} 秒 < {cleanup_interval} 秒，跳过"
            )
            continue
        logger.debug(f"{LOG_SITE_CLEANUP} [{site_name}] 清理间隔设置为 {cleanup_interval} 秒（RSS 间隔={rss_interval} 秒）")
        
        # 获取站点标签
        site_tags = site.get("tags", [])
        if isinstance(site_tags, str):
            site_tags = [t.strip() for t in site_tags.split(",") if t.strip()]
        
        if not site_tags:
            site_tags = ["auto_pt"]
        
        # 使用站点的第一个标签
        tag = site_tags[0]
        
        # 获取站点的删除文件配置
        delete_files = download_settings.get("delete_files", False)
        
        logger.info(
            f"{LOG_SITE_CLEANUP} [{site_name}] 清理已完成种子"
            f"（tag={tag}, delete_files={delete_files}, 清理间隔={cleanup_interval}秒）"
        )
        
        # 获取已完成且做种完成的种子
        completed = qb.get_completed_torrents(tag)
        deleted_count = 0
        
        for t in completed:
            name = t.get("name", "")
            hash_ = t.get("hash", "")
            
            if qb.delete_torrent(hash_, delete_files=delete_files):
                for torrent_id in history.find_torrent_ids_by_hash(hash_):
                    try:
                        history.mark_deleted(
                            torrent_id,
                            source="auto_cleanup",
                            reason="auto_cleanup_completed",
                            delete_files=delete_files,
                        )
                    except Exception as mark_exc:
                        logger.debug(f"{LOG_SITE_CLEANUP} [{site_name}] 标记删除失败：{mark_exc}")
                logger.info(f"{LOG_SITE_CLEANUP} [{site_name}] 删除已完成：{name}")
                deleted_count += 1
        
        logger.info(f"{LOG_SITE_CLEANUP} [{site_name}] 清理完成，删除 {deleted_count} 个种子")
        # 更新站点最近清理时间
        _cleanup_state["last_cleanup"][site_name] = time.time()
        total_deleted += deleted_count
    
    logger.info(f"{LOG_SITE_CLEANUP} 总清理完成，共删除 {total_deleted} 个种子")
    return total_deleted


def sync_deleted_history_records(config: Optional[Config] = None) -> int:
    """
    同步 qBittorrent 中已经消失的种子，并把它们标记为已删除。

    适合识别：
    - 完成后被用户手动删除
    - 下载过程中被用户手动删除
    - 其他从 qB 列表中消失但历史尚未标记删除的记录
    """
    if config is None:
        config = Config()

    logger = get_logger(__name__)
    qb_config = config.qbittorrent
    qb = QBittorrentClient(
        host=get_qbittorrent_host(qb_config),
        username=qb_config.get("username", ""),
        password=qb_config.get("password", ""),
    )

    try:
        torrents = qb.get_torrents(raise_on_error=True)
    except Exception as exc:
        logger.warning(f"{LOG_QB_GET} 获取 qBittorrent 列表失败，跳过删除同步：{exc}")
        return 0

    qb_hashes = {
        str(t.get("hash", "") or "").strip()
        for t in torrents
        if str(t.get("hash", "") or "").strip()
    }

    history = DownloadHistory()
    deleted_count = 0

    for torrent_id, record in list(history.get_all().items()):
        if record.get("deleted_at"):
            continue

        torrent_hash = str(record.get("hash", "") or "").strip()
        if not torrent_hash or torrent_hash in qb_hashes:
            continue

        deleted_reason = _infer_deleted_reason(record)
        if history.mark_deleted(
            torrent_id,
            source="qb_sync",
            reason=deleted_reason,
            delete_files=False,
        ):
            logger.info(
                f"{LOG_SITE_CLEANUP} [历史同步] 检测到 qB 已移除："
                f"{record.get('title', '')} ({deleted_reason})"
            )
            deleted_count += 1

    return deleted_count
