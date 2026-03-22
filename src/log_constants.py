"""
日志常量定义 - 统一日志前缀命名

使用方法:
    from src.log_constants import LOG_MAIN, LOG_QB_ADD
    logger.info(f"{LOG_MAIN} 程序启动")
"""

# ==================== CORE (核心) ====================
LOG_MAIN = "[主程序]"
LOG_DAEMON = "[守护进程]"
LOG_PERF = "[性能]"

# ==================== SITE TASKS (站点任务) ====================
LOG_SITE_CHECK = "[站点-检查]"
LOG_SITE_DOWNLOAD = "[站点-下载]"
LOG_SITE_CLEANUP = "[站点-清理]"

# ==================== PTSEED / SITE CLIENTS (站点客户端) ====================
LOG_MTEAM_FETCH = "[PTSeed-获取]"
LOG_MTEAM_DOWNLOAD = "[PTSeed-下载]"
LOG_MTEAM_PARSE = "[PTSeed-解析]"

# ==================== QB (下载器) ====================
LOG_QB_CONNECT = "[QB-连接]"
LOG_QB_LOGIN = "[QB-登录]"
LOG_QB_ADD = "[QB-添加]"
LOG_QB_GET = "[QB-获取]"
LOG_QB_DEL = "[QB-删除]"

# ==================== FILTER (筛选器) ====================
LOG_FILTER = "[筛选器]"

# ==================== HISTORY (历史记录) ====================
LOG_HISTORY = "[历史记录]"

# ==================== WEB (Web 界面) ====================
LOG_WEB_SERVICE = "[Web-服务]"
LOG_WEB_ACCESS = "[Web-访问]"
LOG_WEB_AUTH = "[Web-认证]"
LOG_WEB_API = "[Web-API]"
LOG_WEB_CONFIG = "[Web-配置]"
LOG_WEB_DOWNLOAD = "[Web-下载]"
LOG_WEB_HISTORY = "[Web-历史]"
LOG_WEB_LOGS = "[Web-日志]"

# ==================== 颜色配置 (用于彩色日志) ====================
# 日志级别颜色
LEVEL_COLORS = {
    'DEBUG': 'gray',
    'INFO': 'green',
    'WARNING': 'yellow',
    'ERROR': 'red',
    'CRITICAL': 'bold_red',
}

# 模块前缀颜色
MODULE_COLORS = {
    LOG_MAIN: 'bold_blue',
    LOG_DAEMON: 'cyan',
    LOG_PERF: 'purple',
    LOG_SITE_CHECK: 'cyan',
    LOG_SITE_DOWNLOAD: 'bold_green',
    LOG_SITE_CLEANUP: 'yellow',
    LOG_MTEAM_FETCH: 'cyan',
    LOG_MTEAM_DOWNLOAD: 'cyan',
    LOG_MTEAM_PARSE: 'cyan',
    LOG_QB_CONNECT: 'bold_green',
    LOG_QB_LOGIN: 'green',
    LOG_QB_ADD: 'green',
    LOG_QB_GET: 'green',
    LOG_QB_DEL: 'green',
    LOG_FILTER: 'yellow',
    LOG_HISTORY: 'purple',
    LOG_WEB_SERVICE: 'bold_yellow',
    LOG_WEB_ACCESS: 'yellow',
    LOG_WEB_AUTH: 'yellow',
    LOG_WEB_API: 'yellow',
    LOG_WEB_CONFIG: 'yellow',
    LOG_WEB_DOWNLOAD: 'yellow',
    LOG_WEB_HISTORY: 'yellow',
    LOG_WEB_LOGS: 'yellow',
}
