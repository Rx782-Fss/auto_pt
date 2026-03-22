"""
彩色日志格式化器

支持:
- 日志级别颜色
- 模块前缀颜色
- Windows 兼容性
- 自动检测终端支持
"""

import logging
import sys
from typing import Dict, Optional

try:
    import colorlog
    HAS_COLORLOG = True
except ImportError:
    HAS_COLORLOG = False

from .log_constants import LEVEL_COLORS, MODULE_COLORS


class ColoredFormatter(logging.Formatter):
    """
    支持彩色输出的日志格式化器
    
    功能:
    - 日志级别颜色
    - 模块前缀颜色高亮
    - Windows 兼容性
    - 非终端自动禁用颜色
    """
    
    # ANSI 颜色代码 (fallback 使用)
    class _Colors:
        RESET = '\033[0m'
        BOLD = '\033[1m'
        GRAY = '\033[90m'
        RED = '\033[31m'
        GREEN = '\033[32m'
        YELLOW = '\033[33m'
        BLUE = '\033[34m'
        MAGENTA = '\033[35m'
        CYAN = '\033[36m'
        WHITE = '\033[37m'
        BOLD_RED = '\033[1;31m'
        BOLD_GREEN = '\033[1;32m'
        BOLD_YELLOW = '\033[1;33m'
        BOLD_BLUE = '\033[1;34m'
        BG_WHITE_RED = '\033[1;41;37m'
    
    # colorlog 颜色名称到 ANSI 代码的映射
    _COLOR_MAP = {
        'gray': '\033[90m',
        'red': '\033[31m',
        'bold_red': '\033[1;31m',
        'green': '\033[32m',
        'bold_green': '\033[1;32m',
        'yellow': '\033[33m',
        'bold_yellow': '\033[1;33m',
        'blue': '\033[34m',
        'bold_blue': '\033[1;34m',
        'purple': '\033[35m',
        'magenta': '\033[35m',
        'cyan': '\033[36m',
        'white': '\033[37m',
    }
    
    def __init__(
        self,
        fmt: Optional[str] = None,
        datefmt: Optional[str] = None,
        use_color: Optional[bool] = None,
        log_colors: Optional[Dict[str, str]] = None,
        module_colors: Optional[Dict[str, str]] = None,
    ):
        """
        初始化彩色格式化器
        
        Args:
            fmt: 日志格式字符串
            datefmt: 时间格式字符串
            use_color: 是否使用颜色 (None=自动检测)
            log_colors: 日志级别颜色映射
            module_colors: 模块前缀颜色映射
        """
        super().__init__(fmt, datefmt)
        
        self.log_colors = log_colors or LEVEL_COLORS
        self.module_colors = module_colors or MODULE_COLORS
        
        # 自动检测是否使用颜色
        if use_color is None:
            self.use_color = self._should_use_color()
        else:
            self.use_color = use_color
        
        # 如果使用 colorlog，创建内部格式化器
        if HAS_COLORLOG and self.use_color:
            self._color_formatter = colorlog.ColoredFormatter(
                fmt=fmt,
                datefmt=datefmt,
                log_colors=self.log_colors,
            )
        else:
            self._color_formatter = None
    
    def _should_use_color(self) -> bool:
        """检测是否应该使用颜色输出"""
        # 检查是否有 stdout
        if not hasattr(sys.stdout, 'isatty'):
            return False
        
        # 检查是否是终端
        if not sys.stdout.isatty():
            return False
        
        # Windows 特殊处理
        if sys.platform == 'win32':
            # 尝试启用 ANSI 支持
            try:
                import os
                os.system('')  # 启用虚拟终端处理
                return True
            except Exception:
                pass
            
            # 尝试使用 colorama
            try:
                import colorama
                colorama.init()
                return True
            except ImportError:
                return False
        
        return True
    
    def _apply_module_color(self, message: str) -> str:
        """为模块前缀应用颜色"""
        if not self.use_color:
            return message
        
        for module, color in self.module_colors.items():
            if module in message:
                if HAS_COLORLOG:
                    # 使用 colorlog 的颜色代码
                    color_code = self._COLOR_MAP.get(color, self._Colors.RESET)
                else:
                    color_code = self._COLOR_MAP.get(color, self._Colors.RESET)
                
                colored_module = f"{color_code}{module}{self._Colors.RESET}"
                message = message.replace(module, colored_module, 1)
        
        return message
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录"""
        # 使用 colorlog 格式化器（如果可用）
        if self._color_formatter:
            message = self._color_formatter.format(record)
        else:
            # 使用基础格式化
            message = super().format(record)
            
            # 手动应用级别颜色（如果没有 colorlog）
            if self.use_color:
                level_color = self._COLOR_MAP.get(
                    self.log_colors.get(record.levelname, 'white'),
                    self._Colors.WHITE
                )
                level_name = f"{level_color}{record.levelname}{self._Colors.RESET}"
                message = message.replace(
                    f" {record.levelname} ",
                    f" {level_name} "
                )
        
        # 应用模块前缀颜色
        if self.use_color:
            message = self._apply_module_color(message)
        
        return message


class SensitiveFormatter(ColoredFormatter):
    """
    带敏感信息脱敏的格式化器
    
    自动脱敏:
    - passkey=xxx
    - password: xxx
    - uid=xxx
    - API key/token
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def _mask_sensitive_info(self, text: str) -> str:
        """脱敏敏感信息"""
        import re
        
        if not text:
            return text
        
        # 脱敏 passkey
        text = re.sub(
            r'passkey=([a-zA-Z0-9]{16,})',
            'passkey=***',
            text,
            flags=re.IGNORECASE
        )
        
        # 脱敏密码 (多种格式)
        text = re.sub(
            r'password["\']?\s*[=:]\s*["\']?([^,"\s\']+)',
            'password: ***',
            text,
            flags=re.IGNORECASE
        )
        
        # 脱敏 uid
        text = re.sub(
            r'uid=([a-zA-Z0-9]{4,})',
            'uid=***',
            text,
            flags=re.IGNORECASE
        )
        
        # 脱敏 sign/token
        text = re.sub(
            r'(sign|token|api_key|secret)["\']?\s*[=:]\s*["\']?([a-zA-Z0-9]{8,})',
            r'\1: ***',
            text,
            flags=re.IGNORECASE
        )
        
        return text
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化并脱敏"""
        message = super().format(record)
        return self._mask_sensitive_info(message)
