"""
统一日志配置模块

提供跨平台、可配置的日志系统，支持:
- 日志轮转 (RotatingFileHandler)
- 彩色控制台输出
- 敏感信息脱敏
- 多日志文件 (主日志 + 错误日志)
"""

import logging
import os
import re
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Dict, Any, Optional

from .colored_formatter import ColoredFormatter, SensitiveFormatter
from .log_constants import LOG_PERF


# ANSI 颜色码正则表达式，用于从日志文件中去除
ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


class StripAnsiFilter(logging.Filter):
    """
    去除日志消息中的 ANSI 颜色码
    
    用于文件处理器，确保日志文件不包含颜色转义序列
    """
    def filter(self, record: logging.LogRecord) -> bool:
        # 处理消息本身
        if isinstance(record.msg, str):
            record.msg = ANSI_RE.sub('', record.msg)
        # 处理参数中的字符串
        if hasattr(record, 'args') and record.args:
            if isinstance(record.args, dict):
                record.args = {k: ANSI_RE.sub('', v) if isinstance(v, str) else v 
                              for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(ANSI_RE.sub('', arg) if isinstance(arg, str) else arg 
                                   for arg in record.args)
        return True


class UnbufferedRotatingFileHandler(RotatingFileHandler):
    """
    无缓冲滚动文件处理器 - 每次写入后立即刷新到磁盘
    同时支持主日志按大小轮转。
    """
    def emit(self, record):
        super().emit(record)
        if hasattr(self, 'stream') and self.stream:
            self.stream.flush()


# 默认配置
DEFAULT_CONFIG = {
    'dir': 'logs',
    'file': 'auto_pt.log',
    'level': 'INFO',
    'max_bytes': 10 * 1024 * 1024,  # 10MB
    'backup_count': 5,
    'format': '%(asctime)s - %(levelname)s - %(message)s',
    'date_format': '%Y-%m-%d %H:%M:%S',
    'use_color': True,
    'mask_sensitive': True,
    'error_file': None,  # 单独的错误日志文件
    'suppress_request_logs': True,
    'request_log_level': 'WARNING',
}

ENV_LOG_DIR = "AUTO_PT_LOG_DIR"
ENV_LOG_FILE = "AUTO_PT_LOG_FILE"
BASE_DIR = Path(__file__).parent.parent.resolve()


def _close_all_handlers(root_logger: logging.Logger):
    """关闭并移除已有 handlers，避免重载时遗留文件句柄。"""
    for handler in root_logger.handlers[:]:
        try:
            handler.close()
        finally:
            root_logger.removeHandler(handler)


def _configure_external_loggers(log_config: Dict[str, Any], default_level: int):
    """
    配置第三方日志器，避免访问日志淹没业务日志。
    默认保留 Werkzeug 的 WARNING/ERROR，压掉常规 200 访问日志。
    """
    suppress_request_logs = bool(log_config.get('suppress_request_logs', True))
    request_level_name = str(log_config.get('request_log_level', 'WARNING')).upper()
    request_level = getattr(logging, request_level_name, logging.WARNING)

    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(request_level if suppress_request_logs else default_level)

    flask_cors_logger = logging.getLogger('flask_cors')
    flask_cors_logger.setLevel(request_level if suppress_request_logs else default_level)


def _build_effective_log_config(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """合并默认值、配置文件和环境变量，得到最终日志配置。"""
    log_config = {**DEFAULT_CONFIG, **(config or {})}

    env_log_dir = os.getenv(ENV_LOG_DIR, "").strip()
    env_log_file = os.getenv(ENV_LOG_FILE, "").strip()
    if env_log_dir:
        log_config["dir"] = env_log_dir
    if env_log_file:
        log_config["file"] = env_log_file

    return log_config


def resolve_log_targets(
    config: Optional[Dict[str, Any]] = None,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """解析日志目录、主日志文件和错误日志文件路径。"""
    log_config = _build_effective_log_config(config)
    project_root = (base_dir or BASE_DIR).resolve()

    log_dir = Path(str(log_config.get("dir", "logs") or "logs")).expanduser()
    if not log_dir.is_absolute():
        log_dir = project_root / log_dir

    log_file = str(log_config.get("file", "auto_pt.log") or "auto_pt.log")
    log_path = Path(log_file).expanduser()
    if not log_path.is_absolute():
        if log_path.parent != Path("."):
            log_path = log_dir / log_path.name
        else:
            log_path = log_dir / log_file

    error_path = None
    error_file = log_config.get("error_file")
    if error_file:
        error_path = Path(str(error_file)).expanduser()
        if not error_path.is_absolute():
            error_path = log_dir / error_path

    return {
        "log_config": log_config,
        "log_dir": log_dir,
        "log_path": log_path,
        "error_path": error_path,
    }


def setup_logging(
    config: Optional[Dict[str, Any]] = None,
    app_name: str = "auto_pt",
    force_reinit: bool = False,
) -> logging.Logger:
    """
    统一的日志初始化函数
    
    Args:
        config: 日志配置字典 (可选，从 YAML 配置读取)
        app_name: 应用名称 (用于日志记录器命名)
        force_reinit: 是否强制重新初始化
    
    Returns:
        配置好的 root logger
    
    使用示例:
        # 从配置字典初始化
        config = {"logging": {"dir": "logs", "level": "DEBUG"}}
        setup_logging(config.get("logging", {}))
        
        # 快速初始化 (使用默认配置)
        setup_logging()
    """
    resolved_targets = resolve_log_targets(config, base_dir=BASE_DIR)
    log_config = resolved_targets["log_config"]
    log_dir = resolved_targets["log_dir"]
    log_path = resolved_targets["log_path"]
    error_path = resolved_targets["error_path"]

    level_name = log_config.get('level', 'INFO').upper()
    level = getattr(logging, level_name, logging.INFO)
    max_bytes = log_config.get('max_bytes', 10 * 1024 * 1024)
    backup_count = log_config.get('backup_count', 5)
    fmt = log_config.get('format', '%(asctime)s - %(levelname)s - %(message)s')
    datefmt = log_config.get('date_format', '%Y-%m-%d %H:%M:%S')
    use_color = log_config.get('use_color', True)
    mask_sensitive = log_config.get('mask_sensitive', True)
    error_file = log_config.get('error_file')
    
    # 确保日志目录存在
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # 获取 root logger
    root_logger = logging.getLogger()
    
    # 检查是否已初始化
    if root_logger.handlers and not force_reinit:
        # 检查配置是否相同
        existing_config = getattr(root_logger, '_log_config_hash', None)
        current_config_hash = hash(str(sorted(log_config.items())))
        if existing_config == current_config_hash:
            return root_logger
    
    # 清除已有 handlers
    _close_all_handlers(root_logger)
    
    # 设置日志级别
    root_logger.setLevel(level)
    
    # 创建控制台处理器 (带颜色)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    if use_color and mask_sensitive:
        console_formatter = SensitiveFormatter(fmt, datefmt, use_color=True)
    elif use_color:
        console_formatter = ColoredFormatter(fmt, datefmt, use_color=True)
    else:
        console_formatter = logging.Formatter(fmt, datefmt)
    
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # 创建文件处理器（无颜色、可轮转、实时刷新）
    file_handler = UnbufferedRotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8',
        delay=True,
    )
    file_handler.setLevel(level)
    if mask_sensitive:
        file_formatter = SensitiveFormatter(fmt, datefmt, use_color=False)
    else:
        file_formatter = logging.Formatter(fmt, datefmt)
    file_handler.setFormatter(file_formatter)
    # 添加 ANSI 去除过滤器，确保日志文件不含颜色码
    file_handler.addFilter(StripAnsiFilter())
    root_logger.addHandler(file_handler)
    
    # 创建错误日志处理器 (可选)
    if error_file and error_path is not None:
        error_path.parent.mkdir(parents=True, exist_ok=True)
        error_handler = RotatingFileHandler(
            error_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8',
            delay=True,
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(file_formatter)
        error_handler.addFilter(StripAnsiFilter())
        root_logger.addHandler(error_handler)
    
    # 保存配置哈希
    root_logger._log_config_hash = hash(str(sorted(log_config.items())))
    _configure_external_loggers(log_config, level)
    
    # 创建应用专用的 logger
    app_logger = logging.getLogger(app_name)
    
    return app_logger


def get_logger(name: str) -> logging.Logger:
    """
    获取命名子日志器
    
    Args:
        name: 日志器名称 (通常是模块名 __name__)
    
    Returns:
        配置好的 logger 实例
    
    使用示例:
        logger = get_logger(__name__)
        logger.info("消息")
    """
    return logging.getLogger(name)


def log_startup_message(logger: logging.Logger, message: str):
    """
    输出启动类日志。

    按当前有效日志级别输出，但尽量保持在信息类级别；
    当级别被抬高时，自动升级到当前可见的最低级别，确保启动信息可见。
    """
    effective_level = logger.getEffectiveLevel()
    if effective_level <= logging.INFO:
        logger.info(message)
    elif effective_level <= logging.WARNING:
        logger.warning(message)
    elif effective_level <= logging.ERROR:
        logger.error(message)
    else:
        logger.critical(message)


def close_logging():
    """
    关闭日志系统，释放文件句柄
    
    在程序退出前调用
    """
    root_logger = logging.getLogger()
    
    # 记录关闭日志
    root_logger.info("日志系统关闭")
    
    # 关闭并移除所有 handlers
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)


def reload_logging(config: Dict[str, Any]):
    """
    重新加载日志配置 (用于配置热重载)
    
    Args:
        config: 新的日志配置字典
    """
    setup_logging(config, force_reinit=True)


# ==================== 性能日志工具 ====================

class PerformanceTimer:
    """
    性能计时器 - 用于记录操作耗时
    
    使用示例:
        timer = PerformanceTimer()
        timer.start("rss_fetch")
        # ... 执行操作 ...
        timer.end("rss_fetch")
        timer.report()
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self._timers: Dict[str, float] = {}
        self._records: Dict[str, list] = {}
        self.logger = logger or get_logger(__name__)
    
    def start(self, name: str):
        """开始计时"""
        import time
        self._timers[name] = time.time()
    
    def end(self, name: str, log: bool = True) -> float:
        """
        结束计时
        
        Args:
            name: 计时器名称
            log: 是否自动记录日志
        
        Returns:
            耗时 (秒)
        """
        import time
        if name not in self._timers:
            return 0.0
        
        elapsed = time.time() - self._timers[name]
        del self._timers[name]
        
        # 记录历史
        if name not in self._records:
            self._records[name] = []
        self._records[name].append(elapsed)
        
        if log:
            self.logger.debug(f"{LOG_PERF} {name}: {elapsed:.3f}s")
        
        return elapsed
    
    def report(self, level: str = "info"):
        """
        输出性能统计报告
        
        Args:
            level: 日志级别 (debug/info/warning)
        """
        log_func = getattr(self.logger, level, self.logger.info)
        
        for name, times in self._records.items():
            if not times:
                continue
            
            avg_time = sum(times) / len(times)
            max_time = max(times)
            min_time = min(times)
            
            log_func(
                f"{LOG_PERF} 统计 {name}: "
                f"平均 {avg_time:.3f}s, "
                f"最小 {min_time:.3f}s, "
                f"最大 {max_time:.3f}s, "
                f"调用 {len(times)} 次"
            )
    
    def elapsed(self, name: str) -> float:
        """获取当前耗时 (不结束计时)"""
        import time
        if name not in self._timers:
            return 0.0
        return time.time() - self._timers[name]
