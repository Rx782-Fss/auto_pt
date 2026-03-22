/**
 * PT Auto Downloader - Utility Functions
 * 工具函数模块
 */

/**
 * HTML 转义工具
 * @param {string} text - 需要转义的文本
 * @returns {string} 转义后的 HTML 字符串
 */
export function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * 隐藏敏感信息（RSS 链接中的 sign、uid、passkey 等）
 * @param {string} url - RSS 链接
 * @returns {string} 隐藏敏感信息后的链接
 */
export function hideSensitiveInfo(url) {
    if (!url) return '';
    return url
        .replace(/sign=[^&]+/gi, 'sign=****')
        .replace(/uid=[^&]+/gi, 'uid=****')
        .replace(/passkey=[^&]+/gi, 'passkey=****')
        .replace(/t=[^&]+/gi, 't=****');
}

/**
 * 格式化文件大小
 * @param {number} bytes - 字节数
 * @returns {string} 格式化后的大小
 */
export function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

/**
 * 格式化日期时间
 * @param {string} isoString - ISO 格式日期字符串
 * @returns {string} 格式化后的日期时间
 */
export function formatDateTime(isoString) {
    if (!isoString) return '-';
    try {
        const date = new Date(isoString);
        return date.toLocaleString('zh-CN');
    } catch (e) {
        return isoString;
    }
}

/**
 * 格式化相对时间（如：2 小时前）
 * @param {string} isoString - ISO 格式日期字符串
 * @returns {string} 相对时间描述
 */
export function formatRelativeTime(isoString) {
    if (!isoString) return '';
    try {
        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffSecs = Math.floor(diffMs / 1000);
        const diffMins = Math.floor(diffSecs / 60);
        const diffHours = Math.floor(diffMins / 60);
        const diffDays = Math.floor(diffHours / 24);
        
        if (diffDays > 0) return `${diffDays}天前`;
        if (diffHours > 0) return `${diffHours}小时前`;
        if (diffMins > 0) return `${diffMins}分钟前`;
        return '刚刚';
    } catch (e) {
        return '';
    }
}

/**
 * 防抖函数
 * @param {Function} func - 需要防抖的函数
 * @param {number} wait - 等待时间（毫秒）
 * @returns {Function} 防抖后的函数
 */
export function debounce(func, wait = 300) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * 截取字符串（超过长度显示...）
 * @param {string} str - 原字符串
 * @param {number} maxLength - 最大长度
 * @returns {string} 截取后的字符串
 */
export function truncate(str, maxLength = 50) {
    if (!str || str.length <= maxLength) return str;
    return str.substring(0, maxLength) + '...';
}

/**
 * 获取 URL 参数
 * @param {string} url - URL 字符串
 * @param {string} param - 参数名
 * @returns {string|null} 参数值
 */
export function getUrlParam(url, param) {
    try {
        const urlObj = new URL(url);
        return urlObj.searchParams.get(param);
    } catch (e) {
        return null;
    }
}
