/**
 * PT Auto Downloader - Main Entry
 * 主入口文件
 */

import { loadConfig, saveConfigData, getQBConfig, getCachedConfig } from './config.js?v=3';
import { loadLogs, clearAllLogs, applyLogFilters, setLogFilters, startLogAutoRefresh, stopLogAutoRefresh, isLogAutoRefreshEnabled } from './logs.js?v=199';
import { loadHistoryData, renderHistoryList, toggleAll, invertSelection, updateSelectedCount, deleteOne, deleteSelected, hideSelected, restoreAllHidden, goToPage, prevPage, nextPage, goToFirstPage, goToLastPage, changePageSize, searchHistoryDynamic, filterHistory, loadHistory, toggleSelectByTitle, toggleHistoryItem, updatePaginationButtons } from './history.js?v=180';
import { renderPreviewList, downloadSingleTorrent, downloadMultipleTorrents, getSelectedTorrents, updateTorrentStatus, clearPreviewCache, getStats, toggleTorrentSelection, updateSelectedCountInModal, askRedownload, updatePreviewCache, renderPreviewToolbar } from './preview.js?v=176';
import { getQBStatus, testQBConnection, deleteHistory, setAuthToken, loadAuthToken, exchangeAuthToken, apiPut, apiGet, apiPost } from './api.js?v=174';
import { escapeHtml, hideSensitiveInfo, debounce, formatDateTime } from './utils.js';
import { togglePanel } from './panel-manager.js?v=3';
import { refreshDashboardStats } from './dashboard-stats.js?v=20';

// ==================== 全局状态 ====================

// 当前操作的站点名称（用于配置弹窗）
let currentSiteName = null;

let _currentDeleteTarget = null;
let _logCache = '';
const PANEL_STATUS_CLASSES = ['status-muted', 'status-success', 'status-warning', 'status-error'];
let pendingRecoveryCodeAction = null;

function setElementHidden(element, hidden) {
    if (!element) {
        return;
    }

    element.classList.toggle('is-hidden', hidden);
}

function setPreviewDownloadButtonLoadingState(isLoading, loadingText = '下载中...') {
    const downloadBtn = document.getElementById('downloadBtn');
    if (!downloadBtn) {
        return null;
    }

    if (isLoading) {
        if (!downloadBtn.dataset.defaultHtml) {
            downloadBtn.dataset.defaultHtml = downloadBtn.innerHTML;
        }
        downloadBtn.disabled = true;
        downloadBtn.classList.remove('is-hidden');
        downloadBtn.classList.add('is-loading');
        downloadBtn.innerHTML = `<span class="loading"></span><span>${loadingText}</span>`;
        return downloadBtn;
    }

    downloadBtn.classList.remove('is-loading');
    if (downloadBtn.dataset.defaultHtml) {
        downloadBtn.innerHTML = downloadBtn.dataset.defaultHtml;
    }
    return downloadBtn;
}

function setPanelStatus(statusEl, message = '', tone = 'muted') {
    if (!statusEl) {
        return;
    }

    const normalizedTone = ['muted', 'success', 'warning', 'error'].includes(tone) ? tone : 'muted';
    statusEl.textContent = message;
    statusEl.classList.remove(...PANEL_STATUS_CLASSES);
    statusEl.classList.add(`status-${normalizedTone}`);
    statusEl.classList.toggle('is-hidden', !message);
}

function cloneConfigData(config) {
    if (!config || typeof config !== 'object') {
        return {};
    }

    if (typeof structuredClone === 'function') {
        return structuredClone(config);
    }

    return JSON.parse(JSON.stringify(config));
}

function areConfigsEquivalent(left, right) {
    return JSON.stringify(left || {}) === JSON.stringify(right || {});
}

function getNotificationEventStates(notificationConfig = {}) {
    const safeConfig = notificationConfig && typeof notificationConfig === 'object' ? notificationConfig : {};
    const fallbackEnabled = Boolean(safeConfig.enabled);
    const hasStartFlag = Object.prototype.hasOwnProperty.call(safeConfig, 'download_start_enabled');
    const hasCompleteFlag = Object.prototype.hasOwnProperty.call(safeConfig, 'download_complete_enabled');

    return {
        downloadStartEnabled: hasStartFlag ? Boolean(safeConfig.download_start_enabled) : fallbackEnabled,
        downloadCompleteEnabled: hasCompleteFlag ? Boolean(safeConfig.download_complete_enabled) : fallbackEnabled,
    };
}

function inferTransportModeFromPort(port) {
    if (port === 587 || port === 2525) {
        return 'starttls';
    }
    if (port === 25) {
        return 'plain';
    }
    return 'ssl';
}

function getDefaultSmtpPortForTransport(mode) {
    if (mode === 'starttls') {
        return 587;
    }
    if (mode === 'plain') {
        return 25;
    }
    return 465;
}

function setButtonLoadingState(button, isLoading, loadingText = '保存中...') {
    if (!button) {
        return;
    }

    if (isLoading) {
        if (!button.dataset.defaultHtml) {
            button.dataset.defaultHtml = button.innerHTML;
        }
        button.disabled = true;
        button.classList.add('is-loading');
        button.innerHTML = `<span class="loading"></span><span>${loadingText}</span>`;
        return;
    }

    button.disabled = false;
    button.classList.remove('is-loading');
    if (button.dataset.defaultHtml) {
        button.innerHTML = button.dataset.defaultHtml;
    }
}

let currentWhitelistIPsState = [];

function setCurrentWhitelistIPs(ips = []) {
    currentWhitelistIPsState = Array.isArray(ips)
        ? ips.map(ip => String(ip || '').trim()).filter(Boolean)
        : [];
    return [...currentWhitelistIPsState];
}

function getCurrentWhitelistIPs() {
    return [...currentWhitelistIPsState];
}

function normalizeAccessModeValue(mode) {
    const normalized = String(mode || 'lan').trim().toLowerCase();

    if (normalized === 'local') return 'lan';
    if (normalized === 'all') return 'public';
    if (['lan', 'whitelist', 'public'].includes(normalized)) return normalized;
    return 'lan';
}

function updateWhitelistCountUI(ips = getCurrentWhitelistIPs()) {
    const countSpan = document.getElementById('whitelistCount');
    if (countSpan) {
        countSpan.textContent = ips.length > 0 ? `(${ips.length} 个 IP)` : '(未设置)';
    }
}

function handleAccessModeChangeGlobal() {
    const whitelistDiv = document.getElementById('whitelistConfig');
    const accessModeRadio = document.querySelector('input[name="accessMode"]:checked');
    const accessMode = normalizeAccessModeValue(accessModeRadio ? accessModeRadio.value : 'lan');

    setElementHidden(whitelistDiv, accessMode !== 'whitelist');
    updateWhitelistCountUI();
}

function showWhitelistModalGlobal() {
    const modal = document.getElementById('whitelistModal');
    const textarea = document.getElementById('whitelistInput');
    const countSpan = document.getElementById('whitelistCount');

    loadConfig().then(config => {
        const ips = setCurrentWhitelistIPs(config?.app?.allowed_ips || []);
        if (textarea) {
            textarea.value = ips.join('\n');
        }
        updateWhitelistCountUI(ips);
    }).catch(err => {
        console.error('加载白名单失败:', err);
        setCurrentWhitelistIPs([]);
        if (textarea) {
            textarea.value = '';
        }
        if (countSpan) {
            countSpan.textContent = '(加载失败)';
        }
    });

    if (modal) {
        modal.classList.add('show');
        if (window.lucide) {
            window.lucide.createIcons();
        }
    }
}

function closeWhitelistModalGlobal() {
    const modal = document.getElementById('whitelistModal');
    if (modal) {
        modal.classList.remove('show');
    }
}

async function saveWhitelistGlobal() {
    const textarea = document.getElementById('whitelistInput');
    const text = textarea?.value.trim() || '';
    const ips = text ? text.split('\n').map(ip => ip.trim()).filter(Boolean) : [];

    try {
        const accessModeInputs = document.getElementsByName('accessMode');
        let accessMode = 'lan';
        for (const input of accessModeInputs) {
            if (input.checked) {
                accessMode = input.value;
                break;
            }
        }

        const configData = {
            app: {
                access_control: accessMode,
                allowed_ips: ips,
            }
        };

        const result = await saveConfigData(configData);
        if (!result.success) {
            throw new Error(result.message || '保存失败');
        }

        if (window._appConfig?.app) {
            window._appConfig.app.access_control = accessMode;
            window._appConfig.app.allowed_ips = ips;
        }

        const newConfig = await loadConfig();
        if (newConfig?.app) {
            window._appConfig = newConfig;
            setCurrentWhitelistIPs(newConfig.app.allowed_ips || []);
        } else {
            setCurrentWhitelistIPs(ips);
        }

        closeWhitelistModalGlobal();
        updateWhitelistCountUI(ips);
        showToast('白名单已保存', 'success');
    } catch (e) {
        showToast('保存失败：' + e.message, 'error');
    }
}

// ==================== 初始化 ====================

/**
 * 页面加载完成后初始化
 */
document.addEventListener('DOMContentLoaded', async () => {
    try {
        // 先注册恢复相关入口，避免初始化或配置加载失败时按钮不可用
        window.openNotificationBackupPanel = openNotificationBackupPanel;
        window.openRecoveryModal = openRecoveryModal;
        window.closeRecoveryCodeModal = closeRecoveryCodeModal;
        window.closeRecoveryResetModal = closeRecoveryResetModal;
        window.confirmRecoveryCodeSaved = confirmRecoveryCodeSaved;
        window.showRecoveryCodeModal = showRecoveryCodeModal;
        window.copyRecoveryCode = copyRecoveryCode;
        window.copyRecoverySecret = copyRecoverySecret;
        window.submitRecoveryModal = submitRecoveryModal;
        window.generateRandomSecret = generateRandomSecret;

        await initPage();
        
        // 导出全局函数（供 HTML onclick 使用）
        // 必须在 DOM 加载后执行
        window.handleTestQBConnection = handleTestQBConnection;
        window.saveSite = saveSite;
        window.deleteCurrentSite = deleteCurrentSite;
        window.toggleSiteByName = toggleSiteByName;
        window.previewSiteTorrents = previewSiteTorrents;
        window.closeSiteModal = closeSiteModal;
        
        // 历史记录管理功能
        window.loadHistoryData = loadHistoryData;
        window.renderHistoryList = renderHistoryList;
        window.toggleAll = toggleAll;
        window.invertSelection = invertSelection;
        window.updateSelectedCount = updateSelectedCount;
        window.deleteOne = deleteOne;
        window.deleteSelected = deleteSelected;
        window.hideSelected = hideSelected;
        window.restoreAllHidden = restoreAllHidden;
        window.goToPage = goToPage;
        window.goToFirstPage = goToFirstPage;
        window.goToLastPage = goToLastPage;
        window.prevPage = prevPage;
        window.nextPage = nextPage;
        window.changePageSize = changePageSize;
        window.updatePaginationButtons = updatePaginationButtons;
        window.searchHistoryDynamic = searchHistoryDynamic;
        window.filterHistory = filterHistory;
        window.toggleHistoryItem = toggleHistoryItem;
        
        // 日志功能
        window.refreshLogs = refreshLogs;
        window.clearLogs = clearLogs;
        window.copyLogs = copyLogs;
        window.applyLogFilters = applyLogFilters;
        window.applyLogFiltersUI = applyLogFiltersUI;
        
/**
 * 保存端口配置
 */
async function saveWebPort() {
    const portInput = document.getElementById('webPort');
    const currentPortDisplay = document.getElementById('currentPort');
    
    if (!portInput) {
        showToast('端口输入框不存在', 'error');
        return;
    }
    
    const newPort = parseInt(portInput.value);
    const oldPort = currentPortDisplay ? parseInt(currentPortDisplay.textContent) : 5000;
    
    // 验证端口
    if (isNaN(newPort) || newPort < 1 || newPort > 65535) {
        showToast('端口号必须在 1-65535 之间', 'error');
        return;
    }
    
    // 如果端口没变，直接提示
    if (newPort === oldPort) {
        showToast('端口未变更', 'info');
        return;
    }
    
    try {
        // 显示确认模态框，密钥不再明文展示
        showPortChangeModal(newPort, oldPort, '');
        
    } catch (e) {
        showToast('获取配置失败：' + e.message, 'error');
    }
}

/**
 * 显示端口修改确认模态框
 */
function showPortChangeModal(newPort, oldPort, secret) {
    const modal = document.getElementById('portChangeModal');
    const oldPortEl = document.getElementById('oldPortNumber');
    const newPortEl = document.getElementById('newPortNumber');
    const portUrlEl = document.getElementById('newPortUrl');
    const secretInput = document.getElementById('modalSecretInput');
    
    if (oldPortEl) oldPortEl.textContent = oldPort;
    if (newPortEl) newPortEl.textContent = newPort;
    if (portUrlEl) portUrlEl.textContent = 'http://localhost:' + newPort;
    if (secretInput) {
        secretInput.value = secret || '';
        secretInput.placeholder = secret ? secret : '密钥已隐藏，不再显示明文';
    }
    
    // 设置待确认的端口修改信息
    window._pendingPortChange = {
        oldPort: oldPort,
        newPort: newPort
    };
    
    // 同时更新警告提示中的新端口
    const newPortUrl2 = document.getElementById('newPortUrl2');
    if (newPortUrl2) {
        newPortUrl2.textContent = 'http://localhost:' + newPort;
    }
    
    if (modal) {
        modal.classList.add('show');
        if (window.lucide) lucide.createIcons();
    }
}

/**
 * 关闭端口修改提示模态框
 */
function closePortChangeModal() {
    const modal = document.getElementById('portChangeModal');
    if (modal) modal.classList.remove('show');
    window._pendingPortChange = null;
}

/**
 * 取消端口修改
 */
function cancelPortChange() {
    const pending = window._pendingPortChange;
    if (pending && pending.oldPort) {
        const portInput = document.getElementById('webPort');
        if (portInput) portInput.value = pending.oldPort;
    }
    closePortChangeModal();
    showToast('已取消端口修改', 'info');
}

/**
 * 确认端口修改
 */
async function confirmPortChange() {
    const pending = window._pendingPortChange;
    if (!pending) {
        showToast('没有待确认的修改', 'error');
        return;
    }
    try {
        const saveResult = await saveSystemConfig(pending.newPort, {
            silentSuccess: true,
            silentRestartHint: true
        });
        if (!saveResult?.success) {
            return;
        }
        document.getElementById('currentPort').textContent = pending.newPort;
        closePortChangeModal();
        showToast('端口已改为 ' + pending.newPort + '，请重启服务生效', 'success');
    } catch (e) {
        showToast('保存失败：' + e.message, 'error');
    }
}

/**
 * 复制模态框中的密钥
 */
function copyModalSecret() {
    const secretInput = document.getElementById('modalSecretInput');
    if (secretInput && secretInput.value) {
        navigator.clipboard.writeText(secretInput.value).then(function() {
            showToast('密钥已复制到剪贴板', 'success');
        }).catch(function() {
            secretInput.select();
            document.execCommand('copy');
            showToast('密钥已复制到剪贴板', 'success');
        });
    } else {
        showToast('当前不再显示密钥明文', 'info');
    }
}

function getRecoveryModalElements() {
    return {
        modal: document.getElementById('recoveryCodeModal'),
        title: document.getElementById('recoveryCodeTitle'),
        intro: document.getElementById('recoveryCodeIntro'),
        secretGroup: document.getElementById('recoverySecretGroup'),
        secretValue: document.getElementById('recoverySecretValue'),
        secretCopyBtn: document.getElementById('recoverySecretCopyBtn'),
        value: document.getElementById('recoveryCodeValue'),
        hint: document.getElementById('recoveryCodeHint'),
        copyBtn: document.getElementById('recoveryCodeCopyBtn'),
        confirmBtn: document.getElementById('recoveryCodeConfirmBtn'),
    };
}

function setRecoveryModalError(message = '') {
    const errorEl = document.getElementById('recoveryModalError');
    if (!errorEl) {
        return;
    }

    errorEl.textContent = message;
    errorEl.classList.toggle('is-hidden', !message);
}

function renderRecoveryModalIntro(element, text) {
    if (!element) {
        return;
    }

    const normalizedText = String(text || '').trim();
    if (!normalizedText) {
        element.textContent = '';
        return;
    }

    const match = normalizedText.match(/^(.+?。)(.*)$/);
    if (!match) {
        element.textContent = normalizedText;
        return;
    }

    const leadText = match[1].trim();
    const tailText = match[2].trim();

    element.textContent = '';

    const lead = document.createElement('strong');
    lead.className = 'recovery-intro-lead';
    lead.textContent = leadText;
    element.appendChild(lead);

    if (tailText) {
        const tail = document.createElement('span');
        tail.className = 'recovery-intro-tail';
        tail.textContent = tailText;
        element.appendChild(tail);
    }
}

function showRecoveryCodeModal(recoveryCode, options = {}) {
    const { modal, title, intro, secretGroup, secretValue, secretCopyBtn, value, hint, confirmBtn } = getRecoveryModalElements();
    if (!modal || !value) {
        return false;
    }

    if (typeof closeRecoveryResetModal === 'function') {
        closeRecoveryResetModal({ resumeAuthPrompt: false });
    }

    const secretText = String(options.secret || '').trim();
    const titleText = options.title || (secretText ? '重要：新的密钥和恢复码已生成' : '重要：恢复码已生成');
    const introText = options.intro || (secretText
        ? '重要：新的 API 密钥和恢复码只显示一次，请立即保存。'
        : '重要：一次性恢复码只显示一次。请至少完成一项：配置邮箱通知备份，或者离线保存并牢记恢复码。');
    const hintText = options.hint || (secretText
        ? '关闭后将不再显示，建议先复制新的 API 密钥，再复制恢复码。'
        : '恢复码只用于忘记 API 密钥时重置访问权限。没有邮箱备份时，请务必离线保存这段代码。');
    const confirmText = options.confirmText || '我已保存';

    if (title) title.textContent = titleText;
    if (intro) renderRecoveryModalIntro(intro, introText);
    if (hint) hint.textContent = hintText;
    if (secretGroup && secretValue) {
        const hasSecret = Boolean(secretText);
        secretGroup.classList.toggle('is-hidden', !hasSecret);
        secretValue.value = hasSecret ? secretText : '';
        secretValue.dataset.recoverySecret = hasSecret ? secretText : '';
        if (secretCopyBtn) {
            secretCopyBtn.classList.toggle('is-hidden', !hasSecret);
        }
    }
    value.value = recoveryCode || '';
    value.dataset.recoveryCode = recoveryCode || '';
    if (confirmBtn) confirmBtn.textContent = confirmText;
    if (secretValue && secretText && typeof secretValue.focus === 'function') {
        secretValue.focus({ preventScroll: true });
        if (typeof secretValue.select === 'function') {
            secretValue.select();
        }
    } else if (typeof value.focus === 'function') {
        value.focus({ preventScroll: true });
        if (typeof value.select === 'function') {
            value.select();
        }
    }

    pendingRecoveryCodeAction = typeof options.onConfirm === 'function' ? options.onConfirm : null;
    setRecoveryModalError('');
    modal.classList.add('show');
    if (window.lucide) {
        window.lucide.createIcons();
    }
    return true;
}

function closeRecoveryCodeModal() {
    const { modal, secretGroup, secretValue, value } = getRecoveryModalElements();
    if (modal) {
        modal.classList.remove('show');
    }
    if (secretGroup) {
        secretGroup.classList.add('is-hidden');
    }
    if (secretValue) {
        secretValue.value = '';
        delete secretValue.dataset.recoverySecret;
    }
    if (value) {
        value.value = '';
        delete value.dataset.recoveryCode;
    }
    setRecoveryModalError('');
    pendingRecoveryCodeAction = null;
    requestAnimationFrame(() => {
        const authModal = document.getElementById('authTokenModal');
        if (authModal?.classList.contains('show') && typeof window.focusAuthTokenInput === 'function') {
            window.focusAuthTokenInput();
        }
    });
}

function getRecoveryResetModalElements() {
    return {
        modal: document.getElementById('recoveryResetModal'),
        codeInput: document.getElementById('recoveryCodeInput'),
        secretInput: document.getElementById('recoveryNewSecretInput'),
        error: document.getElementById('recoveryResetError'),
        confirmBtn: document.getElementById('recoveryResetBtn'),
    };
}

function setRecoveryResetModalError(message = '') {
    const { error } = getRecoveryResetModalElements();
    if (!error) {
        return;
    }

    error.textContent = message;
    error.classList.toggle('is-hidden', !message);
}

function closeRecoveryResetModal(options = {}) {
    const { resumeAuthPrompt = true } = options;
    const { modal, codeInput, secretInput, confirmBtn } = getRecoveryResetModalElements();
    if (modal) {
        modal.classList.remove('show');
    }
    if (codeInput) {
        codeInput.value = '';
    }
    if (secretInput) {
        secretInput.value = '';
    }
    setRecoveryResetModalError('');
    setButtonLoadingState(confirmBtn, false);
    if (resumeAuthPrompt) {
        requestAnimationFrame(() => {
            const authModal = document.getElementById('authTokenModal');
            if (authModal?.classList.contains('show') && typeof window.focusAuthTokenInput === 'function') {
                window.focusAuthTokenInput();
            }
        });
    }
}

function confirmRecoveryCodeSaved() {
    const pendingAction = pendingRecoveryCodeAction;
    closeRecoveryCodeModal();
    if (typeof pendingAction === 'function') {
        pendingAction();
    }
}

function copyModalFieldValue(input, emptyMessage, successMessage) {
    const field = input;
    const text = field?.value || '';
    if (!text) {
        showToast(emptyMessage, 'warning');
        return;
    }

    navigator.clipboard.writeText(text).then(() => {
        showToast(successMessage, 'success');
    }).catch(() => {
        if (field) {
            field.select();
            document.execCommand('copy');
            showToast(successMessage, 'success');
        }
    });
}

function copyRecoveryCode() {
    const { value } = getRecoveryModalElements();
    copyModalFieldValue(value, '当前没有可复制的恢复码', '恢复码已复制到剪贴板');
}

function copyRecoverySecret() {
    const { secretValue } = getRecoveryModalElements();
    copyModalFieldValue(secretValue, '当前没有可复制的新密钥', '新密钥已复制到剪贴板');
}

function openRecoveryModal() {
    if (typeof closeRecoveryCodeModal === 'function') {
        closeRecoveryCodeModal();
    }
    if (typeof closeRecoveryResetModal === 'function') {
        closeRecoveryResetModal({ resumeAuthPrompt: false });
    }

    const { modal, codeInput, secretInput } = getRecoveryResetModalElements();
    if (!modal || !codeInput || !secretInput) {
        showToast('恢复码重置弹窗未加载', 'error');
        return false;
    }

    codeInput.value = '';
    secretInput.value = '';
    setRecoveryResetModalError('');
    requestAnimationFrame(() => {
        modal.classList.add('show');
        if (window.lucide) {
            window.lucide.createIcons();
        }
        if (typeof codeInput.focus === 'function') {
            codeInput.focus();
        }
    });
    return true;
}

async function openNotificationBackupPanel() {
    try {
        const result = await apiPost('/api/auth/recovery-email', {}, {
            skipAuth: true,
        });

        if (!result?.success) {
            throw new Error(result?.error || result?.message || '发送失败');
        }

        if (typeof window.closeAuthTokenModal === 'function') {
            window.closeAuthTokenModal({ force: true });
        }
        showConfirmModal(
            '邮箱恢复已发送',
            result?.message || '已向邮箱发送验证信息，请到邮箱接收。',
            '',
            null,
            {
                confirmText: '知道了',
                cancelText: '关闭',
            }
        );
        return true;
    } catch (error) {
        const message = error?.message || '发送失败';
        const noEmailConfigured = message.includes('没有设置邮箱信息');
        const refocusAuthInput = () => {
            requestAnimationFrame(() => {
                const authModal = document.getElementById('authTokenModal');
                if (authModal?.classList.contains('show') && typeof window.focusAuthTokenInput === 'function') {
                    window.focusAuthTokenInput();
                }
            });
        };
        if (!noEmailConfigured) {
            console.error('[main.js] 邮箱恢复失败:', error);
        }
        showConfirmModal(
            noEmailConfigured ? '邮箱恢复不可用' : '邮箱恢复失败',
            noEmailConfigured
                ? '没有设置邮箱信息，请改用恢复码恢复。'
                : `邮箱恢复失败：${message}`,
            '',
            noEmailConfigured ? refocusAuthInput : null,
            {
                confirmText: '知道了',
                cancelText: noEmailConfigured ? '返回' : '关闭',
                onCancel: noEmailConfigured ? refocusAuthInput : null,
            }
        );
        return false;
    }
}

async function submitRecoveryModal() {
    const { modal, codeInput, secretInput, confirmBtn } = getRecoveryResetModalElements();
    if (!modal || !codeInput || !secretInput) {
        showToast('恢复码重置弹窗未加载', 'error');
        return;
    }

    const recoveryCode = codeInput?.value.trim() || '';
    const newSecret = secretInput?.value.trim() || '';

    if (!recoveryCode) {
        setRecoveryResetModalError('请输入恢复码');
        codeInput?.focus();
        return;
    }
    if (!newSecret) {
        setRecoveryResetModalError('请输入新的 API 密钥');
        secretInput?.focus();
        return;
    }
    if (window._appConfig?.app?.secret_source === 'env') {
        setRecoveryResetModalError('当前由 APP_SECRET 环境变量管理密钥，页面重置不会生效');
        return;
    }

    setRecoveryResetModalError('');
    setButtonLoadingState(confirmBtn, true, '重置中...');

    try {
        const result = await apiPost('/api/auth/recover', {
            recovery_code: recoveryCode,
            secret: newSecret,
        }, {
            skipAuth: true,
        });

        if (!result?.success) {
            throw new Error(result?.error || result?.message || '重置失败');
        }

        closeRecoveryResetModal({ resumeAuthPrompt: false });

        if (result?.auth?.session_token) {
            window.setAuthToken(result.auth.session_token);
        }
        if (result?.config) {
            window._appConfig = result.config;
        }

        if (typeof window.resolveAuthTokenPrompt === 'function') {
            window.resolveAuthTokenPrompt(result?.auth?.session_token || newSecret);
        } else if (typeof window.closeAuthTokenModal === 'function') {
            window.closeAuthTokenModal({ force: true });
        }

        if (!result.recovery_code_sent && result.recovery_code_send_error) {
            showToast(`恢复码邮件发送失败：${result.recovery_code_send_error}`, 'warning');
        } else if (result.recovery_code_sent) {
            showToast('新的恢复码已发送到邮箱', 'success');
        }

        showRecoveryCodeModal(result.recovery_code, {
            secret: result?.secret || newSecret,
            title: '重要：新的密钥和恢复码已生成',
            intro: '重要：新的 API 密钥和恢复码只显示一次，请立即保存。',
            hint: '旧的恢复码已经失效。建议先复制新的 API 密钥，再复制新的恢复码。',
            confirmText: '完成',
            onConfirm: () => {
                window.location.reload();
            },
        });
    } catch (e) {
        setRecoveryResetModalError(e.message || '恢复失败');
        showToast('恢复失败：' + (e.message || '未知错误'), 'error');
    } finally {
        setButtonLoadingState(confirmBtn, false);
    }
}

// ==================== IP 白名单管理 ====================

// 当前白名单数据（从配置加载）
let currentWhitelistIPs = [];

function normalizeAccessMode(mode) {
    const normalized = (mode || 'lan').trim().toLowerCase();

    if (normalized === 'local') return 'lan';
    if (normalized === 'all') return 'public';
    if (['lan', 'whitelist', 'public'].includes(normalized)) return normalized;
    return 'lan';
}

function updateWhitelistCount(ips = []) {
    const countSpan = document.getElementById('whitelistCount');
    if (countSpan) {
        countSpan.textContent = ips.length > 0 ? `(${ips.length} 个 IP)` : '(未设置)';
    }
}

function handleAccessModeChange() {
    const whitelistDiv = document.getElementById('whitelistConfig');
    const accessModeRadio = document.querySelector('input[name="accessMode"]:checked');
    const accessMode = normalizeAccessMode(accessModeRadio ? accessModeRadio.value : 'lan');

    // 仅在白名单模式下显示白名单管理区域
    setElementHidden(whitelistDiv, accessMode !== 'whitelist');

    updateWhitelistCount(currentWhitelistIPs);
}

function showWhitelistModal() {
    const modal = document.getElementById('whitelistModal');
    const textarea = document.getElementById('whitelistInput');
    const countSpan = document.getElementById('whitelistCount');
    
    // 直接从 API 获取最新配置
    loadConfig().then(config => {
        currentWhitelistIPs = config?.app?.allowed_ips || [];
        textarea.value = currentWhitelistIPs.join('\n');
        updateWhitelistCount(currentWhitelistIPs);
    }).catch(err => {
        console.error('加载白名单失败:', err);
        currentWhitelistIPs = [];
        textarea.value = '';
        if (countSpan) {
            countSpan.textContent = '(加载失败)';
        }
    });
    
    if (modal) {
        modal.classList.add('show');
        if (window.lucide) lucide.createIcons();
    }
}

function closeWhitelistModal() {
    const modal = document.getElementById('whitelistModal');
    if (modal) modal.classList.remove('show');
}

async function saveWhitelist() {
    const textarea = document.getElementById('whitelistInput');
    const text = textarea.value.trim();
    
    // 解析 IP 列表
    const ips = text ? text.split('\n').map(ip => ip.trim()).filter(ip => ip) : [];
    
    try {
        // 构建配置数据
        const accessModeInputs = document.getElementsByName('accessMode');
        let accessMode = 'lan';
        for (const input of accessModeInputs) {
            if (input.checked) {
                accessMode = input.value;
                break;
            }
        }
        
        const configData = {
            app: {
                access_control: accessMode,
                allowed_ips: ips
            }
        };
        
        const result = await saveConfigData(configData);
        
        if (!result.success) {
            throw new Error(result.message || '保存失败');
        }
        
        // 更新本地配置缓存
        if (window._appConfig) {
            window._appConfig.app.access_control = accessMode;
            window._appConfig.app.allowed_ips = ips;
        }
        
        // 重新从 API 获取最新配置
        const newConfig = await loadConfig();
        if (newConfig && newConfig.app) {
            window._appConfig = newConfig;
            currentWhitelistIPs = newConfig.app.allowed_ips || [];
        }
        
        closeWhitelistModal();
        
        // 更新显示
        updateWhitelistCount(ips);
        
        showToast('白名单已保存', 'success');
        
    } catch (e) {
        showToast('保存失败：' + e.message, 'error');
    }
}

        window.showPortChangeModal = showPortChangeModal;
        window.closePortChangeModal = closePortChangeModal;
        window.cancelPortChange = cancelPortChange;
        window.confirmPortChange = confirmPortChange;
        window.copyModalSecret = copyModalSecret;
        window.saveWebPort = saveWebPort;
        window.toggleSystemPanel = toggleSystemPanel;
        window.saveSystemConfig = saveSystemConfig;
        window.handleSystemLogLevelChange = handleSystemLogLevelChange;
        window.toggleNotificationPanel = toggleNotificationPanel;
        window.loadNotificationConfig = loadNotificationConfig;
        window.saveNotificationConfig = saveNotificationConfig;
        window.testNotificationEmail = testNotificationEmail;
        window.openRecoveryModal = openRecoveryModal;
        window.closeRecoveryCodeModal = closeRecoveryCodeModal;
        window.closeRecoveryResetModal = closeRecoveryResetModal;
        window.confirmRecoveryCodeSaved = confirmRecoveryCodeSaved;
        window.showRecoveryCodeModal = showRecoveryCodeModal;
        window.copyRecoveryCode = copyRecoveryCode;
        window.submitRecoveryModal = submitRecoveryModal;
        window.generateRandomSecret = generateRandomSecret;
        
        // 白名单管理
        window.showWhitelistModal = showWhitelistModalGlobal;
        window.closeWhitelistModal = closeWhitelistModalGlobal;
        window.saveWhitelist = saveWhitelistGlobal;
        window.handleAccessModeChange = handleAccessModeChangeGlobal;
        
        // 首次使用提示
        window.closeFirstTimeModal = closeFirstTimeModal;
        window.goToSystemSettings = goToSystemSettings;
        window.handleSystemConfigSave = handleSystemConfigSave;
        window.handleNotificationConfigSave = handleNotificationConfigSave;
        
        console.log('[main.js] 全局函数已导出');
    } catch (e) {
        console.error('Init error:', e);
        showToast('页面初始化失败：' + e.message, 'error');
    }
});

/**
 * 检查认证状态并显示相应提示
 */
async function checkAuthStatus(config = null) {
    try {
        // 复用已加载的配置，避免首次启动时重复请求
        const currentConfig = config || await loadConfig();
        const authConfigured = Boolean(currentConfig?.app?.auth_configured);
        
        const authStatusItem = document.getElementById('authStatusItem');
        const authStatusText = document.getElementById('authStatusText');
        const authStatusDot = document.getElementById('authStatusDot');
        const systemSettingsBtn = document.getElementById('systemSettingsBtn');
        const authBadge = document.getElementById('authBadge');
        
        if (!authConfigured) {
            // 显示状态栏指示
            setElementHidden(authStatusItem, false);
            if (authStatusText) authStatusText.textContent = '未设置密钥';
            if (authStatusDot) authStatusDot.classList.add('status-dot-warning');
            
            // 给系统设置按钮添加高亮
            if (systemSettingsBtn) {
                systemSettingsBtn.classList.add('need-auth');
            }
            // 显示徽章
            setElementHidden(authBadge, false);
            
            // 每次未设置密钥都显示弹窗
            showFirstTimeModal();
        } else {
            setElementHidden(authStatusItem, true);
            setElementHidden(authBadge, true);
            if (authStatusDot) authStatusDot.classList.remove('status-dot-warning');
            if (systemSettingsBtn) {
                systemSettingsBtn.classList.remove('need-auth');
            }
        }

        return authConfigured;
    } catch (error) {
        console.error('检查认证状态失败:', error);
        return null;
    }
}

/**
 * 显示首次使用提示弹窗
 */
function showFirstTimeModal() {
    const modal = document.getElementById('firstTimeModal');
    if (modal) {
        modal.classList.add('show');
    }
}

/**
 * 关闭首次使用提示弹窗
 */
function closeFirstTimeModal() {
    const modal = document.getElementById('firstTimeModal');
    if (modal) {
        modal.classList.remove('show');
    }
}

/**
 * 跳转到系统设置
 */
function goToSystemSettings() {
    closeFirstTimeModal();
    toggleSystemPanel();
}

async function initPage() {
    try {
        // 加载认证令牌（从 localStorage）
        console.log('[initPage] 开始加载认证令牌...');
        const token = loadAuthToken();
        console.log('[initPage] localStorage 中的 token:', token ? '已加载' : '未找到');
        console.log('[initPage] API_CONFIG.authEnabled:', window.apiConfig?.authEnabled);
        console.log('[initPage] API_CONFIG.token:', window.apiConfig?.token ? '已设置' : '未设置');
        
        // 加载配置（包括 QB 配置）
        const config = await loadConfigPage();
        
        // 先绑定不依赖接口的全局事件，再判断是否已经完成首次设置
        bindGlobalEvents();
        
        // 检查认证状态并显示提示
        const authConfigured = await checkAuthStatus(config);
        if (authConfigured === false) {
            console.log('[initPage] 首次设置模式，仅保留配置页和提示弹窗');
            return;
        }

        // 加载站点列表
        await window.loadSites();
        
        // 加载日志
        await refreshLogs();
        
        // 检查 qB 状态
        await checkQBStatus();
        
        // 刷新统计信息
        await refreshStats();
        
        // 加载版本号
        await loadAppVersion();
        
        // 默认开启日志自动刷新
        const checkbox = document.getElementById('logAutoRefresh');
        if (checkbox && checkbox.checked) {
            startLogAutoRefresh(3000);
            const indicator = document.getElementById('logAutoRefreshIndicator');
            setElementHidden(indicator, false);
        }
        
        // 启动统计信息自动刷新（每 5 秒）
        setInterval(refreshStats, 5000);
        
        showToast('页面加载完成', 'success');
    } catch (error) {
        console.error('初始化页面失败:', error);
        showToast('初始化失败：' + error.message, 'error');
    }
}

// ==================== 配置管理 ====================

/**
 * 加载配置到页面
 */
async function loadConfigPage() {
    try {
        const config = await loadConfig();
        window._appConfig = config;
        
        const qb = getQBConfig(config);
        
        // qBittorrent 配置
        document.getElementById('qbHost').value = qb.host || '';
        document.getElementById('qbUsername').value = qb.username || '';
        // 安全：不直接显示密码，使用占位符
        const passwordField = document.getElementById('qbPassword');
        if (passwordField) {
            passwordField.value = '';
            passwordField.placeholder = qb.configured ? '******** (密码已保存，留空不修改)' : '请输入密码';
        }
        document.getElementById('savePath').value = qb.save_path || '';
        
        // 密钥改为只读写，不再从配置接口回填明文
        const authConfigured = Boolean(config?.app?.auth_configured);
        const secretSource = config?.app?.secret_source || 'file';
        const systemAppSecretField = document.getElementById('systemAppSecret');
        if (systemAppSecretField) {
            systemAppSecretField.value = '';
            systemAppSecretField.placeholder = secretSource === 'env'
                ? '当前由 APP_SECRET 环境变量管理，页面修改不会生效'
                : (authConfigured ? '留空不修改，输入新密钥后保存' : '请先设置 API 认证密钥');
        }
        
        // 注意：过滤规则和运行设置现在是站点级别的
        // 不再在这里加载全局配置，而是从各个站点的配置中读取
        
        // 自动下载设置（从 localStorage 读取）
        const savedAutoDownload = localStorage.getItem('autoDownload');
        if (document.getElementById('autoDownload')) {
            document.getElementById('autoDownload').checked = savedAutoDownload !== 'false';
        }

        return config;
        
    } catch (e) {
        console.error('Load config error:', e);
        throw e;
    }
}

// ==================== Toast 通知 ====================

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    const icon = document.getElementById('toastIcon');
    const msg = document.getElementById('toastMessage');
    const iconMap = {
        success: '✓',
        error: '✕',
        warning: '!',
        info: 'i'
    };
    
    toast.className = 'toast ' + type;
    icon.textContent = iconMap[type] || iconMap.info;
    msg.textContent = message;
    toast.classList.add('show');
    
    // 5 秒后自动隐藏
    setTimeout(() => toast.classList.remove('show'), 5000);
}

// 导出到全局，供其他 JS 文件使用
window.showToast = showToast;

// Toast 点击复制功能
document.addEventListener('DOMContentLoaded', function() {
    const toast = document.getElementById('toast');
    if (toast) {
        toast.addEventListener('click', function() {
            const msg = document.getElementById('toastMessage');
            const text = msg.textContent;
            
            navigator.clipboard.writeText(text).then(() => {
                // 显示复制成功提示
                const originalText = msg.textContent;
                msg.textContent = '已复制到剪贴板 ✓';
                setTimeout(() => {
                    msg.textContent = originalText;
                }, 1500);
            }).catch(err => {
                console.error('复制失败:', err);
            });
        });
    }
});

// ==================== 自定义确认对话框 ====================

/**
 * 关闭确认对话框（桥接到全局函数）
 */
function closeConfirmModal() {
    window.closeConfirmModal();
}

// 确认按钮点击事件 - 使用全局 confirmModalAction
document.addEventListener('DOMContentLoaded', function() {
    const confirmBtn = document.getElementById('confirmBtn');
    if (confirmBtn) {
        confirmBtn.addEventListener('click', function() {
            // 调用全局的确认操作函数
            if (typeof window.confirmModalAction === 'function') {
                window.confirmModalAction();
            }
        });
    }
    
    // ESC 键关闭对话框
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            const recoveryResetModal = document.getElementById('recoveryResetModal');
            if (recoveryResetModal?.classList.contains('show')) {
                closeRecoveryResetModal();
                return;
            }
            const modal = document.getElementById('confirmModal');
            if (modal.classList.contains('show')) {
                window.closeConfirmModal();
            }
        }
    });
});

// ==================== qBittorrent 状态 ====================

async function checkQBStatus() {
    try {
        const data = await getQBStatus();
        const dot = document.getElementById('qbStatus');
        const text = document.getElementById('qbStatusText');
        const version = document.getElementById('qbVersion');
        
        if (data.connected) {
            dot.classList.add('active');
            text.textContent = 'qBittorrent 已连接';
            const ver = data.version || '?';
            version.textContent = ver.startsWith('v') ? ver : 'v' + ver;
        } else {
            dot.classList.remove('active');
            text.textContent = 'qBittorrent 未连接';
            version.textContent = '-';
        }
    } catch (e) {
        console.error('Check QB status error:', e);
    }
}

async function handleTestQBConnection() {
    console.log('handleTestQBConnection called');
    const host = document.getElementById('qbHost').value;
    const username = document.getElementById('qbUsername').value;
    const passwordField = document.getElementById('qbPassword');
    const password = passwordField?.value || '';
    const qbConfigured = Boolean(window._appConfig?.qbittorrent?.configured);
    console.log('QB config:', { host, username });
    
    try {
        console.log('Calling testQBConnection API...');
        const payload = { host, username };
        if (password || !qbConfigured) {
            payload.password = password;
        }
        const result = await testQBConnection(payload);
        console.log('API result:', result);
        showToast(result.message || '连接成功', result.success ? 'success' : 'error');
    } catch (e) {
        console.error('API error:', e);
        showToast('连接失败：' + e.message, 'error');
    }
}

function normalizeSystemLogLevel(level) {
    const normalized = String(level || '').trim().toUpperCase();
    return ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].includes(normalized) ? normalized : 'INFO';
}

function getSystemLogLevel(config = null) {
    const source = config || window._appConfig || {};
    return normalizeSystemLogLevel(source?.logging?.level || source?.log_level || 'INFO');
}

function syncSystemLogLevelUI(level) {
    const normalized = normalizeSystemLogLevel(level);
    const checkbox = document.getElementById('systemDebugLogging');
    const badge = document.getElementById('systemLogLevelBadge');

    if (checkbox) {
        checkbox.checked = normalized === 'DEBUG';
    }
    if (badge) {
        badge.textContent = normalized;
    }
}

function handleSystemLogLevelChange() {
    const checkbox = document.getElementById('systemDebugLogging');
    const badge = document.getElementById('systemLogLevelBadge');
    const level = checkbox?.checked ? 'DEBUG' : 'INFO';

    if (badge) {
        badge.textContent = level;
    }
}

// ==================== 系统设置 ====================

/**
 * 切换系统设置滑出面板
 */
function toggleSystemPanel() {
    return togglePanel('system', () => {
        loadSystemConfig();
    });
}

/**
 * 加载系统配置
 */
async function loadSystemConfig() {
    try {
        console.log('[SystemConfig] 开始加载配置，token:', window.apiConfig?.token ? '已设置' : '未设置');
        const config = await loadConfig();
        window._appConfig = config;
        console.log('[SystemConfig] 加载到的配置:', config?.app);
        
        // 密钥改为只读写，不再从配置接口回填明文
        const authConfigured = Boolean(config?.app?.auth_configured);
        const secretSource = config?.app?.secret_source || 'file';
        const systemAppSecretField = document.getElementById('systemAppSecret');
        
        if (systemAppSecretField) {
            systemAppSecretField.value = '';
            systemAppSecretField.placeholder = secretSource === 'env'
                ? '当前由 APP_SECRET 环境变量管理，页面修改不会生效'
                : (authConfigured ? '留空不修改，输入新密钥后保存' : '请先设置 API 认证密钥');
            console.log('[SystemConfig] 密钥输入框已清空');
        }
        
        // 加载访问控制配置
        const accessMode = normalizeAccessModeValue(config?.app?.access_control || 'lan');
        const allowedIPs = setCurrentWhitelistIPs(config?.app?.allowed_ips || []);
        
        const accessModeRadios = document.querySelectorAll('input[name="accessMode"]');
        let matchedRadio = false;
        accessModeRadios.forEach(radio => {
            if (radio.value === accessMode) {
                radio.checked = true;
                matchedRadio = true;
            }
        });
        if (!matchedRadio) {
            const defaultRadio = document.querySelector('input[name="accessMode"][value="lan"]');
            if (defaultRadio) {
                defaultRadio.checked = true;
            }
        }
        
        // 更新白名单显示
        updateWhitelistCountUI(allowedIPs);
        
        // 调用 handleAccessModeChange 更新界面显示
        handleAccessModeChangeGlobal();
        
        // 加载 Web 端口配置
        const webPort = config?.app?.web_port || 5000;
        const webPortInput = document.getElementById('webPort');
        const currentPortDisplay = document.getElementById('currentPort');
        
        if (webPortInput) {
            webPortInput.value = webPort;
        }
        if (currentPortDisplay) {
            currentPortDisplay.textContent = window.location.port || '5000';
        }

        syncSystemLogLevelUI(getSystemLogLevel(config));
        
        console.log('[SystemConfig] 访问控制模式:', accessMode);
        
    } catch (error) {
        // 如果是认证失败，显示提示
        if (error.message && error.message.includes('未授权')) {
            const systemAppSecretField = document.getElementById('systemAppSecret');
            if (systemAppSecretField) {
                systemAppSecretField.value = '';
                systemAppSecretField.placeholder = '请先设置 API 认证密钥';
            }
            console.warn('[SystemConfig] 认证失败，无法加载密钥');
        } else {
            console.error('[SystemConfig] 加载系统配置失败:', error);
        }
    }
}

/**
 * 保存系统配置
 */
async function saveSystemConfig(portOverride, options = {}) {
    const statusEl = document.getElementById('saveSystemStatus');
    const saveButton = document.getElementById('saveSystemConfigBtn');
    const appSecret = document.getElementById('systemAppSecret')?.value || '';
    const username = document.getElementById('systemUsername')?.value || '';
    const password = document.getElementById('systemPassword')?.value || '';
    const { silentSuccess = false, silentRestartHint = false, autoClosePanel = false } = options;
    const trimmedSecret = appSecret.trim();
    const secretEntered = trimmedSecret !== '';
    const previousWebPort = window._appConfig?.app?.web_port || getCachedConfig()?.app?.web_port || 5000;
    const debugLoggingEnabled = Boolean(document.getElementById('systemDebugLogging')?.checked);
    const logLevel = debugLoggingEnabled ? 'DEBUG' : 'INFO';
    
    // 获取访问控制配置
    const accessModeRadio = document.querySelector('input[name="accessMode"]:checked');
    const accessMode = normalizeAccessModeValue(accessModeRadio ? accessModeRadio.value : 'lan');
    const allowedIPs = getCurrentWhitelistIPs();
    
    // 获取 Web 端口配置
    const webPortInput = document.getElementById('webPort');
    const webPort = portOverride ?? (webPortInput?.value ? parseInt(webPortInput.value, 10) : 5000);
    
    // 验证端口
    if (webPort < 1 || webPort > 65535) {
        showToast('端口号必须在 1-65535 之间', 'error');
        return null;
    }
    
    setPanelStatus(statusEl, '正在保存系统配置...', 'muted');
    showToast('正在保存系统配置...', 'info');
    setButtonLoadingState(saveButton, true);
    
    try {
        // 优先使用当前页面/缓存中的配置，避免保存前再次请求导致体验卡顿。
        let configData = cloneConfigData(window._appConfig || getCachedConfig() || {});
        
        if (!configData || Object.keys(configData).length === 0) {
            try {
                configData = await loadConfig() || {};
            } catch (e) {
                // 记录错误但继续
                console.warn('无法加载现有配置，将仅保存提供的字段:', e.message);
                
                // 如果是认证错误，提示用户
                if (e.message && e.message.includes('未授权')) {
                    showToast('认证失败，将仅保存 API 密钥。刷新后其他配置可能恢复。', 'warning');
                }
            }
        }

        const originalConfig = cloneConfigData(configData);
        
        // 确保配置对象结构完整
        if (!configData.app) configData.app = {};
        
        // 密钥改为只在用户输入新值时写回
        if (secretEntered) {
            configData.app.secret = trimmedSecret;
        }
        
        // 添加访问控制配置
        configData.app.access_control = accessMode;
        if (accessMode === 'whitelist') {
            configData.app.allowed_ips = allowedIPs;
        } else {
            configData.app.allowed_ips = [];
        }
        
        // 添加 Web 端口配置
        configData.app.web_port = webPort;

        if (!configData.logging || typeof configData.logging !== 'object') {
            configData.logging = {};
        }
        configData.logging.level = logLevel;
        configData.log_level = logLevel;
        
        // 添加用户名和密码（预留未来使用）
        if (username && username.trim() !== '') {
            configData.app.username = username.trim();
        }
        if (password && password.trim() !== '') {
            configData.app.password = password.trim();
        }

        if (areConfigsEquivalent(originalConfig, configData)) {
            setPanelStatus(statusEl, '当前配置未改动，无需保存', 'warning');
            showToast('系统设置未改动，无需保存', 'info');
            setTimeout(() => {
                setPanelStatus(statusEl, '');
            }, 5000);
            return {
                success: true,
                skipped: true,
                noChanges: true,
                config: originalConfig,
            };
        }
        
        const result = await saveConfigData(configData);
        const savedConfig = result?.config || configData;
        window._appConfig = savedConfig;
        syncSystemLogLevelUI(getSystemLogLevel(savedConfig));
        
        if (result.success) {
            setPanelStatus(statusEl, '系统配置已保存', 'success');
            const systemPanel = document.getElementById('systemSlidePanel');
            if (autoClosePanel && systemPanel?.classList.contains('open') && typeof toggleSystemPanel === 'function') {
                toggleSystemPanel();
            }
            if (!silentSuccess) {
                showToast(result?.recovery_code ? '系统配置已保存，恢复码已生成' : '系统配置已保存', 'success');
            }
            
            let shouldReloadAfterSecretSave = false;
            // 只有输入了新密钥时，才更新 token 并刷新页面。
            if (secretEntered) {
                try {
                    const sessionToken = result?.auth?.session_token || await exchangeAuthToken(trimmedSecret);
                    if (sessionToken) {
                        window.setAuthToken(sessionToken);
                        console.log('[SystemConfig] 会话 token 已更新');
                        shouldReloadAfterSecretSave = true;
                    } else {
                        showToast('API 密钥已保存，但会话 token 未更新', 'warning');
                    }
                } catch (tokenError) {
                    console.warn('[SystemConfig] 会话 token 更新失败:', tokenError);
                    showToast('API 密钥已保存，但会话 token 更新失败', 'warning');
                }
            } else if (webPort && webPort !== previousWebPort && !silentRestartHint) {
                // 如果修改了端口，显示重启提示
                showToast(`端口已修改为 ${webPort}，请手动重启服务`, 'info');
            }

            if (result?.recovery_code) {
                showRecoveryCodeModal(result.recovery_code, {
                    secret: trimmedSecret,
                    title: secretEntered ? '重要：新密钥和恢复码已生成' : '重要：恢复码已更新',
                    intro: result?.recovery_code_sent
                        ? '重要：新的 API 密钥和恢复码只显示一次，已尝试发送到邮箱，但仍建议你离线保存一份。'
                        : '重要：新的 API 密钥和恢复码只显示一次。请至少完成一项：配置邮箱通知备份，或者离线保存并牢记恢复码。',
                    hint: result?.recovery_code_sent
                        ? '如果你还没有邮箱备份，现在就把新的 API 密钥和恢复码保存到本地或离线介质。'
                        : '新的 API 密钥和恢复码只会显示这一次。请立即复制并离线保存。',
                    confirmText: '我已保存，继续',
                    onConfirm: () => {
                        if (shouldReloadAfterSecretSave) {
                            window.location.reload();
                        }
                    },
                });
            } else if (shouldReloadAfterSecretSave) {
                showToast('API 密钥已更新，页面将自动刷新...', 'info');
                setTimeout(() => {
                    window.location.reload();
                }, 1000);
            }

            if (result?.recovery_code_sent) {
                showToast('恢复码已发送到邮箱', 'success');
            } else if (result?.recovery_code_send_error) {
                showToast('恢复码邮件发送失败：' + result.recovery_code_send_error, 'warning');
            }
            
            // 3 秒后清除状态
            setTimeout(() => {
                setPanelStatus(statusEl, '');
            }, 6000);
            return result;
        } else {
            setPanelStatus(statusEl, `保存失败：${result.message}`, 'error');
            showToast('保存失败：' + result.message, 'error');
            return result;
        }
    } catch (e) {
        setPanelStatus(statusEl, `保存错误：${e.message}`, 'error');
        showToast('保存错误：' + e.message, 'error');
        return null;
    } finally {
        setButtonLoadingState(saveButton, false);
    }
}

function getNotificationConfigFromForm(existingConfig = {}) {
    const downloadStartEnabled = Boolean(document.getElementById('notifyDownloadStartEnabled')?.checked);
    const downloadCompleteEnabled = Boolean(document.getElementById('notifyDownloadCompleteEnabled')?.checked);
    const smtpHost = document.getElementById('notifySmtpHost')?.value.trim() || '';
    const smtpPortInput = document.getElementById('notifySmtpPort');
    const smtpPort = smtpPortInput?.value ? parseInt(smtpPortInput.value, 10) : 0;
    const transportMode = document.getElementById('notifyTransportMode')?.value || inferTransportModeFromPort(smtpPort || 0);
    const senderEmail = document.getElementById('notifySenderEmail')?.value.trim() || '';
    const senderName = document.getElementById('notifySenderName')?.value.trim() || '';
    const smtpPassword = document.getElementById('notifySmtpPassword')?.value || '';
    const recipientEmail = document.getElementById('notifyRecipientEmail')?.value.trim() || '';

    const notifications = cloneConfigData(existingConfig || {});
    notifications.download_start_enabled = downloadStartEnabled;
    notifications.download_complete_enabled = downloadCompleteEnabled;
    notifications.enabled = downloadStartEnabled || downloadCompleteEnabled;
    notifications.smtp_host = smtpHost;
    notifications.smtp_port = Number.isFinite(smtpPort) && smtpPort > 0 ? smtpPort : 0;
    notifications.transport_mode = transportMode;
    notifications.sender_email = senderEmail;
    notifications.sender_name = senderName;
    notifications.recipient_email = recipientEmail;

    if (smtpPassword.trim()) {
        notifications.smtp_password = smtpPassword.trim();
    } else if (!notifications.configured) {
        delete notifications.smtp_password;
    } else {
        delete notifications.smtp_password;
    }

    return notifications;
}

function applyNotificationConfigToForm(config) {
    const notificationConfig = config?.notifications || {};
    const downloadStartCheckbox = document.getElementById('notifyDownloadStartEnabled');
    const downloadCompleteCheckbox = document.getElementById('notifyDownloadCompleteEnabled');
    const smtpHostInput = document.getElementById('notifySmtpHost');
    const smtpPortInput = document.getElementById('notifySmtpPort');
    const transportSelect = document.getElementById('notifyTransportMode');
    const senderEmailInput = document.getElementById('notifySenderEmail');
    const senderNameInput = document.getElementById('notifySenderName');
    const passwordInput = document.getElementById('notifySmtpPassword');
    const recipientInput = document.getElementById('notifyRecipientEmail');
    const { downloadStartEnabled, downloadCompleteEnabled } = getNotificationEventStates(notificationConfig);

    if (downloadStartCheckbox) {
        downloadStartCheckbox.checked = downloadStartEnabled;
    }
    if (downloadCompleteCheckbox) {
        downloadCompleteCheckbox.checked = downloadCompleteEnabled;
    }
    if (smtpHostInput) {
        smtpHostInput.value = notificationConfig.smtp_host || '';
    }
    if (smtpPortInput) {
        const transportMode = notificationConfig.transport_mode || inferTransportModeFromPort(notificationConfig.smtp_port || 0);
        smtpPortInput.value = notificationConfig.smtp_port || getDefaultSmtpPortForTransport(transportMode);
    }
    if (transportSelect) {
        transportSelect.value = notificationConfig.transport_mode || inferTransportModeFromPort(notificationConfig.smtp_port || 0);
    }
    if (senderEmailInput) {
        senderEmailInput.value = notificationConfig.sender_email || '';
    }
    if (senderNameInput) {
        senderNameInput.value = notificationConfig.sender_name || '';
    }
    if (recipientInput) {
        recipientInput.value = notificationConfig.recipient_email || '';
    }
    if (passwordInput) {
        passwordInput.value = '';
        passwordInput.placeholder = notificationConfig.configured
            ? '******** (已保存，留空不修改)'
            : '请输入 SMTP 授权码 / 密码';
    }
}

async function loadNotificationConfig() {
    try {
        const config = window._appConfig || await loadConfig();
        window._appConfig = config;
        applyNotificationConfigToForm(config);
        updateNotificationStatusUI(config?.notifications || {});
        return config;
    } catch (e) {
        console.error('[NotificationConfig] 加载失败:', e);
        showToast('加载邮件通知配置失败：' + e.message, 'error');
        throw e;
    }
}

function updateNotificationStatusUI(notificationConfig = {}) {
    const statusEl = document.getElementById('saveNotificationStatus');
    if (!statusEl) {
        return;
    }

    const { downloadStartEnabled, downloadCompleteEnabled } = getNotificationEventStates(notificationConfig);
    const anyEventEnabled = downloadStartEnabled || downloadCompleteEnabled;

    if (notificationConfig.configured) {
        setPanelStatus(
            statusEl,
            anyEventEnabled ? '邮件通知配置已就绪' : '邮件通知配置已保存，事件通知未启用',
            anyEventEnabled ? 'success' : 'warning'
        );
    } else if (anyEventEnabled) {
        setPanelStatus(statusEl, '邮件通知已选中，但配置尚未完成', 'warning');
    } else {
        setPanelStatus(statusEl, '邮件通知尚未启用', 'muted');
    }
}

function toggleNotificationPanel() {
    if (!window._appConfig?.app?.auth_configured) {
        showToast('请先设置 API 认证密钥', 'warning');
        return false;
    }

    return togglePanel('notify', () => {
        return loadNotificationConfig();
    });
}

async function saveNotificationConfig() {
    const statusEl = document.getElementById('saveNotificationStatus');
    const saveButton = document.getElementById('saveNotificationBtn');
    const currentConfig = cloneConfigData(window._appConfig || getCachedConfig() || {});
    const originalConfig = cloneConfigData(currentConfig);

    if (!currentConfig.notifications) {
        currentConfig.notifications = {};
    }

    const notificationConfig = getNotificationConfigFromForm(currentConfig.notifications);
    const existingConfigured = Boolean(currentConfig.notifications?.configured);
    const passwordProvided = Boolean(document.getElementById('notifySmtpPassword')?.value.trim());

    if (!notificationConfig.smtp_host) {
        setPanelStatus(statusEl, '请输入 SMTP 服务器', 'error');
        showToast('请输入 SMTP 服务器', 'error');
        return null;
    }
    if (!notificationConfig.sender_email) {
        setPanelStatus(statusEl, '请输入发件邮箱', 'error');
        showToast('请输入发件邮箱', 'error');
        return null;
    }
    if (!notificationConfig.recipient_email) {
        setPanelStatus(statusEl, '请输入收件邮箱', 'error');
        showToast('请输入收件邮箱', 'error');
        return null;
    }
    if (!existingConfigured && !passwordProvided) {
        setPanelStatus(statusEl, '首次配置时必须填写 SMTP 授权码 / 密码', 'error');
        showToast('首次配置时必须填写 SMTP 授权码 / 密码', 'error');
        return null;
    }

    currentConfig.notifications = notificationConfig;

    if (areConfigsEquivalent(originalConfig, currentConfig)) {
        setPanelStatus(statusEl, '邮件通知配置未改动，无需保存', 'warning');
        showToast('邮件通知配置未改动，无需保存', 'info');
        setTimeout(() => {
            setPanelStatus(statusEl, '');
        }, 4000);
        return {
            success: true,
            skipped: true,
            noChanges: true,
            config: originalConfig,
        };
    }

    setPanelStatus(statusEl, '正在保存邮件通知配置...', 'muted');
    showToast('正在保存邮件通知配置...', 'info');
    setButtonLoadingState(saveButton, true);

    try {
        const result = await saveConfigData(currentConfig);
        const savedConfig = result?.config || currentConfig;
        window._appConfig = savedConfig;

        if (result.success) {
            applyNotificationConfigToForm(savedConfig);
            updateNotificationStatusUI(savedConfig.notifications || {});
            setPanelStatus(statusEl, '邮件通知配置已保存', 'success');
            showToast('邮件通知配置已保存', 'success');
            return result;
        }

        setPanelStatus(statusEl, `保存失败：${result.message}`, 'error');
        showToast('保存失败：' + result.message, 'error');
        return result;
    } catch (e) {
        setPanelStatus(statusEl, `保存错误：${e.message}`, 'error');
        showToast('保存错误：' + e.message, 'error');
        return null;
    } finally {
        setButtonLoadingState(saveButton, false);
    }
}

async function testNotificationEmail() {
    const saveButton = document.getElementById('testNotificationBtn');
    const statusEl = document.getElementById('saveNotificationStatus');
    const currentConfig = cloneConfigData(window._appConfig || getCachedConfig() || {});
    if (!currentConfig.notifications) {
        currentConfig.notifications = {};
    }

    const notificationConfig = getNotificationConfigFromForm(currentConfig.notifications);
    const passwordProvided = Boolean(document.getElementById('notifySmtpPassword')?.value.trim());

    if (!notificationConfig.smtp_host || !notificationConfig.sender_email || !notificationConfig.recipient_email) {
        showToast('请先填写完整的邮件通知配置', 'warning');
        return null;
    }
    if (!passwordProvided && !currentConfig.notifications?.configured) {
        showToast('请先填写 SMTP 授权码 / 密码', 'warning');
        return null;
    }

    setPanelStatus(statusEl, '正在发送测试邮件...', 'muted');
    showToast('正在发送测试邮件...', 'info');
    setButtonLoadingState(saveButton, true, '发送中...');

    try {
        const result = await apiPost('/api/notifications/test', {
            notifications: notificationConfig,
            subject: 'Auto PT 邮件通知测试',
            message: '这是一封来自 Auto PT Downloader 的测试邮件，用于验证邮件通知配置是否可用。',
        });

        if (result.success) {
            setPanelStatus(statusEl, '测试邮件已发送', 'success');
            showToast(result.message || '测试邮件已发送', 'success');
        } else {
            setPanelStatus(statusEl, `测试失败：${result.message}`, 'error');
            showToast('测试失败：' + result.message, 'error');
        }
        return result;
    } catch (e) {
        setPanelStatus(statusEl, `测试错误：${e.message}`, 'error');
        showToast('测试错误：' + e.message, 'error');
        return null;
    } finally {
        setButtonLoadingState(saveButton, false, '发送中...');
    }
}

function handleSystemConfigSave(event) {
    if (event) {
        event.preventDefault();
    }
    return saveSystemConfig(undefined, { autoClosePanel: true });
}

function handleNotificationConfigSave(event) {
    if (event) {
        event.preventDefault();
    }
    return saveNotificationConfig();
}

/**
 * 生成随机 API 密钥
 */
function generateRandomSecret(targetInput = 'systemAppSecret') {
    const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_'
    const length = 32
    let randomSecret = ''
    
    // 使用 crypto API 生成更安全的随机数
    if (window.crypto && window.crypto.getRandomValues) {
        const array = new Uint32Array(length)
        window.crypto.getRandomValues(array)
        for (let i = 0; i < length; i++) {
            randomSecret += chars[array[i] % chars.length]
        }
    } else {
        // 降级方案
        for (let i = 0; i < length; i++) {
            randomSecret += chars.charAt(Math.floor(Math.random() * chars.length))
        }
    }
    
    // 填充到输入框
    const input = typeof targetInput === 'string'
        ? document.getElementById(targetInput)
        : targetInput
    if (input) {
        input.value = randomSecret
        input.placeholder = '已生成随机密钥'
        if (typeof input.focus === 'function') {
            input.focus()
        }
        if (typeof input.select === 'function') {
            input.select()
        }
    }
    
    showToast('已生成随机密钥', 'success')
}

/**
 * 保存 Web 端口设置
 */
async function saveWebPort() {
    const portInput = document.getElementById('webPort');
    const port = portInput.value.trim();
    
    // 验证端口
    if (!port) {
        showToast('请输入端口号', 'warning');
        return;
    }
    
    const portNum = parseInt(port);
    if (isNaN(portNum) || portNum < 1 || portNum > 65535) {
        showToast('端口号必须在 1-65535 之间', 'error');
        return;
    }
    
    // 获取当前显示的端口（旧端口）
    const oldPort = document.getElementById('currentPort')?.textContent || '5000';

    // 存储临时数据，等待用户确认
    window._pendingPortChange = {
        newPort: portNum,
        oldPort: oldPort
    };

    // 显示确认模态框，密钥不再明文展示
    showPortChangeModal(portNum, oldPort, '');
}

// ==================== 日志管理 ====================

async function refreshLogs() {
    try {
        // 如果正在自动刷新，则不手动刷新
        if (isLogAutoRefreshEnabled()) {
            showToast('自动刷新已开启，无需手动刷新', 'info');
            return;
        }
        
        const logs = await loadLogs();
        window._logCache = logs;
        applyLogFilters('logContainer', logs);
    } catch (e) {
        console.error('Refresh logs error:', e);
    }
}

/**
 * 切换日志自动刷新
 */
function toggleLogAutoRefresh() {
    const checkbox = document.getElementById('logAutoRefresh');
    const indicator = document.getElementById('logAutoRefreshIndicator');
    if (!checkbox) return;
    
    if (checkbox.checked) {
        startLogAutoRefresh(3000);
        setElementHidden(indicator, false);
        showToast('已开启日志自动刷新 (3 秒)', 'success');
    } else {
        stopLogAutoRefresh();
        setElementHidden(indicator, true);
        showToast('已关闭日志自动刷新', 'info');
    }
}

async function clearLogs() {
    showConfirmModal(
        '🗑️ 清除确认',
        '确定清除所有日志？',
        '清除后日志文件将被清空，此操作不可恢复。',
        async function() {
            try {
                await clearAllLogs();
                _logCache = '';
                applyLogFilters('logContainer', '');
                showToast('日志已清除', 'success');
            } catch (e) {
                showToast('清除失败：' + e.message, 'error');
            }
        }
    );
}

function applyLogFiltersUI() {
    const level = document.getElementById('logLevelFilter').value;
    const module = document.getElementById('logModuleFilter').value;
    const keyword = document.getElementById('logKeywordFilter').value;
    setLogFilters(level, module, keyword);
    const logs = window._logCache || '';
    applyLogFilters('logContainer', logs);
}

function copyLogs() {
    const container = document.getElementById('logContainer');
    if (!container) return;
    
    const text = container.innerText;
    navigator.clipboard.writeText(text).then(() => {
        showToast('日志已复制到剪贴板', 'success');
    }).catch(err => {
        showToast('复制失败：' + err.message, 'error');
    });
}

/**
 * 确认清除历史记录
 */
function confirmClearHistory() {
    showConfirmModal(
        '🗑️ 清除确认',
        '确定清除所有历史记录？',
        '清除后已下载的种子的记录将被删除，允许重新下载。',
        function() {
            clearAllHistory(0).then(() => {
                showToast('历史记录已清除', 'success');
                // 刷新统计信息
                refreshStats();
            }).catch(err => {
                showToast('清除失败：' + err.message, 'error');
            });
        }
    );
}

// ==================== 种子预览和下载 ====================

const SITE_MANAGEMENT_MODAL_IDS = ['siteModal', 'configModal', 'filterModal', 'previewModal'];
const SITE_MANAGEMENT_DIRTY_MODAL_IDS = ['siteModal', 'configModal', 'filterModal'];
const siteManagementModalTitles = {
    siteModal: '站点编辑',
    configModal: '站点配置',
    filterModal: '站点过滤',
    previewModal: '种子预览'
};
const siteManagementModalSnapshots = {};

function getSiteModalState(modalId) {
    switch (modalId) {
        case 'siteModal':
            return {
                siteName: document.getElementById('siteName')?.value || '',
                rssUrl: document.getElementById('siteRssUrl')?.value || '',
                baseUrl: document.getElementById('siteBaseUrl')?.value || '',
                passkey: document.getElementById('sitePasskey')?.value || '',
                uid: document.getElementById('siteUid')?.value || '',
                tags: document.getElementById('siteTags')?.value || ''
            };
        case 'configModal':
            return {
                interval: document.getElementById('configInterval')?.value || '',
                cleanupInterval: document.getElementById('configCleanupInterval')?.value || '',
                pauseAdded: !!document.getElementById('configPauseAdded')?.checked,
                autoDelete: !!document.getElementById('configAutoDelete')?.checked,
                deleteFiles: !!document.getElementById('configDeleteFiles')?.checked,
                autoDownload: !!document.getElementById('configAutoDownload')?.checked
            };
        case 'filterModal':
            return {
                keywords: document.getElementById('filterKeywords')?.value || '',
                exclude: document.getElementById('filterExclude')?.value || '',
                minSize: document.getElementById('filterMinSize')?.value || '',
                maxSize: document.getElementById('filterMaxSize')?.value || ''
            };
        default:
            return null;
    }
}

function serializeSiteModalState(modalId) {
    const state = getSiteModalState(modalId);
    return state ? JSON.stringify(state) : '';
}

function isSiteManagementModalDirty(modalId) {
    if (!SITE_MANAGEMENT_DIRTY_MODAL_IDS.includes(modalId)) {
        return false;
    }

    if (!(modalId in siteManagementModalSnapshots)) {
        return false;
    }

    return siteManagementModalSnapshots[modalId] !== serializeSiteModalState(modalId);
}

window.captureSiteManagementModalState = function(modalId) {
    if (!SITE_MANAGEMENT_DIRTY_MODAL_IDS.includes(modalId)) {
        return;
    }

    siteManagementModalSnapshots[modalId] = serializeSiteModalState(modalId);
};

window.clearSiteManagementModalState = function(modalId) {
    delete siteManagementModalSnapshots[modalId];
};

async function askDiscardSiteManagementChanges(modalId, reason = '切换') {
    const title = siteManagementModalTitles[modalId] || '当前弹窗';
    return window.askConfirmModal(
        '放弃未保存内容？',
        `当前${title}里还有未保存的修改。`,
        `继续${reason}会丢失刚才的内容。`,
        '继续',
        '返回编辑'
    );
}

window.closeSiteManagementModal = async function(modalId, options = {}) {
    const { force = false, reason = '关闭' } = options;
    const modal = document.getElementById(modalId);
    if (!modal || !modal.classList.contains('show')) {
        window.clearSiteManagementModalState(modalId);
        return true;
    }

    if (!force && isSiteManagementModalDirty(modalId)) {
        const confirmed = await askDiscardSiteManagementChanges(modalId, reason);
        if (!confirmed) {
            return false;
        }
    }

    modal.classList.remove('show');
    window.clearSiteManagementModalState(modalId);
    return true;
};

window.closeSiteManagementModals = async function(exceptId = null, options = {}) {
    for (const modalId of SITE_MANAGEMENT_MODAL_IDS) {
        if (modalId === exceptId) {
            continue;
        }

        const closed = await window.closeSiteManagementModal(modalId, options);
        if (!closed) {
            return false;
        }
    }

    return true;
};

window.beforeOpenSiteManagementModal = async function(targetModalId) {
    const targetModal = document.getElementById(targetModalId);
    if (targetModal?.classList.contains('show')) {
        const closedTarget = await window.closeSiteManagementModal(targetModalId, {
            force: false,
            reason: '切换'
        });
        if (!closedTarget) {
            return false;
        }
    }

    return window.closeSiteManagementModals(targetModalId, {
        force: false,
        reason: '切换'
    });
};

/**
 * 显示预览模态框（加载状态）
 * 先打开模态框显示加载动画，数据返回后再填充内容
 */
function getPreviewLoadingMarkup() {
    return `
        <div class="modal-loading-state">
            <div class="modal-loading-spinner"></div>
            <p class="modal-loading-title">🔄 正在刷新 RSS，请稍候...</p>
            <p class="modal-loading-hint">(首次加载可能需要几秒)</p>
        </div>
    `;
}

async function showPreviewModalLoading() {
    const modal = document.getElementById('previewModal');
    const canOpen = await window.beforeOpenSiteManagementModal('previewModal');
    if (!canOpen) {
        return false;
    }

    // 显示加载状态
    const content = document.getElementById('torrentPreviewList');
    content.innerHTML = getPreviewLoadingMarkup();
    
    // 显示模态框（footer 已在 HTML 中定义）
    modal.classList.add('show');
    return true;
}

/**
 * 更新预览缓存并渲染种子列表
 * 数据返回后调用此函数填充内容
 */
function updatePreviewCacheAndRender(data, autoDownload) {
    // 更新预览缓存
    window.updatePreviewCache(data);
    
    // 渲染工具栏和分页（完全按照历史记录布局）
    renderPreviewToolbar();
    
    // 渲染种子列表
    renderPreviewList('torrentPreviewList');
    
    // 如果启用自动下载，自动选中所有新种子
    if (autoDownload) {
        const container = document.getElementById('torrentPreviewList');
        if (container) {
            const newTorrentsSection = container.querySelector('.section-title');
            if (newTorrentsSection) {
                const selectAllBtn = newTorrentsSection.querySelector('.select-all-btn');
                if (selectAllBtn) {
                    selectAllBtn.click();
                }
            }
        }
    }
}

function showPreviewModal(data, autoDownload) {
    const modal = document.getElementById('previewModal');
    
    // 显示加载状态
    const content = document.getElementById('torrentPreviewList');
    content.innerHTML = getPreviewLoadingMarkup();
    
    // 更新预览缓存
    window.updatePreviewCache(data);
    
    // 渲染工具栏和分页（完全按照历史记录布局）
    renderPreviewToolbar();
    
    // 渲染种子列表
    renderPreviewList('torrentPreviewList');
    
    // 显示模态框（footer 已在 HTML 中定义，无需重新渲染）
    modal.classList.add('show');
}

/**
 * 下载选中的种子
 */
async function downloadSelectedTorrents() {
    console.log('=== downloadSelectedTorrents 被调用 ===');
    
    const container = document.getElementById('torrentPreviewList');
    if (!container) {
        console.error('找不到 torrentPreviewList 容器');
        showToast('页面错误：找不到种子列表', 'error');
        return;
    }
    
    const checkboxes = container.querySelectorAll('input[type="checkbox"]:checked');
    console.log('选中的种子:', checkboxes.length);
    console.log('选中的复选框:', Array.from(checkboxes).map(cb => cb.dataset.id));
    
    if (checkboxes.length === 0) {
        showToast('请先勾选要下载的种子', 'warning');
        return;
    }
    
    const selected = Array.from(checkboxes).map(cb => ({
        id: cb.dataset.id,
        title: cb.dataset.title,
        link: cb.dataset.link,
        site_name: cb.dataset.site_name || '',
        category: cb.dataset.category || '',
        size: parseFloat(cb.dataset.size) || 0,
        isDownloaded: cb.dataset.downloaded === 'true'  // 使用 dataset.downloaded 判断
    }));
    
    console.log('准备下载:', selected);
    
    // 检查是否有已下载的种子（需要删除历史记录）
    const needRedownload = selected.filter(s => s.isDownloaded);
    console.log('需要重新下载的种子:', needRedownload);
    
    if (needRedownload.length > 0) {
        const titles = needRedownload.map(s => s.title).join('\n');
        
        showConfirmModal(
            '🔄 重新下载确认',
            `确定要重新下载以下 ${needRedownload.length} 个种子吗？`,
            titles,
            function() {
                // 用户点击确认，开始删除历史记录并下载
                downloadAfterConfirm(selected);
            }
        );
        return;
    } else {
        console.log('没有已下载的种子，直接下载');
    }
    
    // 直接下载
    downloadAfterConfirm(selected);
}

/**
 * 确认后的下载逻辑
 */
async function downloadAfterConfirm(selected) {
    // 先删除需要重新下载的种子的历史记录
    const needRedownload = selected.filter(s => s.isDownloaded);
    
    for (const torrent of needRedownload) {
        try {
            console.log('删除历史记录:', torrent.id);
            const result = await deleteHistory(torrent.id, 'delete');
            if (result.success) {
                console.log('删除成功:', torrent.id);
            } else {
                console.error('删除失败:', torrent.id, result.message);
            }
        } catch (e) {
            console.error('删除历史记录失败:', torrent.id, e);
        }
    }
    
    // 禁用下载按钮
    const downloadBtn = setPreviewDownloadButtonLoadingState(true, '下载中...');
    console.log('下载按钮:', downloadBtn);
    
    try {
        console.log('调用 downloadMultipleTorrents, 数据:', selected);
        
        const result = await downloadMultipleTorrents(selected);
        console.log('下载结果:', result);
        
        if (result.success) {
            showToast(result.message || '下载成功', 'success');
            
            // 更新选中种子状态
            selected.forEach(s => {
                updateTorrentStatus(s.id, true);
            });
            
            // 重新渲染预览列表
            renderPreviewList('torrentPreviewList');
            
            // 更新选中计数
            updateSelectedCountInModal();
            
            // 刷新主页统计
            refreshStats();
        } else {
            showToast(result.message || '下载失败', 'error');
            console.error('下载失败:', result.message);
        }
    } catch (e) {
        showToast('下载失败：' + e.message, 'error');
        console.error('下载异常:', e);
    } finally {
        // 恢复下载按钮
        const restoreBtn = setPreviewDownloadButtonLoadingState(false);
        if (restoreBtn) {
            restoreBtn.disabled = false;
        }
        updateSelectedCountInModal();
    }
}

function closeModal() {
    return window.closeSiteManagementModal('previewModal', {
        force: true,
        reason: '关闭'
    });
}
 
// ==================== 统计信息 ====================

// QB 配置滑出面板
const toggleQBPanel = function() {
    return togglePanel('qb');
};
window.toggleQBPanel = toggleQBPanel;

// 站点管理滑出面板
const toggleSitePanel = async function() {
    return togglePanel('sites', async () => {
        if (typeof window.loadSites === 'function') {
            await window.loadSites();
        }
    });
};
window.toggleSitePanel = toggleSitePanel;

const refreshStats = refreshDashboardStats;
window.refreshStats = refreshStats;

async function loadAppVersion() {
    try {
        const data = await apiGet('/api/version');
        document.getElementById('appVersion').textContent = data.version || '?';
    } catch (e) {
        document.getElementById('appVersion').textContent = '?';
    }
}

window.viewHistory = function() {
    document.getElementById('historyModal').classList.add('show');
    loadHistoryPage();
}

window.closeHistoryModal = function() {
    document.getElementById('historyModal').classList.remove('show');
}

async function loadHistoryPage() {
    try {
        await loadHistory();
    } catch (e) {
        console.error('[main.js] Load history error:', e);
        if (window.showToast) {
            showToast('加载失败：' + e.message, 'error');
        }
    }
}

// 使用 history.js 导出的函数，renderHistoryList 已直接调用
// function renderHistoryPage() { ... }  // 已移除，使用 renderHistoryList 代替

// selectAll 包装函数
function selectAll() {
    const allCheckboxes = document.querySelectorAll('#historyList input[type="checkbox"]');
    const selectAllCheckbox = document.getElementById('selectAllCheckbox');
    const isChecked = selectAllCheckbox?.checked || false;
    
    allCheckboxes.forEach(cb => {
        cb.checked = isChecked;
    });
    updateSelectedCount();
}

// const debouncedSearch = ...   // 已从 history.js 导入

// ==================== 全局事件绑定 ====================

function bindGlobalEvents() {
    // 模态框点击外部关闭
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', async (e) => {
            if (e.target === modal) {
                switch (modal.id) {
                    case 'siteModal':
                        await window.closeSiteModal();
                        break;
                    case 'filterModal':
                        await window.closeFilterModal();
                        break;
                    case 'configModal':
                        await window.closeConfigModal();
                        break;
                    case 'previewModal':
                        await window.closeModal();
                        break;
                    case 'confirmModal':
                        window.closeConfirmModal();
                        break;
                    case 'authTokenModal':
                        window.closeAuthTokenModal();
                        break;
                    case 'historyModal':
                        window.closeHistoryModal();
                        break;
                    case 'recoveryResetModal':
                        closeRecoveryResetModal();
                        break;
                    case 'recoveryCodeModal':
                        break;
                    default:
                        modal.classList.remove('show');
                        break;
                }
            }
        });
    });
    
    // 历史记录复选框变化
    document.getElementById('historyList')?.addEventListener('change', (e) => {
        if (e.target.type === 'checkbox') {
            updateSelectedCount('selectedCount', 'historyList');
        }
    });
    
    // 搜索框 - 使用 oninput 属性直接调用 searchHistoryDynamic（在 index.html 中绑定）
    // 无需额外的事件监听器
}

// ==================== 过滤弹窗相关函数 ====================

const modalSubmitLocks = new Set();

function setModalActionButtonState(button, isLoading, loadingText) {
    if (!button) {
        return;
    }

    if (isLoading) {
        if (!button.dataset.defaultHtml) {
            button.dataset.defaultHtml = button.innerHTML;
        }
        button.disabled = true;
        button.classList.add('is-loading');
        button.innerHTML = `<span class="loading"></span><span>${loadingText}</span>`;
        return;
    }

    button.disabled = false;
    button.classList.remove('is-loading');
    if (button.dataset.defaultHtml) {
        button.innerHTML = button.dataset.defaultHtml;
    }
}

async function runModalSubmitAction(lockKey, button, loadingText, action) {
    if (modalSubmitLocks.has(lockKey)) {
        return false;
    }

    modalSubmitLocks.add(lockKey);
    setModalActionButtonState(button, true, loadingText);

    try {
        await action();
        return true;
    } catch (e) {
        return false;
    } finally {
        modalSubmitLocks.delete(lockKey);
        setModalActionButtonState(button, false, loadingText);
    }
}

/**
 * 过滤规则文本解析与文本域布局
 */
function parseFilterEntriesFromText(text) {
    return String(text || '')
        .split(/[\r\n,，]+/)
        .map(item => item.trim())
        .filter(item => item);
}

function getCachedSiteByName(siteName) {
    const normalizedName = typeof siteName === 'string' ? siteName.trim() : '';
    if (!normalizedName || !Array.isArray(window.sitesData)) {
        return null;
    }

    return window.sitesData.find(site => site && site.name === normalizedName) || null;
}

function applySiteUpdateToCache(siteName, updateData = {}) {
    const site = getCachedSiteByName(siteName);
    if (!site || !updateData || typeof updateData !== 'object') {
        return false;
    }

    if (Object.prototype.hasOwnProperty.call(updateData, 'name') && updateData.name) {
        site.name = updateData.name;
    }
    if (Object.prototype.hasOwnProperty.call(updateData, 'type')) {
        site.type = updateData.type;
    }
    if (Object.prototype.hasOwnProperty.call(updateData, 'base_url')) {
        site.base_url = updateData.base_url;
    }
    if (Object.prototype.hasOwnProperty.call(updateData, 'rss_url')) {
        site.rss_url = updateData.rss_url;
    }
    if (Object.prototype.hasOwnProperty.call(updateData, 'passkey')) {
        site.passkey = updateData.passkey;
    }
    if (Object.prototype.hasOwnProperty.call(updateData, 'uid')) {
        site.uid = updateData.uid;
    }
    if (Object.prototype.hasOwnProperty.call(updateData, 'enabled')) {
        site.enabled = updateData.enabled;
    }
    if (Object.prototype.hasOwnProperty.call(updateData, 'tags')) {
        site.tags = updateData.tags;
    }
    if (Object.prototype.hasOwnProperty.call(updateData, 'interval')) {
        site.interval = updateData.interval;
    }
    if (Object.prototype.hasOwnProperty.call(updateData, 'cleanup_interval')) {
        site.cleanup_interval = updateData.cleanup_interval;
    }
    if (Object.prototype.hasOwnProperty.call(updateData, 'pause_added')) {
        site.pause_added = updateData.pause_added;
        site.download_settings = site.download_settings || {};
        site.download_settings.paused = updateData.pause_added;
    }
    if (Object.prototype.hasOwnProperty.call(updateData, 'auto_delete')) {
        site.auto_delete = updateData.auto_delete;
        site.download_settings = site.download_settings || {};
        site.download_settings.auto_delete = updateData.auto_delete;
    }
    if (Object.prototype.hasOwnProperty.call(updateData, 'delete_files')) {
        site.delete_files = updateData.delete_files;
        site.download_settings = site.download_settings || {};
        site.download_settings.delete_files = updateData.delete_files;
    }
    if (Object.prototype.hasOwnProperty.call(updateData, 'auto_download')) {
        site.auto_download = updateData.auto_download;
        site.download_settings = site.download_settings || {};
        site.download_settings.auto_download = updateData.auto_download;
    }
    if (Object.prototype.hasOwnProperty.call(updateData, 'schedule') && updateData.schedule) {
        site.schedule = { ...(site.schedule || {}), ...updateData.schedule };
        if (Object.prototype.hasOwnProperty.call(updateData.schedule, 'interval')) {
            site.interval = updateData.schedule.interval;
        }
        if (Object.prototype.hasOwnProperty.call(updateData.schedule, 'cleanup_interval')) {
            site.cleanup_interval = updateData.schedule.cleanup_interval;
        }
    }
    if (Object.prototype.hasOwnProperty.call(updateData, 'download_settings') && updateData.download_settings) {
        site.download_settings = { ...(site.download_settings || {}), ...updateData.download_settings };
        if (Object.prototype.hasOwnProperty.call(updateData.download_settings, 'paused')) {
            site.pause_added = updateData.download_settings.paused;
        }
        if (Object.prototype.hasOwnProperty.call(updateData.download_settings, 'auto_delete')) {
            site.auto_delete = updateData.download_settings.auto_delete;
        }
        if (Object.prototype.hasOwnProperty.call(updateData.download_settings, 'delete_files')) {
            site.delete_files = updateData.download_settings.delete_files;
        }
        if (Object.prototype.hasOwnProperty.call(updateData.download_settings, 'auto_download')) {
            site.auto_download = updateData.download_settings.auto_download;
        }
    }
    if (Object.prototype.hasOwnProperty.call(updateData, 'filter') && updateData.filter) {
        site.filter = { ...(site.filter || {}), ...updateData.filter };
    }

    return true;
}

function queueSitePanelRefresh(refreshStats = false) {
    setTimeout(() => {
        const runner = async () => {
            if (typeof window.loadSites === 'function') {
                await window.loadSites();
            }
            if (refreshStats && typeof window.refreshStats === 'function') {
                await window.refreshStats();
            }
        };

        runner().catch(error => {
            console.error('[main.js] 后台刷新站点数据失败:', error);
        });
    }, 0);
}

function resetFilterModalTextareaLayout() {
    const modal = document.getElementById('filterModal');
    if (!modal) {
        return;
    }

    const textareas = modal.querySelectorAll('.modal-textarea-dynamic');

    textareas.forEach(textarea => {
        textarea.style.removeProperty('width');
        textarea.style.removeProperty('height');
        textarea.style.removeProperty('min-height');
        textarea.style.removeProperty('max-height');
        textarea.style.removeProperty('white-space');
        textarea.style.removeProperty('overflow');
        textarea.style.removeProperty('overflow-x');
        textarea.style.removeProperty('overflow-y');
        textarea.style.removeProperty('resize');
    });
}

window.autoResizeTextarea = function(textarea) {
    if (!textarea) {
        return;
    }

    if (!textarea.classList.contains('modal-textarea-dynamic')) {
        return;
    }

    textarea.style.setProperty('width', '100%', 'important');
    textarea.style.setProperty('white-space', 'pre', 'important');
    textarea.style.setProperty('overflow-x', 'auto', 'important');
    textarea.style.setProperty('overflow-y', 'auto', 'important');
    textarea.style.setProperty('resize', 'none', 'important');
}

/**
 * 打开过滤规则弹窗 - 从后端加载站点过滤配置
 */
window.openFilterModal = async function(siteName) {
    try {
        const canOpen = await window.beforeOpenSiteManagementModal('filterModal');
        if (!canOpen) {
            return false;
        }

        let site = getCachedSiteByName(siteName);
        if (!site) {
            // 缓存缺失时再回退请求，避免正常场景下多一次网络等待
            const result = await apiGet('/api/sites');
            if (!result.success) {
                throw new Error('获取站点配置失败');
            }
            site = Array.isArray(result.sites)
                ? result.sites.find(s => s.name === siteName)
                : null;
        }

        if (!site) {
            throw new Error('站点不存在：' + siteName);
        }
        
        // 设置弹窗标题显示站点名称
        document.getElementById('filterModalSiteName').textContent = siteName;

        // 从站点配置读取过滤规则
        const filter = site.filter || {};
        const keywords = typeof filter.keywords_text === 'string'
            ? filter.keywords_text
            : Array.isArray(filter.keywords)
                ? filter.keywords.join('\n')
                : '';
        const exclude = typeof filter.exclude_text === 'string'
            ? filter.exclude_text
            : Array.isArray(filter.exclude)
                ? filter.exclude.join('\n')
                : '';
        const minSize = filter.min_size || '';
        const maxSize = filter.max_size || '';
        
        document.getElementById('filterKeywords').value = keywords;
        document.getElementById('filterExclude').value = exclude;
        document.getElementById('filterMinSize').value = minSize;
        document.getElementById('filterMaxSize').value = maxSize;
        
        const filterModal = document.getElementById('filterModal');
        resetFilterModalTextareaLayout();
        filterModal.classList.add('show');
        window.captureSiteManagementModalState('filterModal');

        requestAnimationFrame(() => {
            window.autoResizeTextarea(document.getElementById('filterKeywords'));
            window.autoResizeTextarea(document.getElementById('filterExclude'));
        });

        return true;
    } catch (e) {
        showToast('加载配置失败：' + e.message, 'error');
        console.error('Load filter config error:', e);
        return false;
    }
}

/**
 * 关闭过滤规则弹窗
 */
window.closeFilterModal = async function() {
    return window.closeSiteManagementModal('filterModal', {
        force: false,
        reason: '关闭'
    });
}

/**
 * 保存过滤规则 - 站点级别
 */
window.saveFilterRules = async function() {
    const saveBtn = document.getElementById('filterModalSaveBtn');

    await runModalSubmitAction('filterModal:save', saveBtn, '保存中', async () => {
        try {
            // 从弹窗标题获取站点名称
            const siteName = document.getElementById('filterModalSiteName').textContent.trim();
            if (!siteName) {
                throw new Error('未指定站点名称');
            }
            
            // 获取表单数据
            const keywords = document.getElementById('filterKeywords').value;
            const exclude = document.getElementById('filterExclude').value;
            const minSize = document.getElementById('filterMinSize').value || '';
            const maxSize = document.getElementById('filterMaxSize').value || '';
            
            // 调用 API 更新站点配置
            const updateData = {
                filter: {
                    keywords: parseFilterEntriesFromText(keywords),
                    exclude: parseFilterEntriesFromText(exclude),
                    keywords_text: keywords,
                    exclude_text: exclude,
                    min_size: minSize ? parseFloat(minSize) : 0,
                    max_size: maxSize ? parseFloat(maxSize) : 0
                }
            };
            
            const response = await apiPut('/api/sites/' + encodeURIComponent(siteName), updateData);
            
            if (!response.success) {
                throw new Error(response.message || '保存失败');
            }

            if (typeof window.markSiteRecentAction === 'function') {
                window.markSiteRecentAction(siteName);
            }
            applySiteUpdateToCache(siteName, {
                filter: updateData.filter
            });
            if (typeof window.renderSites === 'function') {
                window.renderSites();
            }
            window.clearSiteManagementModalState('filterModal');
            await window.closeFilterModal();
            queueSitePanelRefresh(false);
            showToast('过滤规则已保存（仅对站点 "' + siteName + '" 生效）', 'success');
        } catch (e) {
            showToast('保存失败：' + e.message, 'error');
            console.error('Save filter rules error:', e);
            throw e;
        }
    });
}

// ==================== 站点配置弹窗相关函数 ====================

/**
 * 打开站点配置弹窗 - 从后端加载站点配置
 */
window.openSiteConfigModal = async function(siteName) {
    try {
        const canOpen = await window.beforeOpenSiteManagementModal('configModal');
        if (!canOpen) {
            return false;
        }

        let site = getCachedSiteByName(siteName);
        if (!site) {
            // 缓存缺失时再回退请求，避免正常场景下多一次网络等待
            const timestamp = Date.now();
            const result = await apiGet('/api/sites', { t: timestamp });
            if (!result.success) {
                throw new Error('获取站点配置失败');
            }
            site = Array.isArray(result.sites)
                ? result.sites.find(s => s.name === siteName)
                : null;
        }

        if (!site) {
            throw new Error('站点不存在：' + siteName);
        }
        
        // 设置弹窗标题显示站点名称
        document.getElementById('configModalSiteName').textContent = siteName;
        
        // 填充配置值（从站点配置读取）
        document.getElementById('configInterval').value = site.interval || '3600';
        document.getElementById('configCleanupInterval').value = site.cleanup_interval || '';
        document.getElementById('configPauseAdded').checked = site.pause_added || false;
        document.getElementById('configAutoDelete').checked = site.auto_delete || false;
        document.getElementById('configDeleteFiles').checked = site.delete_files || false;
        // 确保正确读取 auto_download 字段
        const autoDownload = site.auto_download === true;
        document.getElementById('configAutoDownload').checked = autoDownload;
        
        console.log('加载站点配置:', siteName, 'auto_download:', autoDownload);
        
        // 记录当前站点名称，用于保存
        currentSiteName = siteName;
        
        document.getElementById('configModal').classList.add('show');
        window.captureSiteManagementModalState('configModal');
        return true;
    } catch (e) {
        showToast('加载配置失败：' + e.message, 'error');
        console.error('Load site config error:', e);
        return false;
    }
}

/**
 * 关闭站点配置弹窗
 */
window.closeConfigModal = async function() {
    return window.closeSiteManagementModal('configModal', {
        force: false,
        reason: '关闭'
    });
}

/**
 * 从弹窗保存配置 - 站点级别
 */
window.saveConfigFromModal = async function() {
    const saveBtn = document.getElementById('configModalSaveBtn');

    await runModalSubmitAction('configModal:save', saveBtn, '保存中', async () => {
        try {
            // 获取当前站点名称
            const siteName = typeof currentSiteName !== 'undefined' ? currentSiteName : null;
            if (!siteName) {
                throw new Error('未指定站点名称');
            }
            
            // 从弹窗读取值
            const interval = document.getElementById('configInterval').value || '3600';
            const cleanupInterval = document.getElementById('configCleanupInterval').value || '0';
            const pauseAdded = document.getElementById('configPauseAdded').checked;
            const autoDelete = document.getElementById('configAutoDelete').checked;
            const deleteFiles = document.getElementById('configDeleteFiles').checked;
            const autoDownload = document.getElementById('configAutoDownload').checked;
            
            // 调用 API 更新站点配置
            const updateData = {
                schedule: {
                    interval: parseInt(interval, 10),
                    cleanup_interval: parseInt(cleanupInterval, 10)
                },
                download_settings: {
                    paused: pauseAdded,
                    auto_delete: autoDelete,
                    delete_files: deleteFiles,
                    auto_download: autoDownload
                },
                // 同时更新全局 qbittorrent 配置，确保下载时使用正确的 paused 值
                qbittorrent_pause_added: pauseAdded
            };
            
            // 同时更新站点的 auto_download 字段（确保与 download_settings.auto_download 同步）
            updateData.auto_download = autoDownload;
            
            // 注意：不修改 filter 字段，保持过滤规则弹窗的独立性
            // filter 字段只能通过过滤规则弹窗修改
            
            const response = await apiPut('/api/sites/' + encodeURIComponent(siteName), updateData);
            
            if (!response.success) {
                throw new Error(response.message || '保存失败');
            }

            if (typeof window.markSiteRecentAction === 'function') {
                window.markSiteRecentAction(siteName);
            }
            applySiteUpdateToCache(siteName, {
                schedule: updateData.schedule,
                download_settings: updateData.download_settings,
                auto_download: autoDownload,
                pause_added: pauseAdded,
                auto_delete: autoDelete,
                delete_files: deleteFiles,
            });
            if (typeof window.renderSites === 'function') {
                window.renderSites();
            }
            window.clearSiteManagementModalState('configModal');
            await window.closeConfigModal();
            queueSitePanelRefresh(true);
            showToast('配置已保存（仅对站点 "' + siteName + '" 生效）', 'success');
            
            // 同步更新卡片上的自动下载开关
            syncCardAutoDownloadSwitch(siteName, autoDownload);
        } catch (e) {
            showToast('保存失败：' + e.message, 'error');
            console.error('Save config from modal error:', e);
            throw e;
        }
    });
}

/**
 * 同步卡片上的自动下载开关状态
 * @param {string} siteName - 站点名称
 * @param {boolean} enabled - 是否启用自动下载
 */
window.syncCardAutoDownloadSwitch = function(siteName, enabled) {
    // 更新卡片上的 checkbox 状态
    const checkbox = document.getElementById('auto-download-' + siteName);
    const label = document.getElementById('auto-download-label-' + siteName);
    const card = document.querySelector('#sitesContainer .site-card[data-site-name="' + siteName + '"]');
    const toggleItem = checkbox ? checkbox.closest('.toggle-item') : null;
    
    if (checkbox) {
        checkbox.checked = enabled;
    }
    if (label) {
        label.textContent = enabled ? '自动下载开' : '自动下载关';
        label.classList.toggle('toggle-label-accent', enabled);
        label.classList.toggle('toggle-label-muted', !enabled);
    }
    if (toggleItem) {
        toggleItem.classList.toggle('is-on', enabled);
        toggleItem.classList.toggle('is-off', !enabled);
    }
    if (card) {
        card.classList.toggle('site-card-auto-on', enabled);
        card.classList.toggle('site-card-auto-off', !enabled);
    }
}

/**
 * 显示预览弹窗加载状态（导出给 sites.js 使用）
 */
window.showPreviewModalLoading = showPreviewModalLoading;

/**
 * 更新预览缓存并渲染（导出给 sites.js 使用）
 */
window.updatePreviewCacheAndRender = updatePreviewCacheAndRender;

/**
 * 显示预览弹窗（导出给 sites.js 使用）
 */
window.showPreviewModal = showPreviewModal;

/**
 * 关闭预览弹窗（导出给 HTML onclick 使用）
 */
window.closeModal = closeModal;

/**
 * 下载选中的种子（导出给 HTML onclick 使用）
 */
window.downloadSelectedTorrents = downloadSelectedTorrents;

/**
 * 更新预览缓存（导出给内部使用）
 */
window.updatePreviewCache = updatePreviewCache;

/**
 * 切换种子选中状态（导出给 HTML onclick 使用）
 */
window.toggleTorrentSelection = toggleTorrentSelection;

/**
 * 切换日志自动刷新（导出给 HTML onchange 使用）
 */
window.toggleLogAutoRefresh = toggleLogAutoRefresh;

/**
 * 测试 qBittorrent 连接（导出给 HTML onclick 使用）
 */
window.testQBConnection = testQBConnection;

// ==================== 确认模态框函数 ====================

/**
 * 确认模态框回调存储
 */
let confirmModalCallback = null;
let confirmModalCancelCallback = null;

/**
 * 显示确认模态框（全局函数）
 * @param {string} title - 标题
 * @param {string} message - 消息内容
 * @param {string} warning - 警告信息（可选）
 * @param {Function} onConfirm - 确认回调
 */
window.showConfirmModal = function(title, message, warning, onConfirm, options = {}) {
    const {
        onCancel = null,
        confirmText = '确定',
        cancelText = '取消'
    } = options;
    const confirmBtn = document.getElementById('confirmModalConfirmBtn');
    const cancelBtn = document.getElementById('confirmModalCancelBtn');

    document.getElementById('confirmModalTitle').textContent = title;
    document.getElementById('confirmModalMessage').innerHTML = message + (warning ? `<div class="confirm-warning">${warning}</div>` : '');
    confirmModalCallback = onConfirm;
    confirmModalCancelCallback = onCancel;
    if (confirmBtn) {
        confirmBtn.textContent = confirmText;
    }
    if (cancelBtn) {
        cancelBtn.textContent = cancelText;
    }
    document.getElementById('confirmModal').classList.add('show');
}

window.askConfirmModal = function(title, message, warning, confirmText = '确定', cancelText = '取消') {
    return new Promise((resolve) => {
        let settled = false;
        const settle = (value) => {
            if (settled) {
                return;
            }
            settled = true;
            resolve(value);
        };

        window.showConfirmModal(title, message, warning, () => settle(true), {
            onCancel: () => settle(false),
            confirmText,
            cancelText
        });
    });
}

/**
 * 关闭确认模态框
 */
window.closeConfirmModal = function(options = {}) {
    const { confirmed = false } = options;
    const confirmBtn = document.getElementById('confirmModalConfirmBtn');
    const cancelBtn = document.getElementById('confirmModalCancelBtn');
    const cancelCallback = confirmModalCancelCallback;

    document.getElementById('confirmModal').classList.remove('show');
    confirmModalCallback = null;
    confirmModalCancelCallback = null;
    if (confirmBtn) {
        confirmBtn.textContent = '确定';
    }
    if (cancelBtn) {
        cancelBtn.textContent = '取消';
    }
    if (!confirmed && typeof cancelCallback === 'function') {
        cancelCallback();
    }
}

/**
 * 确认模态框的确认操作
 */
window.confirmModalAction = async function() {
    const callback = confirmModalCallback;
    window.closeConfirmModal({ confirmed: true });
    if (callback) {
        try {
            await callback();
        } catch (e) {
            console.error('Confirm modal callback error:', e);
        }
    }
}

/**
 * 局部函数桥接（供模块内部调用）
 */
function showConfirmModal(title, message, details, onConfirm, options = {}) {
    window.showConfirmModal(title, message, details, onConfirm, options);
}

// ==================== 覆盖 saveQBConfig 关闭面板 ====================

// 保存 QB 配置后自动关闭滑出面板
window.saveQBConfig = async function() {
    try {
        // 获取 QB 配置表单数据
        const qbHost = document.getElementById('qbHost')?.value || '';
        const qbUsername = document.getElementById('qbUsername')?.value || '';
        const qbPassword = document.getElementById('qbPassword')?.value || '';
        const savePath = document.getElementById('savePath')?.value || '';
        
        // 构建配置对象
        const configData = {
            qbittorrent: {
                host: qbHost,
                username: qbUsername,
                password: qbPassword,
                save_path: savePath
            }
        };
        
        // 调用 API 保存
        const result = await saveConfigData(configData);
        
        if (!result.success) {
            throw new Error(result.message || '保存失败');
        }
        
        // 保存成功，关闭面板并显示提示
        if (typeof toggleQBPanel === 'function') {
            toggleQBPanel();
        }
        
        showToast('QB 配置已保存', 'success');
        
    } catch (e) {
        showToast('保存失败：' + e.message, 'error');
    }
};
