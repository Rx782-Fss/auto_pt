/**
 * PT Auto Downloader - API Client
 * API 调用封装模块
 * 
 * 功能:
 * - 统一错误处理
 * - 请求超时控制
 * - 自动重试机制
 * - 友好的错误信息
 */

// API 配置
// 注意：api.js 可能被不同的模块路径重复加载（如带/不带版本参数）。
// 这里把配置挂到 window 上，确保所有模块实例共享同一份认证状态。
const API_CONFIG = window.__AUTO_PT_API_CONFIG__ || (window.__AUTO_PT_API_CONFIG__ = {
    timeout: 60000,        // 60 秒超时（预览需要获取 RSS，可能需要更长时间）
    maxRetries: 2,         // 最多重试 2 次
    retryDelay: 1000,      // 重试间隔 1 秒
    authEnabled: false,    // 是否启用认证（默认关闭，后端强制开启时会自动启用）
    token: null            // 认证令牌（会话 token）
});

const AUTH_TOKEN_STORAGE_KEY = 'auth_token';
const AUTH_TOKEN_COOKIE_KEY = 'auto_pt_auth_token';

// API 端点配置
const API = {
    config: '/api/config',
    authToken: '/api/auth/token',
    authRecover: '/api/auth/recover',
    authRecoveryEmail: '/api/auth/recovery-email',
    notificationsTest: '/api/notifications/test',
    history: '/api/history',
    historyClear: '/api/history/clear',
    logs: '/api/logs',
    run: '/api/run',
    preview: '/api/preview',
    download: '/api/download',
    downloadSingle: '/api/download_single',
    qbStatus: '/api/qb/status',
    qbTest: '/api/qb/test'
};

/**
 * 格式化错误信息
 * @param {number} status - HTTP 状态码
 * @param {string} statusText - 状态文本
 * @returns {string} 友好的错误信息
 */
function formatErrorMessage(status, statusText) {
    const errorMap = {
        400: '请求参数错误',
        401: '未授权，请登录',
        403: '拒绝访问',
        404: '请求的资源不存在',
        500: '服务器内部错误',
        502: '网关错误，请稍后重试',
        503: '服务暂时不可用',
        504: '网关超时'
    };
    return errorMap[status] || `请求失败 (${status})`;
}

function setStorageValue(storage, key, value) {
    if (!storage) {
        return;
    }

    try {
        storage.setItem(key, value);
    } catch (error) {
        console.warn('保存认证信息失败:', error);
    }
}

function removeStorageValue(storage, key) {
    if (!storage) {
        return;
    }

    try {
        storage.removeItem(key);
    } catch (error) {
        console.warn('清理认证信息失败:', error);
    }
}

function getStorageValue(storage, key) {
    if (!storage) {
        return null;
    }

    try {
        return storage.getItem(key);
    } catch (error) {
        console.warn('读取认证信息失败:', error);
        return null;
    }
}

function writeAuthTokenCookie(token) {
    document.cookie = `${AUTH_TOKEN_COOKIE_KEY}=${encodeURIComponent(token)}; Max-Age=${60 * 60 * 24 * 30}; Path=/; SameSite=Lax`;
}

function clearAuthTokenCookie() {
    document.cookie = `${AUTH_TOKEN_COOKIE_KEY}=; Max-Age=0; Path=/; SameSite=Lax`;
}

function readAuthTokenCookie() {
    const cookie = document.cookie
        .split('; ')
        .find(item => item.startsWith(`${AUTH_TOKEN_COOKIE_KEY}=`));

    if (!cookie) {
        return null;
    }

    const [, value = ''] = cookie.split('=');
    return value ? decodeURIComponent(value) : null;
}

function syncAuthTokenToStores(token) {
    if (!token) {
        removeStorageValue(window.localStorage, AUTH_TOKEN_STORAGE_KEY);
        removeStorageValue(window.sessionStorage, AUTH_TOKEN_STORAGE_KEY);
        clearAuthTokenCookie();
        return;
    }

    setStorageValue(window.localStorage, AUTH_TOKEN_STORAGE_KEY, token);
    setStorageValue(window.sessionStorage, AUTH_TOKEN_STORAGE_KEY, token);
    writeAuthTokenCookie(token);
}

function readPersistedAuthToken() {
    return (
        getStorageValue(window.localStorage, AUTH_TOKEN_STORAGE_KEY) ||
        getStorageValue(window.sessionStorage, AUTH_TOKEN_STORAGE_KEY) ||
        readAuthTokenCookie()
    );
}

function normalizeAuthToken(token) {
    return typeof token === 'string' ? token.trim() : '';
}

function applyAuthTokenState(token) {
    const normalizedToken = normalizeAuthToken(token);
    API_CONFIG.token = normalizedToken || null;
    API_CONFIG.authEnabled = !!normalizedToken;
    return API_CONFIG.token;
}

function hydrateAuthTokenFromStorage(forceClear = false) {
    const persistedToken = readPersistedAuthToken();
    if (persistedToken) {
        return applyAuthTokenState(persistedToken);
    }

    if (forceClear) {
        applyAuthTokenState(null);
    }

    return API_CONFIG.token;
}

hydrateAuthTokenFromStorage();

async function exchangeAuthTokenForSession(token) {
    const normalizedToken = normalizeAuthToken(token);
    if (!normalizedToken) {
        return null;
    }

    const response = await fetchWithTimeout(API.authToken, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${normalizedToken}`
        }
    }, API_CONFIG.timeout);

    if (!response.ok) {
        let serverMessage = '';
        try {
            const errorData = await response.json();
            serverMessage = errorData?.error || errorData?.message || '';
        } catch (parseError) {
            try {
                serverMessage = (await response.text()).trim();
            } catch (readError) {
                console.warn('读取会话 token 响应失败:', readError);
            }
        }
        throw new Error(serverMessage || formatErrorMessage(response.status, response.statusText));
    }

    const responseData = await response.json();
    const sessionToken = normalizeAuthToken(responseData?.token);
    if (!sessionToken) {
        throw new Error('会话 token 交换失败');
    }

    return sessionToken;
}

async function upgradeLegacyAuthTokenFromResponse(response, endpoint) {
    if (endpoint === API.authToken) {
        return;
    }

    const authMode = response.headers.get('X-Auto-PT-Auth-Mode');
    if (authMode !== 'legacy-secret') {
        return;
    }

    const currentToken = normalizeAuthToken(API_CONFIG.token);
    if (!currentToken) {
        return;
    }

    try {
        const sessionToken = await exchangeAuthTokenForSession(currentToken);
        if (sessionToken && sessionToken !== currentToken) {
            setAuthToken(sessionToken);
        }
    } catch (error) {
        console.warn('升级会话 token 失败:', error);
    }
}

/**
 * 认证失败时交互输入 token
 * @returns {Promise<string|null>}
 */
let pendingAuthTokenRequest = null;
let authTokenRequestResolver = null;
let authTokenPromptSuppressed = false;
let authTokenModalLocked = false;
let authTokenSubmitting = false;

function getAuthTokenModalElements() {
    return {
        modal: document.getElementById('authTokenModal'),
        input: document.getElementById('authTokenInput'),
        error: document.getElementById('authTokenError'),
        closeBtn: document.getElementById('authTokenCloseBtn'),
        cancelBtn: document.getElementById('authTokenCancelBtn'),
        submitBtn: document.getElementById('authTokenSubmitBtn'),
    };
}

function setAuthTokenModalError(message = '') {
    const { error } = getAuthTokenModalElements();
    if (!error) {
        return;
    }

    error.textContent = message;
    error.classList.toggle('is-hidden', !message);
}

function focusAuthTokenInput() {
    const { input } = getAuthTokenModalElements();
    if (!input) {
        return;
    }

    requestAnimationFrame(() => {
        input.focus();
        input.select();
    });
}

function syncAuthTokenModalButtons() {
    const { closeBtn, cancelBtn, submitBtn } = getAuthTokenModalElements();
    const closeLocked = authTokenModalLocked || authTokenSubmitting;

    if (closeBtn) {
        closeBtn.disabled = closeLocked;
        closeBtn.title = closeLocked ? '请先完成 API 认证' : '';
    }

    if (cancelBtn) {
        cancelBtn.disabled = closeLocked;
        cancelBtn.title = closeLocked ? '请先完成 API 认证' : '';
    }

    if (submitBtn) {
        submitBtn.disabled = authTokenSubmitting;
    }
}

function setAuthTokenSubmitLoadingState(isLoading) {
    const { submitBtn } = getAuthTokenModalElements();
    if (!submitBtn) {
        return;
    }

    if (isLoading) {
        if (!submitBtn.dataset.defaultHtml) {
            submitBtn.dataset.defaultHtml = submitBtn.innerHTML;
        }
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="loading"></span><span>验证中...</span>';
        return;
    }

    submitBtn.disabled = authTokenSubmitting;
    if (submitBtn.dataset.defaultHtml) {
        submitBtn.innerHTML = submitBtn.dataset.defaultHtml;
    }
    if (window.lucide) {
        window.lucide.createIcons();
    }
}

function settleAuthTokenRequest(token = null) {
    const { modal, input } = getAuthTokenModalElements();
    const resolver = authTokenRequestResolver;

    if (modal) {
        modal.classList.remove('show');
    }

    authTokenModalLocked = false;
    authTokenSubmitting = false;
    syncAuthTokenModalButtons();
    setAuthTokenSubmitLoadingState(false);

    if (input) {
        input.value = '';
    }

    setAuthTokenModalError('');

    authTokenRequestResolver = null;
    pendingAuthTokenRequest = null;

    if (resolver) {
        resolver(token && token.trim() ? token.trim() : null);
    }
}

function hideAuthTokenModal() {
    settleAuthTokenRequest(null);
}

function setAuthTokenPromptSuppressed(isSuppressed) {
    authTokenPromptSuppressed = Boolean(isSuppressed);
}

function isAnotherModalOpen() {
    return Array.from(document.querySelectorAll('.modal.show'))
        .some(modal => modal.id && modal.id !== 'authTokenModal');
}

function openAuthTokenModal() {
    const { modal, input } = getAuthTokenModalElements();
    if (!modal || !input) {
        return false;
    }

    if (authTokenPromptSuppressed) {
        return false;
    }

    input.value = '';
    setAuthTokenModalError('');
    authTokenModalLocked = true;
    authTokenSubmitting = false;
    syncAuthTokenModalButtons();
    setAuthTokenSubmitLoadingState(false);
    modal.classList.add('show');
    if (window.lucide) {
        window.lucide.createIcons();
    }
    focusAuthTokenInput();
    return true;
}

async function requestAuthTokenFromUser() {
    if (authTokenPromptSuppressed) {
        return pendingAuthTokenRequest;
    }

    if (pendingAuthTokenRequest) {
        focusAuthTokenInput();
        return pendingAuthTokenRequest;
    }

    if (!openAuthTokenModal()) {
        const token = window.prompt('请输入 API 认证密钥');
        if (!token || !token.trim()) {
            return null;
        }
        return token.trim();
    }

    pendingAuthTokenRequest = new Promise(resolve => {
        authTokenRequestResolver = resolve;
    });

    return pendingAuthTokenRequest;
}

window.submitAuthTokenModal = async function() {
    const { input } = getAuthTokenModalElements();
    if (!input) {
        settleAuthTokenRequest(null);
        return;
    }

    if (authTokenSubmitting) {
        return;
    }

    const token = input.value.trim();
    if (!token) {
        setAuthTokenModalError('请输入 API 认证密钥');
        focusAuthTokenInput();
        return;
    }

    authTokenSubmitting = true;
    setAuthTokenModalError('');
    setAuthTokenSubmitLoadingState(true);

    try {
        const sessionToken = await exchangeAuthTokenForSession(token);
        if (!pendingAuthTokenRequest) {
            return;
        }

        setAuthToken(sessionToken);
        settleAuthTokenRequest(sessionToken);
    } catch (error) {
        if (!pendingAuthTokenRequest) {
            return;
        }

        authTokenSubmitting = false;
        setAuthTokenSubmitLoadingState(false);
        setAuthTokenModalError(error?.message || '认证失败：无法交换会话 token');
        focusAuthTokenInput();
    }
};

window.closeAuthTokenModal = function(options = {}) {
    const forceClose = Boolean(options?.force);
    if (authTokenModalLocked && !forceClose) {
        setAuthTokenModalError('请先完成 API 认证');
        focusAuthTokenInput();
        return;
    }

    settleAuthTokenRequest(null);
};

document.addEventListener('keydown', event => {
    const { modal } = getAuthTokenModalElements();
    if (!modal || !modal.classList.contains('show')) {
        return;
    }

    if (isAnotherModalOpen()) {
        return;
    }

    if (event.key === 'Escape') {
        event.preventDefault();
        window.closeAuthTokenModal();
        return;
    }

    if (event.key === 'Enter') {
        const targetTag = event.target?.tagName?.toLowerCase();
        if (targetTag !== 'textarea') {
            event.preventDefault();
            window.submitAuthTokenModal();
        }
    }
});

/**
 * 带超时的 fetch 请求
 * @param {string} url - 请求 URL
 * @param {Object} options - fetch 选项
 * @param {number} timeout - 超时时间 (毫秒)
 * @returns {Promise<Response>} 响应对象
 */
async function fetchWithTimeout(url, options = {}, timeout = API_CONFIG.timeout) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);
    
    try {
        const response = await fetch(url, {
            ...options,
            signal: controller.signal
        });
        clearTimeout(timeoutId);
        return response;
    } catch (error) {
        clearTimeout(timeoutId);
        
        if (error.name === 'AbortError') {
            throw new Error('请求超时，请检查网络连接后重试');
        }
        
        if (error.message.includes('Failed to fetch')) {
            throw new Error('网络连接失败，请检查服务是否正常运行');
        }
        
        throw error;
    }
}

/**
 * 通用 API 请求函数 (带重试)
 * @param {string} endpoint - API 端点
 * @param {Object} options - fetch 选项
 * @param {number} retries - 剩余重试次数
 * @returns {Promise<any>} 响应数据
 */
async function apiRequest(endpoint, options = {}, retries = API_CONFIG.maxRetries) {
    const url = endpoint.startsWith('/') ? endpoint : `/api/${endpoint}`;
    const authRetried = !!options._authRetried;
    const skipAuth = !!options.skipAuth;
    const requestOptionsRaw = { ...options };
    delete requestOptionsRaw._authRetried;
    delete requestOptionsRaw.skipAuth;

    hydrateAuthTokenFromStorage();
    
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
        },
    };
    
    // 如果启用了认证且有 token，添加 Authorization header
    if (!skipAuth && API_CONFIG.authEnabled && API_CONFIG.token) {
        defaultOptions.headers['Authorization'] = `Bearer ${API_CONFIG.token}`;
    }

    // headers 需要深度合并，避免覆盖掉 Authorization
    const mergedOptions = {
        ...defaultOptions,
        ...requestOptionsRaw,
        headers: {
            ...(defaultOptions.headers || {}),
            ...(requestOptionsRaw.headers || {})
        }
    };
    
    try {
        const response = await fetchWithTimeout(url, mergedOptions);
        
        // 处理 HTTP 错误
        if (!response.ok) {
            let serverMessage = '';
            const errorContentType = response.headers.get('content-type') || '';

            if (errorContentType.includes('application/json')) {
                try {
                    const errorData = await response.json();
                    serverMessage = errorData?.error || errorData?.message || '';
                } catch (parseError) {
                    console.warn('解析错误响应失败:', parseError);
                }
            } else {
                try {
                    serverMessage = (await response.text()).trim();
                } catch (parseError) {
                    console.warn('读取错误响应失败:', parseError);
                }
            }

            if (response.status === 401 && !authRetried && !skipAuth) {
                const persistedToken = hydrateAuthTokenFromStorage();
                const hasAuthHeader = Boolean(mergedOptions.headers?.Authorization);

                if (persistedToken && !hasAuthHeader) {
                    return apiRequest(endpoint, { ...options, _authRetried: true }, retries);
                }

                const sessionToken = await requestAuthTokenFromUser();
                if (sessionToken) {
                    setAuthToken(sessionToken);
                    return apiRequest(endpoint, { ...options, _authRetried: true }, retries);
                }
            }

            const errorMsg = serverMessage || formatErrorMessage(response.status, response.statusText);
            
            // 只在特定状态码时重试
            if (retries > 0 && [502, 503, 504].includes(response.status)) {
                console.warn(`请求失败，${API_CONFIG.retryDelay}ms 后重试 (${API_CONFIG.maxRetries - retries + 1}/${API_CONFIG.maxRetries})`);
                await new Promise(resolve => setTimeout(resolve, API_CONFIG.retryDelay));
                return apiRequest(endpoint, options, retries - 1);
            }
            
            throw new Error(errorMsg);
        }
        
        // 解析响应
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
            await upgradeLegacyAuthTokenFromResponse(response, endpoint);
            const data = await response.json();
            // 检查业务逻辑错误
            if (data.success === false && data.message) {
                throw new Error(data.message);
            }
            return data;
        }
        
        await upgradeLegacyAuthTokenFromResponse(response, endpoint);
        return await response.text();
        
    } catch (error) {
        // 网络错误重试
        if (retries > 0 && (
            error.message.includes('timeout') || 
            error.message.includes('network') ||
            error.message.includes('Failed to fetch')
        )) {
            console.warn(`请求失败，${API_CONFIG.retryDelay}ms 后重试 (${API_CONFIG.maxRetries - retries + 1}/${API_CONFIG.maxRetries})`);
            await new Promise(resolve => setTimeout(resolve, API_CONFIG.retryDelay));
            return apiRequest(endpoint, options, retries - 1);
        }
        
        throw error;
    }
}

/**
 * GET 请求
 * @param {string} endpoint - API 端点
 * @param {Object} params - URL 参数
 * @returns {Promise<any>} 响应数据
 */
export async function apiGet(endpoint, params = {}) {
    const url = new URL(endpoint, window.location.origin);
    Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
            url.searchParams.set(key, value);
        }
    });
    return apiRequest(url.pathname + url.search);
}

/**
 * POST 请求
 * @param {string} endpoint - API 端点
 * @param {Object} data - 请求数据
 * @returns {Promise<any>} 响应数据
 */
export async function apiPost(endpoint, data = {}, options = {}) {
    return apiRequest(endpoint, {
        method: 'POST',
        body: JSON.stringify(data),
        ...options,
    });
}

/**
 * PUT 请求
 * @param {string} endpoint - API 端点
 * @param {Object} data - 请求数据
 * @returns {Promise<any>} 响应数据
 */
export async function apiPut(endpoint, data = {}, options = {}) {
    return apiRequest(endpoint, {
        method: 'PUT',
        body: JSON.stringify(data),
        ...options,
    });
}

/**
 * DELETE 请求
 * @param {string} endpoint - API 端点
 * @param {Object} params - URL 参数
 * @param {Object} options - 额外选项（如 body）
 * @returns {Promise<any>} 响应数据
 */
export async function apiDelete(endpoint, params = {}, options = {}) {
    const url = new URL(endpoint, window.location.origin);
    Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
            url.searchParams.set(key, value);
        }
    });
    
    const deleteOptions = {
        method: 'DELETE',
    };
    
    // 如果有请求体，添加 Content-Type 和 body
    if (options.body) {
        deleteOptions.headers = {
            'Content-Type': 'application/json'
        };
        deleteOptions.body = options.body;
    }
    
    return apiRequest(url.pathname + url.search, deleteOptions);
}

// ==================== 配置相关 API ====================

/**
 * 获取配置
 * @returns {Promise<Object>} 配置对象
 */
export function getConfig() {
    return apiGet(API.config);
}

/**
 * 保存配置
 * @param {Object} config - 配置对象
 * @returns {Promise<Object>} 响应数据
 */
export function saveConfig(config) {
    return apiPost(API.config, config);
}

// ==================== 历史记录相关 API ====================

/**
 * 获取历史记录
 * @param {Object} params - 查询参数（days, search）
 * @returns {Promise<Object>} 历史记录列表
 */
export function getHistory(params = {}) {
    return apiGet(API.history, params);
}

/**
 * 删除历史记录（支持批量删除）
 * @param {string|Array<string>} torrentIds - 种子 ID 或 ID 数组
 * @param {string} action - 删除方式（hide/delete）
 * @returns {Promise<Object>} 响应数据
 */
export function deleteHistory(torrentIds, action = 'delete') {
    // 批量删除
    if (Array.isArray(torrentIds)) {
        return apiDelete(API.history, {}, {
            method: 'DELETE',
            body: JSON.stringify({ ids: torrentIds })
        });
    }
    // 单个删除
    return apiDelete(`${API.history}/${torrentIds}`, { action });
}

/**
 * 恢复单条历史记录
 * @param {string} torrentId - 种子 ID
 * @returns {Promise<Object>} 响应数据
 */
export function restoreHistory(torrentId) {
    return apiPost(`${API.history}/${torrentId}/restore`);
}

/**
 * 更新历史记录状态
 * @param {string} torrentId - 种子 ID
 * @param {string} status - 新状态（downloading/completed/seeding/paused）
 * @returns {Promise<Object>} 响应数据
 */
export function updateHistoryStatus(torrentId, status) {
    return apiRequest(`${API.history}/${torrentId}/status`, {
        method: 'PUT',
        body: JSON.stringify({ status })
    });
}

/**
 * 清空所有历史记录
 * @returns {Promise<Object>} 响应数据
 */
export function clearAllHistory() {
    return apiPost(API.historyClear);
}

/**
 * 清除历史记录
 * @param {number} days - 时间范围（0=全部）
 * @returns {Promise<Object>} 响应数据
 */
export function clearHistory(days = 0) {
    return apiDelete(API.history, { days });
}

// ==================== 日志相关 API ====================

/**
 * 获取日志
 * @returns {Promise<Object>} 日志数据
 */
export function getLogs() {
    return apiGet(API.logs);
}

/**
 * 清除日志
 * @returns {Promise<Object>} 响应数据
 */
export function clearLogs() {
    return apiDelete(API.logs);
}

// ==================== 运行控制相关 API ====================

/**
 * 立即运行检查
 * @returns {Promise<Object>} 响应数据
 */
export function runCheck() {
    return apiPost(API.run);
}

/**
 * 预览种子
 * @returns {Promise<Object>} 种子预览数据
 */
export function previewTorrents() {
    return apiPost(API.preview);
}

/**
 * 下载单个种子
 * @param {Object} torrent - 种子信息（id, title, link）
 * @returns {Promise<Object>} 响应数据
 */
export function downloadSingle(torrent) {
    return apiPost(API.downloadSingle, torrent);
}

/**
 * 批量下载种子
 * @param {Array<Object>} torrents - 种子数据列表 [{id, title, link}]
 * @returns {Promise<Object>} 响应数据
 */
export function downloadTorrents(torrents) {
    return apiPost(API.download, { torrents: torrents });
}

// ==================== qBittorrent 相关 API ====================

/**
 * 获取 qBittorrent 状态
 * @returns {Promise<Object>} QB 状态数据
 */
export function getQBStatus() {
    return apiGet(API.qbStatus);
}

/**
 * 测试 qBittorrent 连接
 * @param {Object} credentials - 连接凭证（host, username, password）
 * @returns {Promise<Object>} 响应数据
 */
export function testQBConnection(credentials) {
    return apiPost(API.qbTest, credentials);
}

// 导出 API 端点常量和配置
export { API, API_CONFIG };

// 导出到全局作用域（供非模块脚本使用）
window.apiGet = apiGet;
window.apiPost = apiPost;
window.apiPut = apiPut;
window.apiDelete = apiDelete;

// ==================== 认证相关函数 ====================

/**
 * 设置认证令牌
 * @param {string} token - 认证令牌（会话 token）
 */
export function setAuthToken(token) {
    const normalizedToken = applyAuthTokenState(token) || '';

    // 同时保存到多种浏览器存储，减少强制刷新后再次丢失认证的问题。
    syncAuthTokenToStores(normalizedToken);

    // 兼容旧逻辑：保留 localStorage 中的 auth_token
}

/**
 * 从 localStorage 加载认证令牌
 * @returns {string|null} 认证令牌
 */
export function loadAuthToken() {
    const token = hydrateAuthTokenFromStorage(true);
    if (token) {
        setAuthToken(token);
    }
    return token;
}

/**
 * 将主密钥换成会话 token
 * @param {string} token - 主密钥或会话 token
 * @returns {Promise<string>} 会话 token
 */
export async function exchangeAuthToken(token) {
    return exchangeAuthTokenForSession(token);
}

// 导出认证函数到全局
window.setAuthToken = setAuthToken;
window.loadAuthToken = loadAuthToken;
window.exchangeAuthToken = exchangeAuthToken;
window.setAuthTokenPromptSuppressed = setAuthTokenPromptSuppressed;
window.resolveAuthTokenPrompt = settleAuthTokenRequest;
window.hideAuthTokenModal = hideAuthTokenModal;
window.focusAuthTokenInput = focusAuthTokenInput;
window.openAuthTokenModal = openAuthTokenModal;

// 导出 API_CONFIG 到全局（重要！用于其他模块检查认证状态）
window.apiConfig = API_CONFIG;
