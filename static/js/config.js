/**
 * PT Auto Downloader - Config Manager
 * 配置管理模块
 */

import { getConfig, saveConfig } from './api.js?v=174';

// 配置缓存
let configCache = null;

/**
 * 加载配置
 * @returns {Promise<Object>} 配置对象
 */
export async function loadConfig() {
    try {
        console.log('[loadConfig] 开始加载配置...');
        const response = await getConfig();
        console.log('[loadConfig] API 响应:', response);
        
        // API 返回格式：{config: {...}, success: true}
        const config = response?.config || response;
        console.log('[loadConfig] 提取后的配置:', config);
        
        configCache = config;
        return config;
    } catch (e) {
        console.error('[loadConfig] 加载失败:', e.message);
        throw e;
    }
}

/**
 * 从配置对象中提取 qbittorrent 配置
 * @param {Object} config - 完整配置
 * @returns {Object} qbittorrent 配置
 */
export function getQBConfig(config) {
    return config?.qbittorrent || {};
}

/**
 * 获取缓存的配置
 * @returns {Object|null} 配置对象
 */
export function getCachedConfig() {
    return configCache;
}

/**
 * 保存配置
 * @param {Object} configData - 配置数据
 * @returns {Promise<Object>} 响应数据
 */
export async function saveConfigData(configData) {
    try {
        const result = await saveConfig(configData);
        // 更新缓存
        configCache = configData;
        return result;
    } catch (e) {
        console.error('Save config error:', e);
        throw e;
    }
}

/**
 * 构建配置对象
 * @param {Object} formData - 表单数据
 * @returns {Object} 完整配置对象
 */
export function buildConfig(formData) {
    const config = {
        qbittorrent: {
            host: formData.qbHost,
            username: formData.qbUsername,
            password: formData.qbPassword,
            save_path: formData.savePath,
        }
    };

    if (formData.interval !== undefined) {
        config.schedule = {
            interval: formData.interval || 300,
            enabled: true
        };
    }

    if (formData.keywords || formData.exclude || formData.minSize || formData.maxSize) {
        config.filter = {
            categories: [],
            keywords: formData.keywords || [],
            exclude: formData.exclude || [],
            min_size: formData.minSize || 0,
            max_size: formData.maxSize || 0
        };
    }

    if (formData.tags || formData.pauseAdded !== undefined) {
        config.qbittorrent.tags = formData.tags;
        config.qbittorrent.pause_added = formData.pauseAdded;
    }

    return config;
}

/**
 * 验证配置
 * @param {Object} config - 配置对象
 * @returns {Array<string>} 错误信息列表
 */
export function validateConfig(config) {
    const errors = [];
    
    const qb = config.qbittorrent || {};
    const schedule = config.schedule || {};
    
    // 验证 qBittorrent 地址
    if (!qb.host) {
        errors.push('qBittorrent 地址不能为空');
    } else {
        const hostPattern = /^https?:\/\/[\w.-]+(?::\d+)?\/?$/;
        if (!hostPattern.test(qb.host)) {
            errors.push('qBittorrent 地址格式不正确 (示例：http://192.168.1.1:8080)');
        }
    }
    
    // 验证检查间隔
    const interval = schedule.interval || 300;
    if (interval < 60) {
        errors.push('检查间隔不能小于 60 秒');
    }
    if (interval > 86400) {
        errors.push('检查间隔不能大于 24 小时');
    }
    
    // 验证大小范围
    const filter = config.filter || {};
    const minSize = filter.min_size || 0;
    const maxSize = filter.max_size || 0;
    
    if (minSize < 0) {
        errors.push('最小文件大小不能小于 0');
    }
    if (maxSize < 0) {
        errors.push('最大文件大小不能小于 0');
    }
    if (minSize > 0 && maxSize > 0 && minSize >= maxSize) {
        errors.push('最小文件大小必须小于最大文件大小');
    }
    
    return errors;
}
