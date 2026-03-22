/**
 * PT Auto Downloader - Logs Module
 * 日志显示模块
 * 
 * 功能:
 * - 日志加载和显示
 * - 日志过滤 (级别/模块/关键词)
 * - 自动刷新
 */

import { getLogs, clearLogs } from './api.js?v=174';

// 日志过滤状态
let logFilters = {
    level: 'all',
    module: 'all',
    keyword: ''
};

// 自动刷新状态
let logAutoRefresh = {
    enabled: false,
    interval: 3000,
    timer: null
};

const MAX_RENDERED_LOG_LINES = 1000;

const LOG_LEVEL_OPTIONS = Object.freeze([
    { value: 'all', label: '全部级别' },
    { value: 'DEBUG', label: '调试 DEBUG' },
    { value: 'INFO', label: '信息 INFO' },
    { value: 'WARNING', label: '警告 WARNING' },
    { value: 'ERROR', label: '错误 ERROR' }
]);

const LOG_MODULE_OPTIONS = Object.freeze([
    { value: 'all', label: '全部模块' },
    { value: '系统运行', label: '常用 · 系统运行' },
    { value: '站点任务', label: '常用 · 站点任务' },
    { value: 'Web 安全', label: '常用 · Web 安全' },
    { value: 'Web 服务', label: '常用 · Web 服务' },
    { value: 'qBittorrent', label: '常用 · 下载器 QB' },
    { value: 'PTSeed', label: '常用 · PTSeed' },
    { value: '主程序', label: '详细 · 主程序' },
    { value: '守护进程', label: '详细 · 守护进程' },
    { value: '性能', label: '详细 · 性能' },
    { value: '站点-检查', label: '详细 · 站点检查' },
    { value: '站点-下载', label: '详细 · 站点下载' },
    { value: '站点-清理', label: '详细 · 站点清理' },
    { value: 'PTSeed-获取', label: '详细 · PTSeed 获取' },
    { value: 'PTSeed-下载', label: '详细 · PTSeed 下载' },
    { value: 'PTSeed-解析', label: '详细 · PTSeed 解析' },
    { value: 'QB-连接', label: '详细 · QB 连接' },
    { value: 'QB-登录', label: '详细 · QB 登录' },
    { value: 'QB-添加', label: '详细 · QB 添加' },
    { value: 'QB-获取', label: '详细 · QB 获取' },
    { value: 'QB-删除', label: '详细 · QB 删除' },
    { value: '筛选器', label: '详细 · 筛选器' },
    { value: '历史记录', label: '详细 · 历史记录' },
    { value: 'Web-服务', label: '详细 · Web 服务' },
    { value: 'Web-访问', label: '详细 · Web 访问' },
    { value: 'Web-认证', label: '详细 · Web 认证' },
    { value: 'Web-API', label: '详细 · Web API' },
    { value: 'Web-配置', label: '详细 · Web 配置' },
    { value: 'Web-下载', label: '详细 · Web 下载' },
    { value: 'Web-历史', label: '详细 · Web 历史' },
    { value: 'Web-日志', label: '详细 · Web 日志' }
]);

const LOG_MODULE_KEYWORDS = Object.freeze({
    '系统运行': ['[主程序]', '[守护进程]', '[性能]'],
    '站点任务': ['[站点-检查]', '[站点-下载]', '[站点-清理]'],
    'Web 安全': ['[Web-访问]', '[Web-认证]'],
    'Web 服务': ['[Web-服务]', '[Web-API]', '[Web-配置]', '[Web-下载]', '[Web-历史]', '[Web-日志]'],
    'qBittorrent': ['[QB-连接]', '[QB-登录]', '[QB-添加]', '[QB-获取]', '[QB-删除]'],
    'PTSeed': ['[PTSeed-获取]', '[PTSeed-下载]', '[PTSeed-解析]'],
    '主程序': ['[主程序]'],
    '守护进程': ['[守护进程]'],
    '性能': ['[性能]'],
    '站点-检查': ['[站点-检查]'],
    '站点-下载': ['[站点-下载]'],
    '站点-清理': ['[站点-清理]'],
    'PTSeed-获取': ['[PTSeed-获取]'],
    'PTSeed-下载': ['[PTSeed-下载]'],
    'PTSeed-解析': ['[PTSeed-解析]'],
    'QB-连接': ['[QB-连接]'],
    'QB-登录': ['[QB-登录]'],
    'QB-添加': ['[QB-添加]'],
    'QB-获取': ['[QB-获取]'],
    'QB-删除': ['[QB-删除]'],
    '筛选器': ['[筛选器]'],
    '历史记录': ['[历史记录]'],
    'Web-服务': ['[Web-服务]', 'Flask'],
    'Web-访问': ['[Web-访问]'],
    'Web-认证': ['[Web-认证]'],
    'Web-API': ['[Web-API]'],
    'Web-配置': ['[Web-配置]'],
    'Web-下载': ['[Web-下载]'],
    'Web-历史': ['[Web-历史]'],
    'Web-日志': ['[Web-日志]']
});

function splitLogLines(logs) {
    if (!logs) {
        return [];
    }

    return logs.split('\n').filter(line => line.trim());
}

function renderFilterOptions(selectEl, options, selectedValue, getCountLabel) {
    if (!selectEl) {
        return;
    }

    selectEl.innerHTML = options.map(option => {
        const countLabel = typeof getCountLabel === 'function' ? getCountLabel(option.value) : '';
        const selectedAttr = option.value === selectedValue ? ' selected' : '';
        return `<option value="${option.value}"${selectedAttr}>${option.label}${countLabel}</option>`;
    }).join('');
}

function countMatchingLines(lines, levelFilter = 'all', moduleFilter = 'all') {
    return lines.filter(line => matchesLogLine(line, levelFilter, moduleFilter)).length;
}

function syncLogFilterControls(rawLogs = '') {
    const lines = splitLogLines(rawLogs);
    const levelSelect = document.getElementById('logLevelFilter');
    const moduleSelect = document.getElementById('logModuleFilter');
    const selectedLevel = levelSelect?.value || logFilters.level || 'all';
    const selectedModule = moduleSelect?.value || logFilters.module || 'all';

    renderFilterOptions(levelSelect, LOG_LEVEL_OPTIONS, selectedLevel, value => {
        if (value === 'all') {
            return '';
        }
        const count = countMatchingLines(lines, value, 'all');
        return count > 0 ? ` (${count})` : '';
    });

    renderFilterOptions(moduleSelect, LOG_MODULE_OPTIONS, selectedModule, value => {
        if (value === 'all') {
            return '';
        }
        const count = countMatchingLines(lines, 'all', value);
        return count > 0 ? ` (${count})` : '';
    });
}

export function matchesLogLine(line, levelFilter = 'all', moduleFilter = 'all', keyword = '') {
    if (!line || !line.trim()) {
        return false;
    }

    if (levelFilter !== 'all' && !line.includes(` - ${levelFilter} - `)) {
        return false;
    }

    if (moduleFilter !== 'all') {
        const moduleKeywords = LOG_MODULE_KEYWORDS[moduleFilter];
        if (!moduleKeywords || !moduleKeywords.some(keywordItem => line.includes(keywordItem))) {
            return false;
        }
    }

    if (keyword) {
        const keywordLower = keyword.toLowerCase();
        if (!line.toLowerCase().includes(keywordLower)) {
            return false;
        }
    }

    return true;
}

function getFilteredLogLines(logs, levelFilter = 'all', moduleFilter = 'all', keyword = '') {
    return splitLogLines(logs).filter(line => matchesLogLine(line, levelFilter, moduleFilter, keyword));
}

function updateLogEntryCount(rawLogs, filteredCount) {
    const countEl = document.getElementById('logEntryCount');
    if (!countEl) {
        return;
    }

    if (!rawLogs || !rawLogs.trim()) {
        countEl.textContent = '';
        return;
    }

    const totalLoaded = splitLogLines(rawLogs).length;
    const loadedLabel = totalLoaded >= MAX_RENDERED_LOG_LINES ? `最近 ${totalLoaded} 条` : `已加载 ${totalLoaded} 条`;
    countEl.textContent = filteredCount === totalLoaded ? loadedLabel : `${loadedLabel} · 命中 ${filteredCount} 条`;
}

/**
 * 加载日志
 * @returns {Promise<string>} 日志内容
 */
export async function loadLogs() {
    try {
        const data = await getLogs();
        return data.logs || '';
    } catch (e) {
        console.error('Load logs error:', e);
        return '加载日志失败：' + e.message;
    }
}

/**
 * 清除日志
 * @returns {Promise<Object>} 响应数据
 */
export async function clearAllLogs() {
    try {
        return await clearLogs();
    } catch (e) {
        console.error('Clear logs error:', e);
        throw e;
    }
}

/**
 * 设置日志过滤条件
 * @param {string} level - 日志级别
 * @param {string} module - 模块名称
 * @param {string} keyword - 关键词
 */
export function setLogFilters(level = 'all', module = 'all', keyword = '') {
    logFilters.level = level;
    logFilters.module = module;
    logFilters.keyword = keyword;
}

/**
 * 获取当前过滤条件
 * @returns {Object} 过滤条件
 */
export function getLogFilters() {
    return { ...logFilters };
}

/**
 * 过滤日志内容
 * @param {string} logs - 日志内容
 * @param {string} levelFilter - 级别过滤
 * @param {string} moduleFilter - 模块过滤
 * @param {string} keyword - 关键词过滤
 * @returns {string} 过滤后的日志
 */
export function filterLogs(logs, levelFilter = 'all', moduleFilter = 'all', keyword = '') {
    return getFilteredLogLines(logs, levelFilter, moduleFilter, keyword).join('\n');
}

/**
 * 解析日志行，获取样式类名
 * @param {string} line - 日志行
 * @returns {string} CSS 类名
 */
export function getLogLineClass(line) {
    let className = 'log-line';
    
    if (line.includes(' - ERROR - ') || line.includes('[ERROR]')) {
        className += ' error';
    } else if (line.includes(' - WARNING - ') || line.includes('[WARNING]')) {
        className += ' warning';
    } else if (line.includes(' - INFO - ') || line.includes('[INFO]')) {
        className += ' info';
    }
    
    // 特殊日志类型
    if (line.includes('[下载]') || line.includes('下载：')) {
        className += ' download';
    } else if (line.includes('[删除]') || line.includes('删除：')) {
        className += ' delete';
    } else if (line.includes('[配置修改]')) {
        className += ' config';
    } else if (line.includes('成功')) {
        className += ' success';
    }
    
    return className;
}

/**
 * 渲染日志到容器（优化版：限制显示数量）
 * @param {string} containerId - 容器 ID
 * @param {string} logs - 日志内容
 */
export function renderLogs(containerId, logs) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    if (!logs || logs.trim() === '') {
        container.innerHTML = '<div class="empty-text">暂无日志</div>';
        return;
    }
    
    // 限制显示最后 1000 行，避免 DOM 过大
    const lines = logs.split('\n');
    const displayLines = lines.slice(-MAX_RENDERED_LOG_LINES);
    
    // 使用 DocumentFragment 优化 DOM 操作
    const fragment = document.createDocumentFragment();
    const tempDiv = document.createElement('div');
    
    displayLines.forEach((line) => {
        if (!line.trim()) return;
        
        const div = document.createElement('div');
        div.className = getLogLineClass(line);
        div.textContent = line;
        tempDiv.appendChild(div);
    });
    
    container.innerHTML = tempDiv.innerHTML;
    
    // 滚动到底部
    container.scrollTop = container.scrollHeight;
}

/**
 * 应用过滤并重新渲染日志
 * @param {string} containerId - 容器 ID
 * @param {string} rawLogs - 原始日志内容
 */
export function applyLogFilters(containerId, rawLogs) {
    syncLogFilterControls(rawLogs);
    const filteredLines = getFilteredLogLines(rawLogs, logFilters.level, logFilters.module, logFilters.keyword);
    renderLogs(containerId, filteredLines.join('\n'));
    updateLogEntryCount(rawLogs, filteredLines.length);
}

/**
 * 开启日志自动刷新
 * @param {number} interval - 刷新间隔 (毫秒)
 */
export function startLogAutoRefresh(interval = 3000) {
    if (logAutoRefresh.enabled) return;
    
    logAutoRefresh.enabled = true;
    logAutoRefresh.interval = interval;
    
    // 立即刷新一次
    refreshLogsFromCache();
    
    // 定时刷新
    logAutoRefresh.timer = setInterval(refreshLogsFromCache, interval);
    
    console.log('[日志] 自动刷新已启动，间隔:', interval, 'ms');
}

/**
 * 停止日志自动刷新
 */
export function stopLogAutoRefresh() {
    if (logAutoRefresh.timer) {
        clearInterval(logAutoRefresh.timer);
        logAutoRefresh.timer = null;
    }
    logAutoRefresh.enabled = false;
    console.log('[日志] 自动刷新已停止');
}

/**
 * 获取自动刷新状态
 * @returns {boolean} 是否启用
 */
export function isLogAutoRefreshEnabled() {
    return logAutoRefresh.enabled;
}

/**
 * 从缓存刷新日志 (内部使用)
 */
async function refreshLogsFromCache() {
    try {
        const data = await getLogs();
        const logs = data.logs || '';
        
        // 只在日志内容变化时更新
        const oldCache = window._logCache || '';
        if (logs !== oldCache) {
            window._logCache = logs;
            
            // 使用当前的过滤条件重新渲染
            const container = document.getElementById('logContainer');
            if (container) {
                applyLogFilters('logContainer', logs);
            }
        }
    } catch (e) {
        console.error('[日志] 自动刷新失败:', e);
    }
}
