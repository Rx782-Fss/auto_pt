#!/usr/bin/env python3
import os
import sys
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from src.config import Config, get_qbittorrent_host
from src.runner import (
    run_check,
    cleanup_completed,
    create_site_client,
    sync_download_completion_notifications,
    sync_deleted_history_records,
)
from src.history import DownloadHistory
from src.qbittorrent import QBittorrentClient
from src.logger_config import setup_logging, get_logger, log_startup_message, reload_logging
from src.log_constants import LOG_MAIN, LOG_DAEMON

# ==================== RSS 预获取功能（已禁用，保留代码供未来使用） ====================
# 如需启用，请取消以下所有代码的注释

# # RSS 预获取缓存（全局共享）
# _rss_prefetch_cache = {}
# _rss_prefetch_timestamps = {}

# def prefetch_rss_for_site(site_name, site_config, logger):
#     """
#     预获取单个站点的 RSS
    
#     Args:
#         site_name: 站点名称
#         site_config: 站点配置
#         logger: logger 对象
    
#     Returns:
#         int: 获取到的种子数量，失败返回 -1
#     """
#     try:
#         logger.debug(f"{LOG_DAEMON} [预获取] 开始为站点 {site_name} 预获取 RSS")
        
#         # 使用工厂模式创建站点客户端
#         site_client = create_site_client(site_config.get('type', 'mteam'), site_config)
        
#         # 获取种子列表
#         torrents = site_client.fetch_torrents()
        
#         if torrents:
#             # 更新缓存
#             import hashlib
#             import json
#             cache_key = hashlib.md5(json.dumps({
#                 'site': site_name,
#                 'rss_url_rss_url': site_config.get('rss_url', ''),
#             }, sort_keys=True).encode()).hexdigest()
            
#             _rss_prefetch_cache[cache_key] = {
#                 'data': torrents,
#                 'timestamp': time.time()
#             }
#             _rss_prefetch_timestamps[site_name] = time.time()
            
#             logger.info(f"{LOG_DAEMON} [预获取] {site_name} 成功，获取 {len(torrents)} 个种子")
#             return len(torrents)
#         else:
#             logger.warning(f"{LOG_DAEMON} [预获取] {site_name} 没有获取到种子")
#             return 0
            
#     except Exception as e:
#         logger.exception(f"{LOG_DAEMON} [预获取] {site_name} 失败：{e}")
#         return -1

# def prefetch_all_sites_rss(config: Config, logger):
#     """
#     预获取所有站点的 RSS
    
#     Args:
#         config: 配置对象
#         logger: logger 对象
    
#     Returns:
#         tuple: (成功数量，失败数量，总种子数）
#     """
#     sites = config.get_enabled_sites()  # 只获取启用的站点
#     if not sites:
#         logger.info(f"{LOG_DAEMON} [预获取] 没有启用的站点，跳过")
#         return (0, 0, 0)
    
#     logger.info(f"{LOG_DAEMON} [预获取] 开始为 {len(sites)} 个启用的站点预获取 RSS")
    
#     success_count = 0
#     fail_count = 0
#     total_torrents = 0
    
#     for site in sites:
#         site_name = site.get('name', 'unknown')
#         count = prefetch_rss_for_site(site_name, site, logger)
        
#         if count >= 0:
#             success_count += 1
#             total_torrents += count
#         else:
#             fail_count += 1
    
#     logger.info(f"{LOG_DAEMON} [预获取] 完成，成功 {success_count} 个，失败 {fail_count} 个，总种子 {total_torrents}")
#     return (success_count, fail_count, total_torrents)


# def get_rss_prefetch_cache():
#     """获取预获取缓存（供 web.py 使用）"""
#     return _rss_prefetch_cache
# ==================== RSS 预获取功能结束 ====================


def run_once(config: Config) -> int:
    """执行一次种子检查"""
    _, new_count = run_check(config)
    sync_download_completion_notifications(config)
    sync_deleted_history_records(config)
    return new_count


def cleanup_completed_task(config: Config) -> int:
    """清理已完成的种子（站点级独立判断）"""
    import time
    logger = get_logger(__name__)
    current_time = time.time()
    total_deleted = 0

    enabled_sites = config.get_enabled_sites()
    if not enabled_sites:
        return 0

    for site in enabled_sites:
        site_name = site.get("name", "unknown")
        download_settings = site.get("download_settings", {})
        auto_delete = download_settings.get("auto_delete", False)
        if not auto_delete:
            continue

        cleanup_interval = site.get("schedule", {}).get("cleanup_interval", 0)
        rss_interval = site.get("schedule", {}).get("interval", 300)
        if cleanup_interval <= 0:
            cleanup_interval = rss_interval

        last = _LAST_SITE_CLEANUP.get(site_name, 0)
        if current_time - last >= cleanup_interval:
            try:
                logger.info(f"{LOG_DAEMON} [{site_name}] 开始清理（间隔={cleanup_interval}秒）")
                # 调用原有清理入口，尽可能复用已有实现
                deleted = cleanup_completed(config)
                _LAST_SITE_CLEANUP[site_name] = current_time
                total_deleted += int(deleted)
            except Exception as e:
                logger.exception(f"{LOG_DAEMON} [{site_name}] 清理异常：{e}")

    return total_deleted


def cleanup_history_task(config: Config, max_retries: int = 3) -> int:
    """
    清理过期的历史记录（带重试机制）
    
    Args:
        config: 配置对象
        max_retries: 最大重试次数，默认 3 次
    
    Returns:
        删除的记录数量
    """
    history_max_age = config.global_schedule.get("history_max_age", 30)
    if history_max_age <= 0:
        return 0
    
    history = DownloadHistory()
    last_error = None
    logger = get_logger(__name__)  # 添加 logger
    
    # 记录清理前的数量
    before_count = history.count()
    logger.info(f"{LOG_DAEMON} 开始清理历史记录，当前记录数：{before_count}")
    
    # 重试机制
    for attempt in range(1, max_retries + 1):
        try:
            deleted = history.cleanup_old_records(history_max_age)
            
            # 验证删除是否成功
            after_count = history.count()
            expected_count = before_count - deleted
            
            if after_count == expected_count:
                logger.info(f"{LOG_DAEMON} 历史记录清理成功：删除 {deleted} 条记录，剩余 {after_count} 条")
                return deleted
            else:
                logger.warning(f"{LOG_DAEMON} 历史记录清理验证失败：预期 {expected_count} 条，实际 {after_count} 条")
                last_error = Exception(f"验证失败：预期{expected_count}条，实际{after_count}条")
                
        except Exception as e:
            last_error = e
            logger.exception(f"{LOG_DAEMON} 历史记录清理失败 (尝试 {attempt}/{max_retries})：{e}")
            
            if attempt < max_retries:
                wait_time = min(attempt * 10, 60)  # 等待时间：10 秒、20 秒、30 秒... 最多 60 秒
                logger.warning(f"{LOG_DAEMON} {wait_time}秒后重试...")
                time.sleep(wait_time)
    
    # 所有重试都失败
    logger.error(f"{LOG_DAEMON} 历史记录清理失败，已重试{max_retries}次：{last_error}")
    return 0


# 全局用于记录各站点最近一次清理时间的字典（站点名称 -> 时间戳）
_LAST_SITE_CLEANUP: dict = {}

# 全局变量：追踪每个站点的最后检查时间
_SITE_CHECK_STATE = {}

def run_daemon(config: Config):
    """守护进程：循环执行种子检查、清理和历史记录维护"""
    logger = get_logger(__name__)
    log_startup_message(logger, f"{LOG_DAEMON} 启动")
    
    last_check = 0
    last_cleanup = 0
    # last_prefetch = 0  # 上次预获取 RSS 的时间（已禁用）
    last_config_mtime = 0  # 初始化配置修改时间
    history_cleanup_done = False  # 标记今天是否已清理
    last_logging_config_hash = hash(str(sorted((config.logging_config or {}).items())))
    
    while True:
        current_time = time.time()
        now = datetime.now()
        
        config.reload()
        current_logging_config = dict(config.logging_config or {})
        current_logging_hash = hash(str(sorted(current_logging_config.items())))
        if current_logging_hash != last_logging_config_hash:
            logger.info(f"{LOG_DAEMON} 日志配置已更新，重新加载日志器")
            reload_logging(current_logging_config)
            logger = get_logger(__name__)
            last_logging_config_hash = current_logging_hash
        schedule = config.global_schedule
        check_interval = schedule.get("interval", 300)
        # prefetch_interval = schedule.get("prefetch_interval", 3600)  # ԤȡĬ 60 ӣѽã
        history_max_age = schedule.get("history_max_age", 30)  # ʷ¼
        qb_config = config.qbittorrent

        # ǷվԶɾվ㼶ã
        enabled_sites = config.get_enabled_sites()
        auto_delete = any(
            site.get("download_settings", {}).get("auto_delete", False)
            for site in enabled_sites
        )
        
        config_path = config.config_path
        if os.path.exists(config_path):
            current_mtime = os.path.getmtime(config_path)
            if current_mtime != last_config_mtime:
                last_config_mtime = current_mtime
                last_check = 0
                # last_prefetch = 0  # 配置变更，重置预获取计时器（已禁用）
                logger.info(f"{LOG_DAEMON} 配置文件变更，重置计时器")
        
        # 预获取 RSS（后台任务）- 已禁用，保留代码供未来使用
        # if current_time - last_prefetch >= prefetch_interval:
        #     try:
        #         logger.info(f"{LOG_DAEMON} [预获取] 开始预获取 RSS (间隔：{prefetch_interval}秒)")
        #         success, fail, total = prefetch_all_sites_rss(config, logger)
        #         last_prefetch = current_time
        #     except Exception as e:
        #         logger.exception(f"{LOG_DAEMON} [预获取] 预获取循环异常：{e}")
        
        # 检查新种子（站点级独立判断）
        enabled_sites = config.get_enabled_sites()
        qb = QBittorrentClient(
            host=get_qbittorrent_host(qb_config),
            username=qb_config.get("username", ""),
            password=qb_config.get("password", ""),
        )
        history = DownloadHistory()
        for site in enabled_sites:
            site_name = site.get("name", "unknown")
            # 获取站点级刷新间隔
            rss_interval = site.get("schedule", {}).get("interval", 300)
            # 使用站点名称作为计时 key
            check_key = f"last_check_{site_name}"
            last_check = _SITE_CHECK_STATE.get(check_key, 0)
            
            if current_time - last_check >= rss_interval:
                try:
                    logger.info(f"{LOG_DAEMON} [{site_name}] 开始刷新 RSS (间隔={rss_interval}秒)")
                    # 只处理单个站点
                    from src.runner import process_single_site
                    process_single_site(
                        site=site,
                        qb=qb,
                        qb_config=qb_config,
                        history=history,
                        notification_settings=config.notifications,
                    )
                    
                    # 更新站点的上次刷新时间
                    _SITE_CHECK_STATE[check_key] = current_time
                except Exception as e:
                    logger.exception(f"{LOG_DAEMON} [{site_name}] RSS 检查异常：{e}")

        try:
            sync_download_completion_notifications(config)
        except Exception as e:
            logger.exception(f"{LOG_DAEMON} 下载完成通知同步异常：{e}")
        
        # 清理已完成的种子（每 10 秒检查一次，实际是否清理由 cleanup_completed_task 内部控制站点级间隔）
        if auto_delete and current_time - last_cleanup >= 10:
            try:
                cleanup_completed_task(config)
                last_cleanup = current_time
            except Exception as e:
                logger.exception(f"{LOG_DAEMON} 清理异常：{e}")

        try:
            sync_deleted_history_records(config)
        except Exception as e:
            logger.exception(f"{LOG_DAEMON} 删除历史同步异常：{e}")
        
        # 清理过期历史记录（每天零点检查一次）
        if history_max_age > 0:
            # 判断是否为新的一天（零点后）
            current_hour = now.hour
            current_minute = now.minute
            
            # 在 00:00 - 00:05 之间执行清理
            if current_hour == 0 and current_minute < 5:
                if not history_cleanup_done:
                    try:
                        deleted = cleanup_history_task(config)
                        if deleted > 0:
                            logger.info(f"{LOG_DAEMON} 历史记录清理完成，删除 {deleted} 条记录")
                            history_cleanup_done = True
                    except Exception as e:
                        logger.exception(f"{LOG_DAEMON} 历史记录清理异常：{e}")
            else:
                # 过了 00:05，重置清理标记
                history_cleanup_done = False
        
        # 主循环睡眠 10 秒，降低 CPU 占用
        time.sleep(10)


def main():
    parser = argparse.ArgumentParser(description="PT Auto Downloader")
    parser.add_argument(
        "-c", "--config", default="config.yaml", help="Config file config_path"
    )
    parser.add_argument(
        "-d", "--daemon", action="store_true", help="Run as daemon"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output"
    )
    args = parser.parse_args()
    
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path(__file__).parent / config_path

    env_config_path = os.environ.get("AUTO_PT_CONFIG_FILE", "").strip()
    if env_config_path and args.config == "config.yaml":
        config_path = Path(env_config_path)

    config = Config(str(config_path))
    
    if args.verbose:
        config._config.setdefault("logging", {})["level"] = "DEBUG"
    
    setup_logging(config.logging_config)
    logger = get_logger(__name__)
    
    import platform
    version = config._config.get('app', {}).get('version', 'unknown')
    log_startup_message(logger, f"{LOG_MAIN} PT 自动下载器启动 (版本 v{version})")
    log_startup_message(logger, f"{LOG_MAIN} Python 版本：{sys.version}, 平台：{platform.platform()}")
    log_startup_message(logger, f"{LOG_MAIN} 配置文件：{args.config}")
    
    try:
        if args.daemon:
            run_daemon(config)
        else:
            run_once(config)
    except KeyboardInterrupt:
        logger.info(f"{LOG_MAIN} 用户中断")
    except Exception as e:
        logger.exception(f"{LOG_MAIN} 致命错误：{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
