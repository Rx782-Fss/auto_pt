/**
 * 站点管理模块
 * 负责 PT 站点的增删改查
 * v=1772345002
 */

import { apiGet, apiPost, apiPut, apiDelete } from './api.js?v=174';
import { updateSitePanelSummary, updateSiteResultMeta } from './panel-manager.js?v=2';

// 当前操作的站点名称
let currentSiteName = null;

// 全局缓存
window.sitesData = [];

// 分页配置
const SITES_PER_PAGE = 12;
const SITE_RECENT_ACTION_STORAGE_KEY = 'site_recent_actions';

let currentSitesPage = 1;
let currentSiteQuery = '';
let currentSiteFilter = 'all';
let currentSiteSort = 'default';

const selectedSiteNames = new Set();
const siteActionLocks = new Set();
const siteNameCollator = new Intl.Collator('zh-CN', {
    sensitivity: 'base',
    numeric: true
});

let recentActionMap = loadRecentActionMap();

window.selectedSiteNames = selectedSiteNames;

const SITE_FILTER_LABELS = {
    all: '全部站点',
    enabled: '仅看启用',
    paused: '仅看暂停',
    auto_download_on: '自动下载开启',
    auto_download_off: '自动下载关闭'
};

const SITE_SORT_LABELS = {
    default: '默认顺序',
    name_asc: '名称 A-Z',
    enabled_first: '已启用优先',
    auto_download_first: '自动下载优先',
    recent_first: '最近操作优先'
};

const SITE_CARD_ACTION_LOADING_TEXT = {
    edit: '打开中',
    config: '打开中',
    filter: '打开中',
    download: '载入中'
};

const SITE_BATCH_BUTTON_CONFIG = {
    enable: {
        id: 'siteBatchEnableBtn',
        loadingText: '启用中'
    },
    disable: {
        id: 'siteBatchDisableBtn',
        loadingText: '暂停中'
    },
    auto_on: {
        id: 'siteBatchAutoOnBtn',
        loadingText: '开启中'
    },
    auto_off: {
        id: 'siteBatchAutoOffBtn',
        loadingText: '关闭中'
    }
};

// Toast 通知函数 - 避免无限递归
var _siteToast = function(message, type) {
    console.log('[' + type + ']', message);
};

function showToast(message, type) {
    try {
        var f = window._mainShowToast;
        if (typeof f === 'function') {
            f(message, type);
        } else {
            _siteToast(message, type || 'success');
        }
    } catch (e) {
        _siteToast(message, type || 'success');
    }
}

function showError(message) {
    showToast(message, 'error');
}

function buildEmptyState(title, hint, iconName) {
    return '<div class="site-panel-empty"><div class="site-panel-empty-icon"><i data-lucide="' + iconName + '" class="icon-xl"></i></div><div class="site-panel-empty-title">' + title + '</div><div class="site-panel-empty-hint">' + hint + '</div></div>';
}

function loadRecentActionMap() {
    try {
        const raw = localStorage.getItem(SITE_RECENT_ACTION_STORAGE_KEY);
        if (!raw) {
            return {};
        }

        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (e) {
        return {};
    }
}

function persistRecentActionMap() {
    localStorage.setItem(SITE_RECENT_ACTION_STORAGE_KEY, JSON.stringify(recentActionMap));
}

function pruneRecentActionMap() {
    const validNames = new Set(window.sitesData.map(site => site.name));
    let changed = false;

    Object.keys(recentActionMap).forEach((siteName) => {
        if (!validNames.has(siteName)) {
            delete recentActionMap[siteName];
            changed = true;
        }
    });

    if (changed) {
        persistRecentActionMap();
    }
}

function markSiteRecentAction(siteNames) {
    const names = Array.isArray(siteNames) ? siteNames : [siteNames];
    const baseTime = Date.now();
    let changed = false;

    names.filter(Boolean).forEach((siteName, index) => {
        recentActionMap[siteName] = baseTime + index;
        changed = true;
    });

    if (changed) {
        persistRecentActionMap();
    }
}

function clearSiteRecentAction(siteName) {
    if (!siteName || !(siteName in recentActionMap)) {
        return;
    }

    delete recentActionMap[siteName];
    persistRecentActionMap();
}

function getSiteRecentActionTime(siteName) {
    return Number(recentActionMap[siteName]) || 0;
}

window.markSiteRecentAction = function(siteNames) {
    markSiteRecentAction(siteNames);
};

window.clearSiteRecentAction = function(siteName) {
    clearSiteRecentAction(siteName);
};

function pruneSelectedSiteNames() {
    const validNames = new Set(window.sitesData.map(site => site.name));

    Array.from(selectedSiteNames).forEach((siteName) => {
        if (!validNames.has(siteName)) {
            selectedSiteNames.delete(siteName);
        }
    });
}

function compareSitesByName(a, b) {
    return siteNameCollator.compare(String(a.name || ''), String(b.name || ''));
}

function getFilteredSites() {
    const keyword = currentSiteQuery.trim().toLowerCase();
    const filteredSites = window.sitesData.filter(site => {
        const name = String(site.name || '').toLowerCase();
        const matchesKeyword = !keyword || name.includes(keyword);

        let matchesFilter = true;
        switch (currentSiteFilter) {
            case 'enabled':
                matchesFilter = !!site.enabled;
                break;
            case 'paused':
                matchesFilter = !site.enabled;
                break;
            case 'auto_download_on':
                matchesFilter = !!site.auto_download;
                break;
            case 'auto_download_off':
                matchesFilter = !site.auto_download;
                break;
            default:
                matchesFilter = true;
                break;
        }

        return matchesKeyword && matchesFilter;
    });

    switch (currentSiteSort) {
        case 'name_asc':
            filteredSites.sort(compareSitesByName);
            break;
        case 'enabled_first':
            filteredSites.sort((a, b) => {
                const enabledDiff = Number(!!b.enabled) - Number(!!a.enabled);
                return enabledDiff || compareSitesByName(a, b);
            });
            break;
        case 'auto_download_first':
            filteredSites.sort((a, b) => {
                const autoDownloadDiff = Number(!!b.auto_download) - Number(!!a.auto_download);
                return autoDownloadDiff || compareSitesByName(a, b);
            });
            break;
        case 'recent_first':
            filteredSites.sort((a, b) => {
                const recentDiff = getSiteRecentActionTime(b.name) - getSiteRecentActionTime(a.name);
                return recentDiff || compareSitesByName(a, b);
            });
            break;
        default:
            break;
    }

    return filteredSites;
}

function getCurrentPageSites(preparedSites = null) {
    const sites = preparedSites || getFilteredSites();
    const totalPages = Math.max(1, Math.ceil(sites.length / SITES_PER_PAGE));

    if (currentSitesPage > totalPages) {
        currentSitesPage = totalPages;
    }
    if (currentSitesPage < 1) {
        currentSitesPage = 1;
    }

    const startIndex = (currentSitesPage - 1) * SITES_PER_PAGE;
    return sites.slice(startIndex, startIndex + SITES_PER_PAGE);
}

function updateResultMeta(filteredCount, totalCount, totalPages) {
    if (totalCount === 0) {
        updateSiteResultMeta('还没有站点，点击右上角“添加站点”开始配置。', 'empty');
        return;
    }

    if (filteredCount === 0) {
        const activeFilter = SITE_FILTER_LABELS[currentSiteFilter] || SITE_FILTER_LABELS.all;
        const queryText = currentSiteQuery.trim() ? `，搜索词“${currentSiteQuery.trim()}”` : '';
        updateSiteResultMeta(`没有匹配结果，当前筛选为“${activeFilter}”${queryText}。`, 'warning');
        return;
    }

    const parts = [`显示 ${filteredCount} / ${totalCount} 个站点`];
    if (currentSiteFilter !== 'all') {
        parts.push(SITE_FILTER_LABELS[currentSiteFilter]);
    }
    if (currentSiteSort !== 'default') {
        parts.push(`排序：${SITE_SORT_LABELS[currentSiteSort]}`);
    }
    if (currentSiteQuery.trim()) {
        parts.push(`搜索：${currentSiteQuery.trim()}`);
    }
    if (selectedSiteNames.size > 0) {
        parts.push(`已选 ${selectedSiteNames.size} 个`);
    }
    if (totalPages > 1) {
        parts.push(`第 ${currentSitesPage} / ${totalPages} 页`);
    }

    updateSiteResultMeta(parts.join(' · '), 'ready');
}

function syncFilterInputs() {
    const searchInput = document.getElementById('siteSearchInput');
    const filterSelect = document.getElementById('siteFilterSelect');
    const sortSelect = document.getElementById('siteSortSelect');

    if (searchInput && searchInput.value !== currentSiteQuery) {
        searchInput.value = currentSiteQuery;
    }

    if (filterSelect && filterSelect.value !== currentSiteFilter) {
        filterSelect.value = currentSiteFilter;
    }

    if (sortSelect && sortSelect.value !== currentSiteSort) {
        sortSelect.value = currentSiteSort;
    }
}

function formatDuration(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) {
        return '--';
    }

    if (value % 3600 === 0) {
        return (value / 3600) + ' 小时';
    }
    if (value % 60 === 0) {
        return (value / 60) + ' 分钟';
    }
    return value + ' 秒';
}

function getCleanupIntervalText(site) {
    const cleanupInterval = Number(site.cleanup_interval || 0);
    if (!Number.isFinite(cleanupInterval) || cleanupInterval <= 0) {
        return '跟随检查';
    }
    return formatDuration(cleanupInterval);
}

function getAutoDeleteText(site) {
    if (!site.auto_delete) {
        return '已关闭';
    }
    return site.delete_files ? '删种删文件' : '仅删种';
}

function escapeSiteNameForAttr(siteName) {
    return escapeHtml(siteName);
}

function buildSiteActionButtonHtml(action, iconName, label, title, escapedSiteName) {
    return '<button class="btn-card-' + action + ' site-action-btn" onclick="handleSiteCardAction(this, \'' + action + '\', \'' + escapedSiteName + '\')" title="' + title + '">' +
        '<i data-lucide="' + iconName + '" class="icon-sm"></i>' +
        '<span>' + label + '</span>' +
        '</button>';
}

function setButtonLoadingState(button, isLoading, loadingText) {
    if (!button) {
        return;
    }

    if (isLoading) {
        if (!button.dataset.defaultHtml) {
            button.dataset.defaultHtml = button.innerHTML;
        }
        button.disabled = true;
        button.classList.add('is-loading');
        button.innerHTML = '<span class="loading"></span><span>' + loadingText + '</span>';
        return;
    }

    button.disabled = false;
    button.classList.remove('is-loading');
    if (button.dataset.defaultHtml) {
        button.innerHTML = button.dataset.defaultHtml;
    }
}

function setSwitchBusyState(inputEl, isBusy) {
    if (!inputEl) {
        return;
    }

    inputEl.disabled = isBusy;
    const switchEl = inputEl.closest('.toggle-switch');
    if (switchEl) {
        switchEl.classList.toggle('is-busy', isBusy);
    }
    const toggleItem = inputEl.closest('.toggle-item');
    if (toggleItem) {
        toggleItem.classList.toggle('is-busy', isBusy);
    }
}

async function withSiteActionLock(lockKey, handler, options = {}) {
    const {
        button = null,
        loadingText = '处理中',
        onStart = null,
        onEnd = null
    } = options;

    if (siteActionLocks.has(lockKey)) {
        return false;
    }

    siteActionLocks.add(lockKey);
    setButtonLoadingState(button, true, loadingText);
    if (typeof onStart === 'function') {
        onStart();
    }
    updateBatchControls();

    try {
        await handler();
        return true;
    } finally {
        siteActionLocks.delete(lockKey);
        if (typeof onEnd === 'function') {
            onEnd();
        }
        setButtonLoadingState(button, false, loadingText);
        updateBatchControls();
    }
}

function updateBatchControls() {
    const statusEl = document.getElementById('siteBatchStatus');
    const currentPageSites = getCurrentPageSites();
    const selectedCount = selectedSiteNames.size;

    if (statusEl) {
        statusEl.classList.remove('is-empty', 'is-selected', 'is-ready');
        if (selectedCount > 0) {
            statusEl.textContent = '已选 ' + selectedCount + ' 个站点';
            statusEl.classList.add('is-selected');
        } else {
            statusEl.textContent = currentPageSites.length > 0 ? '未选择站点' : '当前页没有可选站点';
            statusEl.classList.add(currentPageSites.length > 0 ? 'is-ready' : 'is-empty');
        }
    }

    const selectPageBtn = document.getElementById('siteBatchSelectPageBtn');
    const clearBtn = document.getElementById('siteBatchClearBtn');
    const enableBtn = document.getElementById('siteBatchEnableBtn');
    const disableBtn = document.getElementById('siteBatchDisableBtn');
    const autoOnBtn = document.getElementById('siteBatchAutoOnBtn');
    const autoOffBtn = document.getElementById('siteBatchAutoOffBtn');

    if (selectPageBtn && !selectPageBtn.classList.contains('is-loading')) {
        selectPageBtn.disabled = currentPageSites.length === 0;
    }
    if (clearBtn && !clearBtn.classList.contains('is-loading')) {
        clearBtn.disabled = selectedCount === 0;
    }
    if (enableBtn && !enableBtn.classList.contains('is-loading')) {
        enableBtn.disabled = selectedCount === 0;
    }
    if (disableBtn && !disableBtn.classList.contains('is-loading')) {
        disableBtn.disabled = selectedCount === 0;
    }
    if (autoOnBtn && !autoOnBtn.classList.contains('is-loading')) {
        autoOnBtn.disabled = selectedCount === 0;
    }
    if (autoOffBtn && !autoOffBtn.classList.contains('is-loading')) {
        autoOffBtn.disabled = selectedCount === 0;
    }
}

function updateSiteCardSelectionState(siteName) {
    const cards = document.querySelectorAll('#sitesContainer .site-card');
    cards.forEach((card) => {
        if (card.dataset.siteName === siteName) {
            card.classList.toggle('is-selected', selectedSiteNames.has(siteName));
        }
    });
}

async function refreshSitesAndStats(refreshStats = false) {
    await loadSites();
    if (refreshStats && typeof window.refreshStats === 'function') {
        await window.refreshStats();
    }
}

function buildSiteMetaRow(site) {
    return [
        '<div class="site-card-meta-row">',
        '<div class="site-card-meta-item"><span class="site-card-meta-label">检查周期</span><span class="site-card-meta-value">' + escapeHtml(formatDuration(site.interval || 300)) + '</span></div>',
        '<div class="site-card-meta-item"><span class="site-card-meta-label">清理周期</span><span class="site-card-meta-value">' + escapeHtml(getCleanupIntervalText(site)) + '</span></div>',
        '<div class="site-card-meta-item"><span class="site-card-meta-label">自动删种</span><span class="site-card-meta-value">' + escapeHtml(getAutoDeleteText(site)) + '</span></div>',
        '</div>'
    ].join('');
}

/**
 * 加载所有站点
 */
const loadSites = window.loadSites = async function() {
    try {
        const response = await apiGet('/api/sites');
        window.sitesData = response.sites || [];
        recentActionMap = loadRecentActionMap();
        pruneRecentActionMap();
        pruneSelectedSiteNames();
        updateSitePanelSummary(window.sitesData);
        renderSites();
    } catch (error) {
        updateSitePanelSummary(null);
        updateSiteResultMeta('站点列表加载失败，请稍后重试。');
        const container = document.getElementById('sitesContainer');
        if (container) {
            container.innerHTML = buildEmptyState('加载失败', '站点列表暂时不可用，请稍后重试。', 'alert-triangle');
            if (typeof lucide !== 'undefined') {
                lucide.createIcons();
            }
        }
        updateBatchControls();
        showError('加载站点失败：' + error.message);
        console.error('Load sites error:', error);
    }
};

/**
 * 渲染站点列表 - 支持分页
 */
const renderSites = window.renderSites = function() {
    const container = document.getElementById('sitesContainer');

    if (!container) {
        console.error('sitesContainer not found');
        return;
    }

    syncFilterInputs();
    updateSitePanelSummary(window.sitesData);

    const filteredSites = getFilteredSites();
    const totalSites = filteredSites.length;
    const totalPages = Math.max(1, Math.ceil(totalSites / SITES_PER_PAGE));
    const currentSites = totalSites > 0 ? getCurrentPageSites(filteredSites) : [];

    if (window.sitesData.length === 0) {
        container.innerHTML = buildEmptyState('暂无站点', '点击右上角“添加站点”开始管理你的 PT 站点。', 'globe-2');
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
        updateResultMeta(0, 0, 0);
        updateBatchControls();
        return;
    }

    if (filteredSites.length === 0) {
        container.innerHTML = buildEmptyState('没有匹配结果', '试试调整筛选条件，或者清空搜索后再看。', 'search-x');
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
        updateResultMeta(0, window.sitesData.length, 0);
        updateBatchControls();
        return;
    }

    let html = '';
    currentSites.forEach((site) => {
        const statusIconName = site.enabled ? 'globe-2' : 'pause';
        const statusText = site.enabled ? '运行中' : '已暂停';
        const statusClass = site.enabled ? 'status-active' : 'status-paused';
        const escapedSiteName = escapeSiteNameForAttr(site.name);
        const isSelected = selectedSiteNames.has(site.name);
        const cardClasses = [
            'site-card',
            site.enabled ? 'site-card-enabled' : 'site-card-paused',
            site.auto_download ? 'site-card-auto-on' : 'site-card-auto-off'
        ].filter(Boolean);

        if (isSelected) {
            cardClasses.push('is-selected');
        }

        html += '<div class="' + cardClasses.join(' ') + '" data-site-name="' + escapedSiteName + '">';
        html += '<div class="site-card-header">';
        html += '<div class="site-card-title">';
        html += '<span class="site-card-icon ' + statusClass + '"><i data-lucide="' + statusIconName + '" class="icon-md"></i></span>';
        html += '<span class="site-card-name">' + escapeHtml(site.name) + '</span>';
        html += '</div>';
        html += '<div class="site-card-header-actions">';
        html += '<label class="site-select-chip" title="选择站点">';
        html += '<input type="checkbox" ' + (isSelected ? 'checked ' : '') + 'onchange="toggleSiteSelection(\'' + escapedSiteName + '\', this.checked)">';
        html += '<span>选择</span>';
        html += '</label>';
        html += '<span class="site-card-status-tag ' + statusClass + '">' + statusText + '</span>';
        html += '</div>';
        html += '</div>';

        html += '<div class="site-card-body">';
        html += '<div class="site-card-info">';
        html += buildSiteMetaRow(site);
        html += '<div class="site-card-row site-card-toggle-row">';
        html += '<div class="toggle-item toggle-item-status ' + (site.enabled ? 'is-on' : 'is-off') + '">';
        html += '<label class="toggle-switch toggle-status">';
        html += '<input type="checkbox" ' + (site.enabled ? 'checked ' : '') + 'onchange="toggleSiteByName(\'' + escapedSiteName + '\', this.checked, this)">';
        html += '<span class="toggle-slider"></span>';
        html += '</label>';
        html += '<span class="toggle-label ' + (site.enabled ? 'toggle-label-active' : 'toggle-label-muted') + '">' + (site.enabled ? '站点已启用' : '站点未启用') + '</span>';
        html += '</div>';
        html += '<div class="toggle-item toggle-item-auto ' + (site.auto_download ? 'is-on' : 'is-off') + '">';
        html += '<label class="toggle-switch toggle-auto" title="新种子自动下载">';
        html += '<input type="checkbox" ' + (site.auto_download ? 'checked ' : '') + 'id="auto-download-' + escapedSiteName + '" onchange="toggleAutoDownload(\'' + escapedSiteName + '\', this.checked, this)">';
        html += '<span class="toggle-slider"></span>';
        html += '</label>';
        html += '<span class="toggle-label ' + (site.auto_download ? 'toggle-label-accent' : 'toggle-label-muted') + '" id="auto-download-label-' + escapedSiteName + '">' + (site.auto_download ? '自动下载开' : '自动下载关') + '</span>';
        html += '</div>';
        html += '</div>';
        html += '</div>';

        html += '<div class="site-card-actions">';
        html += '<div class="site-card-buttons">';
        html += buildSiteActionButtonHtml('edit', 'pencil', '编辑', '编辑站点', escapedSiteName);
        html += buildSiteActionButtonHtml('config', 'sliders-horizontal', '配置', '运行配置', escapedSiteName);
        html += buildSiteActionButtonHtml('filter', 'funnel', '过滤', '过滤种子', escapedSiteName);
        html += buildSiteActionButtonHtml('download', 'download', '下载', '预览下载', escapedSiteName);
        html += '</div>';
        html += '</div>';
        html += '</div>';
        html += '</div>';
    });

    if (totalSites > SITES_PER_PAGE) {
        html += '<div class="sites-pagination">';
        html += '<div class="pagination-info">';
        html += '共 <span class="pagination-total">' + totalSites + '</span> 个结果';
        html += '</div>';
        html += '<div class="pagination-controls">';

        html += '<button class="pagination-btn pagination-prev" onclick="goToSitesPage(' + (currentSitesPage - 1) + ')" ' + (currentSitesPage === 1 ? 'disabled' : '') + '>';
        html += '◀ 上一页';
        html += '</button>';

        html += '<div class="pagination-pages">';
        const maxVisiblePages = 5;
        let startPage = Math.max(1, currentSitesPage - Math.floor(maxVisiblePages / 2));
        let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);

        if (endPage - startPage + 1 < maxVisiblePages) {
            startPage = Math.max(1, endPage - maxVisiblePages + 1);
        }

        if (startPage > 1) {
            html += '<button class="pagination-page" onclick="goToSitesPage(1)">1</button>';
            if (startPage > 2) {
                html += '<span class="pagination-ellipsis">...</span>';
            }
        }

        for (let i = startPage; i <= endPage; i++) {
            if (i === currentSitesPage) {
                html += '<button class="pagination-page pagination-current">' + i + '</button>';
            } else {
                html += '<button class="pagination-page" onclick="goToSitesPage(' + i + ')">' + i + '</button>';
            }
        }

        if (endPage < totalPages) {
            if (endPage < totalPages - 1) {
                html += '<span class="pagination-ellipsis">...</span>';
            }
            html += '<button class="pagination-page" onclick="goToSitesPage(' + totalPages + ')">' + totalPages + '</button>';
        }

        html += '</div>';
        html += '<button class="pagination-btn pagination-next" onclick="goToSitesPage(' + (currentSitesPage + 1) + ')" ' + (currentSitesPage === totalPages ? 'disabled' : '') + '>';
        html += '下一页 ▶';
        html += '</button>';
        html += '</div>';
        html += '<div class="pagination-detail">';
        html += '第 <span class="pagination-current-num">' + currentSitesPage + '</span> / <span class="pagination-total-pages">' + totalPages + '</span> 页';
        html += '</div>';
        html += '</div>';
    }

    container.innerHTML = html;
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
    updateResultMeta(filteredSites.length, window.sitesData.length, totalPages);
    updateBatchControls();
};

const goToSitesPage = window.goToSitesPage = function(page) {
    const totalPages = Math.max(1, Math.ceil(getFilteredSites().length / SITES_PER_PAGE));

    if (page < 1 || page > totalPages || page === currentSitesPage) {
        return;
    }

    currentSitesPage = page;
    renderSites();

    const container = document.getElementById('sitesContainer');
    if (container) {
        const panelBody = container.closest('.qb-panel-body');
        if (panelBody) {
            panelBody.scrollTo({ top: 0, behavior: 'smooth' });
        } else {
            container.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }
};

window.handleSiteSearch = function(value) {
    currentSiteQuery = value || '';
    currentSitesPage = 1;
    renderSites();
};

window.handleSiteFilterChange = function(value) {
    currentSiteFilter = SITE_FILTER_LABELS[value] ? value : 'all';
    currentSitesPage = 1;
    renderSites();
};

window.handleSiteSortChange = function(value) {
    currentSiteSort = SITE_SORT_LABELS[value] ? value : 'default';
    currentSitesPage = 1;
    renderSites();
};

window.resetSiteFilters = function() {
    currentSiteQuery = '';
    currentSiteFilter = 'all';
    currentSiteSort = 'default';
    currentSitesPage = 1;
    syncFilterInputs();
    renderSites();
};

window.toggleSiteSelection = function(siteName, checked) {
    if (checked) {
        selectedSiteNames.add(siteName);
    } else {
        selectedSiteNames.delete(siteName);
    }

    updateSiteCardSelectionState(siteName);
    updateBatchControls();
    updateResultMeta(getFilteredSites().length, window.sitesData.length, Math.max(1, Math.ceil(getFilteredSites().length / SITES_PER_PAGE)));
};

window.selectCurrentPageSites = function() {
    getCurrentPageSites().forEach((site) => {
        selectedSiteNames.add(site.name);
    });
    renderSites();
};

window.clearSelectedSites = function() {
    if (selectedSiteNames.size === 0) {
        return;
    }
    selectedSiteNames.clear();
    renderSites();
};

window.handleSiteCardAction = async function(button, action, siteName) {
    const lockKey = 'card:' + action + ':' + siteName;
    const loadingText = SITE_CARD_ACTION_LOADING_TEXT[action] || '处理中';

    await withSiteActionLock(lockKey, async () => {
        switch (action) {
            case 'edit':
                await window.editSiteByName(siteName);
                break;
            case 'config':
                await window.openSiteConfig(siteName);
                break;
            case 'filter':
                await window.filterSiteTorrents(siteName);
                break;
            case 'download':
                await window.previewSiteTorrents(siteName);
                break;
            default:
                break;
        }
    }, {
        button,
        loadingText
    });
};

window.batchEnableSites = async function() {
    await runBatchSiteUpdate('enable', async (siteName, site) => {
        if (site.enabled) {
            return 'skipped';
        }
        await apiPut('/api/sites/' + encodeURIComponent(siteName), {
            enabled: true
        });
        return 'updated';
    }, true);
};

window.batchDisableSites = async function() {
    await runBatchSiteUpdate('disable', async (siteName, site) => {
        if (!site.enabled) {
            return 'skipped';
        }
        await apiPut('/api/sites/' + encodeURIComponent(siteName), {
            enabled: false
        });
        return 'updated';
    }, true);
};

window.batchEnableAutoDownload = async function() {
    await runBatchSiteUpdate('auto_on', async (siteName, site) => {
        if (site.auto_download) {
            return 'skipped';
        }
        await apiPut('/api/sites/' + encodeURIComponent(siteName), {
            auto_download: true
        });
        return 'updated';
    }, true);
};

window.batchDisableAutoDownload = async function() {
    await runBatchSiteUpdate('auto_off', async (siteName, site) => {
        if (!site.auto_download) {
            return 'skipped';
        }
        await apiPut('/api/sites/' + encodeURIComponent(siteName), {
            auto_download: false
        });
        return 'updated';
    }, true);
};

async function runBatchSiteUpdate(actionKey, updater, refreshStats) {
    const buttonConfig = SITE_BATCH_BUTTON_CONFIG[actionKey];
    const button = buttonConfig ? document.getElementById(buttonConfig.id) : null;
    const siteNames = Array.from(selectedSiteNames);

    if (siteNames.length === 0) {
        showToast('请先选择要批量处理的站点', 'warning');
        return false;
    }

    return withSiteActionLock('batch:' + actionKey, async () => {
        const sitesByName = new Map(window.sitesData.map(site => [site.name, site]));
        const successNames = [];
        const failedNames = [];
        let skippedCount = 0;

        for (const siteName of siteNames) {
            const site = sitesByName.get(siteName);
            if (!site) {
                failedNames.push(siteName + '（站点不存在）');
                continue;
            }

            try {
                const result = await updater(siteName, site);
                if (result === 'skipped') {
                    skippedCount += 1;
                } else {
                    successNames.push(siteName);
                }
            } catch (error) {
                failedNames.push(siteName + '（' + error.message + '）');
            }
        }

        if (successNames.length > 0) {
            markSiteRecentAction(successNames);
            await refreshSitesAndStats(refreshStats);
        }

        if (failedNames.length === 0) {
            if (successNames.length === 0) {
                showToast('选中的站点已经是目标状态，无需重复处理', 'info');
            } else if (skippedCount > 0) {
                showToast('批量处理完成：成功 ' + successNames.length + ' 个，跳过 ' + skippedCount + ' 个', 'success');
            } else {
                showToast('批量处理完成：成功 ' + successNames.length + ' 个站点', 'success');
            }
            return;
        }

        const summary = '批量处理完成：成功 ' + successNames.length + ' 个，失败 ' + failedNames.length + ' 个';
        showToast(summary + '。失败项：' + failedNames.join('，'), successNames.length > 0 ? 'warning' : 'error');
    }, {
        button,
        loadingText: buttonConfig ? buttonConfig.loadingText : '处理中'
    });
}

/**
 * 显示添加站点模态框
 */
window.showAddSiteModal = async function() {
    if (typeof window.beforeOpenSiteManagementModal === 'function') {
        const canOpen = await window.beforeOpenSiteManagementModal('siteModal');
        if (!canOpen) {
            return false;
        }
    }

    document.getElementById('siteModalTitle').textContent = '添加站点';
    document.getElementById('siteOriginalName').value = '';
    document.getElementById('siteOriginalRss').value = '';
    document.getElementById('siteName').value = '';
    document.getElementById('siteRssUrl').value = '';
    document.getElementById('siteBaseUrl').value = '';
    document.getElementById('sitePasskey').value = '';
    document.getElementById('siteUid').value = '';
    document.getElementById('siteTags').value = '';
    document.getElementById('deleteSiteBtn').classList.add('is-hidden');
    document.getElementById('siteModal').classList.add('show');
    if (typeof window.captureSiteManagementModalState === 'function') {
        window.captureSiteManagementModalState('siteModal');
    }
    return true;
};

/**
 * 编辑站点
 */
window.editSiteByName = async function(siteName) {
    const site = window.sitesData.find(s => s.name === siteName);
    if (!site) {
        return false;
    }

    if (typeof window.beforeOpenSiteManagementModal === 'function') {
        const canOpen = await window.beforeOpenSiteManagementModal('siteModal');
        if (!canOpen) {
            return false;
        }
    }

    document.getElementById('siteModalTitle').textContent = '编辑站点：' + siteName;
    document.getElementById('siteOriginalName').value = siteName;
    document.getElementById('siteOriginalRss').value = site.rss_url || '';
    document.getElementById('siteName').value = site.name;
    document.getElementById('siteRssUrl').value = site.rss_url || '';
    document.getElementById('siteBaseUrl').value = site.base_url || '';
    document.getElementById('sitePasskey').value = site.passkey || '';
    document.getElementById('siteUid').value = site.uid || '';

    let tagsStr = '';
    if (site.tags) {
        tagsStr = Array.isArray(site.tags) ? site.tags.join(', ') : site.tags;
    }
    document.getElementById('siteTags').value = tagsStr;
    document.getElementById('deleteSiteBtn').classList.remove('is-hidden');
    document.getElementById('siteModal').classList.add('show');
    if (typeof window.captureSiteManagementModalState === 'function') {
        window.captureSiteManagementModalState('siteModal');
    }
    return true;
};

/**
 * 关闭模态框
 */
window.closeSiteModal = async function() {
    if (typeof window.closeSiteManagementModal === 'function') {
        return window.closeSiteManagementModal('siteModal', {
            force: false,
            reason: '关闭'
        });
    }

    document.getElementById('siteModal').classList.remove('show');
    return true;
};

/**
 * 保存站点
 */
window.saveSite = async function() {
    const originalName = document.getElementById('siteOriginalName').value;
    const saveBtn = document.getElementById('siteModalSaveBtn');
    const deleteBtn = document.getElementById('deleteSiteBtn');

    await withSiteActionLock('siteModal:save', async () => {
        if (deleteBtn) {
            deleteBtn.disabled = true;
        }

        try {
            const originalRss = document.getElementById('siteOriginalRss').value;
            const name = document.getElementById('siteName').value.trim();
            const rssUrl = document.getElementById('siteRssUrl').value.trim();
            const baseUrl = document.getElementById('siteBaseUrl').value.trim();
            const passkey = document.getElementById('sitePasskey').value.trim();
            const uid = document.getElementById('siteUid').value.trim();
            const tagsInput = document.getElementById('siteTags').value.trim();

            if (!name) {
                showError('请输入站点名称');
                return;
            }

            if (!/^[a-zA-Z0-9_]+$/.test(name)) {
                showError('站点名称只能包含字母、数字和下划线');
                return;
            }

            if (!rssUrl) {
                showError('请输入 RSS 订阅链接');
                return;
            }

            let baseUrlFromRss = '';
            try {
                baseUrlFromRss = new URL(rssUrl).origin;
            } catch (e) {
                showError('RSS 订阅链接格式无效，请输入完整的 URL（如：https://example.com/rss.xml）');
                return;
            }

            let tags = [];
            if (tagsInput) {
                tags = tagsInput.split(',').map(t => t.trim()).filter(t => t);
            }
            if (tags.length === 0) {
                tags = [name, 'auto_pt'];
            }

            const currentSite = originalName ? window.sitesData.find(s => s.name === originalName) : null;
            const siteData = {
                name: name,
                type: 'mteam',
                base_url: baseUrl || baseUrlFromRss,
                rss_url: rssUrl,
                passkey: passkey,
                uid: uid,
                tags: tags,
                enabled: currentSite ? !!currentSite.enabled : false
            };

            if (!originalName) {
                siteData.filter = {
                    keywords: [],
                    exclude: [],
                    min_size: 0,
                    max_size: 0
                };
                siteData.schedule = {
                    interval: 120,
                    cleanup_interval: 3600
                };
                siteData.auto_download = false;
            }

            if (originalName) {
                if (originalRss !== rssUrl) {
                    const confirmed = typeof window.askConfirmModal === 'function'
                        ? await window.askConfirmModal(
                            '⚠️ RSS 链接已改变',
                            'RSS 订阅链接已改变，需要删除旧站点并创建新站点。',
                            '⚠️ 注意：这会使用新站点默认配置，原来的过滤规则和运行设置需要重新确认。',
                            '继续更新',
                            '返回编辑'
                        )
                        : window.confirm('RSS 订阅链接已改变，需要删除旧站点并创建新站点，是否继续？');

                    if (!confirmed) {
                        return;
                    }

                    await apiDelete('/api/sites/' + encodeURIComponent(originalName));
                    clearSiteRecentAction(originalName);
                    selectedSiteNames.delete(originalName);
                    await apiPost('/api/sites', siteData);
                } else {
                    await apiPut('/api/sites/' + encodeURIComponent(originalName), siteData);
                    if (originalName !== name) {
                        clearSiteRecentAction(originalName);
                        if (selectedSiteNames.delete(originalName)) {
                            selectedSiteNames.add(name);
                        }
                    }
                }
            } else {
                await apiPost('/api/sites', siteData);
            }

            markSiteRecentAction(name);
            if (typeof window.clearSiteManagementModalState === 'function') {
                window.clearSiteManagementModalState('siteModal');
            }
            await window.closeSiteModal();
            await refreshSitesAndStats(true);

            const action = originalName ? '更新' : '添加';
            showToast(action + '站点 "' + name + '" 成功', 'success');
        } catch (error) {
            const action = originalName ? '更新' : '添加';
            showToast(action + '失败：' + error.message, 'error');
            console.error('Save site error:', error);
        } finally {
            if (deleteBtn) {
                deleteBtn.disabled = false;
            }
        }
    }, {
        button: saveBtn,
        loadingText: originalName ? '保存中' : '添加中'
    });
};

/**
 * 删除当前站点
 */
window.deleteCurrentSite = async function() {
    const siteName = document.getElementById('siteOriginalName').value;
    if (!siteName) {
        return;
    }

    const deleteBtn = document.getElementById('deleteSiteBtn');
    const saveBtn = document.getElementById('siteModalSaveBtn');

    await withSiteActionLock('siteModal:delete', async () => {
        if (saveBtn) {
            saveBtn.disabled = true;
        }

        try {
            const confirmed = typeof window.askConfirmModal === 'function'
                ? await window.askConfirmModal(
                    '🗑️ 删除站点确认',
                    '确定要删除站点 "' + siteName + '" 吗？',
                    '⚠️ 此操作不可恢复！所有历史记录将保留但不再关联。',
                    '确认删除',
                    '取消'
                )
                : window.confirm('确定要删除站点 "' + siteName + '" 吗？');

            if (!confirmed) {
                return;
            }

            await apiDelete('/api/sites/' + encodeURIComponent(siteName));
            clearSiteRecentAction(siteName);
            selectedSiteNames.delete(siteName);
            if (typeof window.clearSiteManagementModalState === 'function') {
                window.clearSiteManagementModalState('siteModal');
            }
            await window.closeSiteModal();
            await refreshSitesAndStats(true);
            showToast('站点 "' + siteName + '" 已删除', 'success');
        } catch (error) {
            showToast('删除失败：' + error.message, 'error');
            console.error('Delete site error:', error);
        } finally {
            if (saveBtn) {
                saveBtn.disabled = false;
            }
        }
    }, {
        button: deleteBtn,
        loadingText: '删除中'
    });
};

/**
 * 切换站点启用状态
 */
window.toggleSiteByName = async function(siteName, nextEnabled = null, inputEl = null) {
    const site = window.sitesData.find(s => s.name === siteName);
    if (!site) {
        return false;
    }

    const targetEnabled = typeof nextEnabled === 'boolean' ? nextEnabled : !site.enabled;
    return withSiteActionLock('site:toggle:' + siteName, async () => {
        try {
            await apiPut('/api/sites/' + encodeURIComponent(siteName), {
                enabled: targetEnabled
            });

            markSiteRecentAction(siteName);
            await refreshSitesAndStats(true);
            showToast((targetEnabled ? '启用' : '禁用') + '站点 "' + siteName + '" 成功', 'success');
        } catch (error) {
            if (inputEl && document.body.contains(inputEl)) {
                inputEl.checked = !!site.enabled;
            }
            showToast('切换状态失败：' + error.message, 'error');
            console.error('Toggle site error:', error);
        }
    }, {
        onStart: () => setSwitchBusyState(inputEl, true),
        onEnd: () => setSwitchBusyState(inputEl, false)
    });
};

/**
 * 预览站点种子 - 优化版本（立即反馈）
 */
window.previewSiteTorrents = async function(siteName) {
    try {
        const site = window.sitesData.find(s => s.name === siteName);
        if (!site || !site.enabled) {
            showToast('站点已禁用，无法预览种子', 'error');
            return false;
        }

        if (typeof window.showPreviewModalLoading === 'function') {
            const opened = await window.showPreviewModalLoading();
            if (!opened) {
                return false;
            }
        }

        const response = await apiPost('/api/preview', { site_name: siteName });
        if (response.success) {
            const newTorrents = response.torrents?.new || [];

            if (typeof window.updatePreviewCacheAndRender === 'function') {
                window.updatePreviewCacheAndRender(response, true);
            }

            markSiteRecentAction(siteName);
            if (newTorrents.length > 0) {
                showToast('获取到 ' + newTorrents.length + ' 个新种子', 'success');
            } else {
                showToast('没有新种子', 'info');
            }
            return true;
        }

        throw new Error(response.message || '获取种子失败');
    } catch (error) {
        if (typeof window.closeModal === 'function') {
            await window.closeModal();
        }
        showToast('预览失败：' + error.message, 'error');
        console.error('Preview error:', error);
        return false;
    }
};

/**
 * 过滤站点种子 - 打开过滤规则弹窗
 */
window.filterSiteTorrents = async function(siteName) {
    try {
        currentSiteName = siteName;
        if (typeof window.openFilterModal === 'function') {
            return await window.openFilterModal(siteName);
        }
        showToast('过滤功能尚未初始化', 'error');
        return false;
    } catch (error) {
        showToast('过滤失败：' + error.message, 'error');
        console.error('Filter error:', error);
        return false;
    }
};

/**
 * 打开站点配置弹窗
 */
window.openSiteConfig = async function(siteName) {
    currentSiteName = siteName;
    if (typeof window.openSiteConfigModal === 'function') {
        return window.openSiteConfigModal(siteName);
    }

    showToast('配置功能尚未初始化', 'error');
    return false;
};

/**
 * 切换自动下载状态
 */
window.toggleAutoDownload = async function(siteName, enabled, inputEl = null) {
    const site = window.sitesData.find(s => s.name === siteName);
    if (!site) {
        return false;
    }

    return withSiteActionLock('site:auto:' + siteName, async () => {
        try {
            const response = await apiPut('/api/sites/' + encodeURIComponent(siteName), {
                auto_download: enabled
            });

            if (!response.success) {
                throw new Error(response.error || response.message || '更新站点配置失败');
            }

            markSiteRecentAction(siteName);
            await refreshSitesAndStats(true);
            showToast(enabled ? '已开启自动下载' : '已关闭自动下载', 'success');
        } catch (e) {
            if (inputEl && document.body.contains(inputEl)) {
                inputEl.checked = !!site.auto_download;
            }
            showToast('切换自动下载失败：' + e.message, 'error');
            console.error('Toggle auto download error:', e);
        }
    }, {
        onStart: () => setSwitchBusyState(inputEl, true),
        onEnd: () => setSwitchBusyState(inputEl, false)
    });
};

/**
 * HTML 转义
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
