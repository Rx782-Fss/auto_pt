/**
 * PT Auto Downloader - History Module
 * 历史记录模块
 */

import { getHistory, deleteHistory as deleteHistoryApi, restoreHistory, clearHistory, apiPost } from './api.js?v=174';
import { formatDateTime, formatRelativeTime, escapeHtml } from './utils.js';

function refreshLucideIcons() {
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

function syncHistorySelectionClasses() {
    document.querySelectorAll('#historyList .history-item').forEach(item => {
        const checkbox = item.querySelector('input[type="checkbox"]');
        item.classList.toggle('selected', Boolean(checkbox?.checked));
    });
}

const DELETED_REASON_LABELS = {
    auto_cleanup_completed: '自动清理',
    manual_removed_after_complete: '完成后删除',
    manual_removed_during_download: '下载中删除',
    manual_removed_paused: '暂停后删除',
    unknown_removed: '未知方式',
};

function formatDeletedReason(reason) {
    const normalizedReason = normalizeHistoryValue(reason);
    return DELETED_REASON_LABELS[normalizedReason] || '未知方式';
}

// 分页配置
let currentPage = 1;
let page_size = 20;
let totalRecords = 0;
let totalPages = 1;
let currentRecords = [];
let searchTimer = null;
let currentSearchTerm = '';
let allHistoryRecords = []; // 全量历史记录缓存（用于前端搜索）
let currentHistorySiteFilter = '';
let currentHistoryCategoryFilter = '';
let currentHistorySort = 'default';
let currentHistoryVisibility = 'visible';

const FILTER_ALL_VALUE = '';
const FILTER_UNKNOWN_VALUE = '__unknown__';

function normalizeHistoryValue(value) {
    return String(value || '').trim();
}

function getHistoryRecordTimestamp(record) {
    if (!record?.added_at) {
        return null;
    }
    const timestamp = new Date(record.added_at).getTime();
    return Number.isFinite(timestamp) ? timestamp : null;
}

function getHistoryRecordSize(record) {
    const size = Number(record?.size);
    return Number.isFinite(size) && size > 0 ? size : null;
}

function compareNullableHistoryValues(aValue, bValue, descending) {
    if (aValue === null && bValue === null) {
        return 0;
    }
    if (aValue === null) {
        return 1;
    }
    if (bValue === null) {
        return -1;
    }
    return descending ? bValue - aValue : aValue - bValue;
}

function compareHistorySearchPriority(a, b, term) {
    const aTitle = normalizeHistoryValue(a.title).toLowerCase();
    const bTitle = normalizeHistoryValue(b.title).toLowerCase();
    const aSite = normalizeHistoryValue(a.site_name).toLowerCase();
    const bSite = normalizeHistoryValue(b.site_name).toLowerCase();
    const aCategory = normalizeHistoryValue(a.category).toLowerCase();
    const bCategory = normalizeHistoryValue(b.category).toLowerCase();

    const getPriority = (title, site, category) => {
        if (title.startsWith(term)) return 1;
        if (site.startsWith(term)) return 2;
        if (category.startsWith(term)) return 3;
        if (title.includes(term)) return 4;
        if (site.includes(term)) return 5;
        if (category.includes(term)) return 6;
        return 7;
    };

    const aPriority = getPriority(aTitle, aSite, aCategory);
    const bPriority = getPriority(bTitle, bSite, bCategory);

    if (aPriority !== bPriority) {
        return aPriority - bPriority;
    }

    return aTitle.localeCompare(bTitle);
}

function buildHistorySelectOptions(values, selectedValue, allLabel, unknownLabel, includeUnknown) {
    const optionValues = values.slice();
    const hasSelectedValue =
        selectedValue === FILTER_ALL_VALUE ||
        optionValues.includes(selectedValue) ||
        (selectedValue === FILTER_UNKNOWN_VALUE && includeUnknown);
    const safeSelectedValue = hasSelectedValue ? selectedValue : FILTER_ALL_VALUE;

    const options = [
        `<option value="${FILTER_ALL_VALUE}"${safeSelectedValue === FILTER_ALL_VALUE ? ' selected' : ''}>${allLabel}</option>`
    ];

    optionValues.forEach(value => {
        const escapedValue = escapeHtml(value);
        options.push(
            `<option value="${escapedValue}"${safeSelectedValue === value ? ' selected' : ''}>${escapedValue}</option>`
        );
    });

    if (includeUnknown) {
        options.push(
            `<option value="${FILTER_UNKNOWN_VALUE}"${safeSelectedValue === FILTER_UNKNOWN_VALUE ? ' selected' : ''}>${unknownLabel}</option>`
        );
    }

    return {
        optionsHtml: options.join(''),
        selectedValue: safeSelectedValue
    };
}

function renderHistoryFilterOptions() {
    const siteSelect = document.getElementById('historySiteFilter');
    const categorySelect = document.getElementById('historyCategoryFilter');

    if (!siteSelect || !categorySelect) {
        return;
    }

    const siteValues = Array.from(
        new Set(allHistoryRecords.map(record => normalizeHistoryValue(record.site_name)).filter(Boolean))
    ).sort((a, b) => a.localeCompare(b));
    const categoryValues = Array.from(
        new Set(allHistoryRecords.map(record => normalizeHistoryValue(record.category)).filter(Boolean))
    ).sort((a, b) => a.localeCompare(b));

    const siteOptions = buildHistorySelectOptions(
        siteValues,
        currentHistorySiteFilter,
        '站点',
        '未知站点',
        allHistoryRecords.some(record => !normalizeHistoryValue(record.site_name))
    );
    currentHistorySiteFilter = siteOptions.selectedValue;
    siteSelect.innerHTML = siteOptions.optionsHtml;
    siteSelect.value = currentHistorySiteFilter;

    const categoryOptions = buildHistorySelectOptions(
        categoryValues,
        currentHistoryCategoryFilter,
        '类型',
        '未知类型',
        allHistoryRecords.some(record => !normalizeHistoryValue(record.category))
    );
    currentHistoryCategoryFilter = categoryOptions.selectedValue;
    categorySelect.innerHTML = categoryOptions.optionsHtml;
    categorySelect.value = currentHistoryCategoryFilter;
}

function updateHistoryVisibilityButton() {
    const button = document.getElementById('historyHiddenToggleBtn');
    const restoreButton = document.getElementById('historyRestoreBtn');
    if (!button) {
        return;
    }

    if (currentHistoryVisibility === 'hidden') {
        button.classList.remove('btn-secondary');
        button.classList.add('btn-accent');
        button.innerHTML = '<i data-lucide="list" class="icon-sm"></i> 返回列表';
        if (restoreButton) {
            restoreButton.style.display = 'inline-flex';
        }
    } else {
        button.classList.remove('btn-accent');
        button.classList.add('btn-secondary');
        button.innerHTML = '<i data-lucide="eye-off" class="icon-sm"></i> 查看已隐藏';
        if (restoreButton) {
            restoreButton.style.display = 'none';
        }
    }
}

function applyHistorySort(records, term) {
    if (currentHistorySort === 'default') {
        if (!term) {
            return records;
        }
        return records.sort((a, b) => compareHistorySearchPriority(a, b, term));
    }

    return records.sort((a, b) => {
        switch (currentHistorySort) {
            case 'time_desc':
                return compareNullableHistoryValues(
                    getHistoryRecordTimestamp(a),
                    getHistoryRecordTimestamp(b),
                    true
                );
            case 'time_asc':
                return compareNullableHistoryValues(
                    getHistoryRecordTimestamp(a),
                    getHistoryRecordTimestamp(b),
                    false
                );
            case 'size_desc':
                return compareNullableHistoryValues(
                    getHistoryRecordSize(a),
                    getHistoryRecordSize(b),
                    true
                );
            case 'size_asc':
                return compareNullableHistoryValues(
                    getHistoryRecordSize(a),
                    getHistoryRecordSize(b),
                    false
                );
            default:
                return 0;
        }
    });
}

function applyHistoryFiltersAndRender(resetPage = false) {
    if (resetPage) {
        currentPage = 1;
    }

    const searchInput = document.getElementById('historySearch');
    const siteFilterSelect = document.getElementById('historySiteFilter');
    const categoryFilterSelect = document.getElementById('historyCategoryFilter');
    const sortSelect = document.getElementById('historySort');

    if (searchInput) {
        currentSearchTerm = searchInput.value;
    }
    if (siteFilterSelect) {
        currentHistorySiteFilter = siteFilterSelect.value;
    }
    if (categoryFilterSelect) {
        currentHistoryCategoryFilter = categoryFilterSelect.value;
    }
    if (sortSelect) {
        currentHistorySort = sortSelect.value;
    }

    const days = parseInt(document.getElementById('historyDays')?.value || '0', 10) || 0;
    const now = Date.now();
    const daysMs = days * 24 * 60 * 60 * 1000;
    const term = normalizeHistoryValue(currentSearchTerm).toLowerCase();

    const filteredRecords = allHistoryRecords.filter(record => {
        const isHidden = Boolean(record.hidden);

        if (currentHistoryVisibility === 'hidden') {
            if (!isHidden) {
                return false;
            }
        } else if (isHidden) {
            return false;
        }

        const siteName = normalizeHistoryValue(record.site_name);
        const category = normalizeHistoryValue(record.category);

        if (currentHistorySiteFilter === FILTER_UNKNOWN_VALUE) {
            if (siteName) {
                return false;
            }
        } else if (currentHistorySiteFilter && siteName !== currentHistorySiteFilter) {
            return false;
        }

        if (currentHistoryCategoryFilter === FILTER_UNKNOWN_VALUE) {
            if (category) {
                return false;
            }
        } else if (currentHistoryCategoryFilter && category !== currentHistoryCategoryFilter) {
            return false;
        }

        if (days > 0) {
            const addedTime = getHistoryRecordTimestamp(record);
            if (addedTime === null || now - addedTime > daysMs) {
                return false;
            }
        }

        if (!term) {
            return true;
        }

        return (
            normalizeHistoryValue(record.title).toLowerCase().includes(term) ||
            siteName.toLowerCase().includes(term) ||
            category.toLowerCase().includes(term)
        );
    });

    const sortedRecords = applyHistorySort(filteredRecords, term);

    totalRecords = sortedRecords.length;
    totalPages = Math.max(1, Math.ceil(totalRecords / page_size));
    if (currentPage > totalPages) {
        currentPage = totalPages;
    }

    const startIndex = (currentPage - 1) * page_size;
    const endIndex = startIndex + page_size;
    currentRecords = sortedRecords.slice(startIndex, endIndex);

    updateHistoryVisibilityButton();
    renderHistoryList('historyList', currentRecords);
}

async function reloadHistoryDataAndRender(resetPage = false) {
    await loadHistoryData({ page: 1, page_size }, true);
    renderHistoryFilterOptions();
    applyHistoryFiltersAndRender(resetPage);
}

/**
 * 加载历史记录（支持分页、搜索、时间筛选）
 * @param {Object} params - 查询参数（page, page_size, search, days）
 * @param {boolean} loadAll - 是否加载所有数据到缓存（用于前端搜索）
 * @returns {Promise<Object>} 历史记录数据
 */
export async function loadHistoryData(params = {}, loadAll = false) {
    try {
        const page = params.page || currentPage;
        const pageSize = params.page_size || page_size;
        const search = loadAll ? '' : (params.search || '');
        const days = loadAll ? 0 : (params.days || 0);
        
        const data = await getHistory({ page, page_size: pageSize, search, days, include_hidden: 1 });
        
        currentPage = data.page || 1;
        page_size = data.page_size || 20;
        totalRecords = data.total || 0;
        totalPages = data.total_pages || 1;
        currentRecords = data.records || [];
        
        // 如果是加载所有数据，保存到缓存
        if (loadAll) {
            // 计算需要加载的总页数
            const totalPageCount = Math.ceil(data.total / pageSize);
            if (totalPageCount > 0) {
                allHistoryRecords = [];
                // 逐页加载所有历史记录（包含隐藏项，前端按当前视图过滤）
                for (let p = 1; p <= totalPageCount; p++) {
                    const pageData = await getHistory({
                        page: p,
                        page_size: pageSize,
                        search: '',
                        days: 0,
                        include_hidden: 1
                    });
                    allHistoryRecords = [...allHistoryRecords, ...(pageData.records || [])];
                }
            } else {
                allHistoryRecords = [];
            }
        }
        
        // 更新分页按钮状态
        updatePaginationButtons();
        
        return data;
    } catch (e) {
        console.error('Load history error:', e);
        throw e;
    }
}

/**
 * 渲染历史记录列表
 * @param {string} containerId - 容器 ID
 * @param {Array} records - 记录列表
 */
export function renderHistoryList(containerId, records = currentRecords) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    if (!records || records.length === 0) {
        const emptyText = currentHistoryVisibility === 'hidden' ? '暂无隐藏记录' : '暂无历史记录';
        const emptyHint = currentHistoryVisibility === 'hidden'
            ? '被“仅从列表隐藏”的记录会显示在这里，可按需恢复。'
            : '下载的种子将显示在这里';
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon"><i data-lucide="inbox" class="icon-xl"></i></div>
                <div class="empty-text">${emptyText}</div>
                <div class="empty-hint">${emptyHint}</div>
            </div>
        `;
        updateSelectedCount();
        refreshLucideIcons();
        return;
    }
    
    const html = records.map(record => {
        const { id, title, hash, site_name, category, size, status, added_at, completed_time, hidden } = record;
        const deletedAt = record.deleted_at;
        const deletedReason = record.deleted_reason;
        const deletedFromStatus = normalizeHistoryValue(record.deleted_from_status);
        const deletedReasonText = formatDeletedReason(deletedReason);
        const timeAgo = formatRelativeTime(added_at);
        const categoryText = category || '未知类型';
        // 状态标签
        const statusLabels = {
            'downloading': { text: '下载中', tone: 'blue', icon: 'download' },
            'completed': { text: '已完成', tone: 'green', icon: 'check' },
            'seeding': { text: '做种中', tone: 'green', icon: 'upload' },
            'paused': { text: '已暂停', tone: 'yellow', icon: 'pause' },
            'deleted': { text: '已删除', tone: 'red', icon: 'trash-2' }
        };
        const statusInfo = statusLabels[status] || statusLabels['downloading'];
        
        // 格式化大小
        const formatSize = (size) => {
            if (!size || size <= 0) return '未知大小';
            if (size < 1) return `${(size * 1024).toFixed(0)} MB`;
            return `${size.toFixed(2)} GB`;
        };
        
        // 格式化完成时间
        const formatCompleted = (time) => {
            if (!time) return '';
            try {
                return `${formatRelativeTime(time)}完成`;
            } catch (e) {
                return '';
            }
        };

        const formatDeletedTime = (time) => {
            if (!time) return '';
            try {
                return `${formatRelativeTime(time)}删除`;
            } catch (e) {
                return '';
            }
        };
        const showDeletedTime = Boolean(
            deletedAt && ['downloading', 'paused'].includes(deletedFromStatus)
        );
        
        return `
            <div class="history-item history-item-${escapeHtml(status || 'downloading')}" data-id="${escapeHtml(id)}">
                <input type="checkbox" data-id="${escapeHtml(id)}" onclick="event.stopPropagation()" onchange="updateSelectedCount()">
                <div class="history-info">
                    <div class="history-title-row">
                        <span class="status-badge status-badge-history status-badge-${statusInfo.tone}">
                            <i data-lucide="${statusInfo.icon}" class="icon-sm"></i>
                            ${statusInfo.text}
                        </span>
                        <span class="history-title-text" title="${escapeHtml(title)}">${escapeHtml(title)}</span>
                    </div>
                    <div class="history-meta history-meta-primary">
                        <span class="meta-site meta-chip meta-chip-accent">
                            <i data-lucide="globe" class="icon-sm"></i>
                            ${escapeHtml(site_name || '未知站点')}
                        </span>
                        ${deletedAt ? `
                            <span class="meta-delete-reason meta-chip meta-chip-warning" title="${escapeHtml(deletedReasonText)}">
                                <i data-lucide="tag" class="icon-sm"></i>
                                ${escapeHtml(deletedReasonText)}
                            </span>
                            ${showDeletedTime ? `
                            <span class="meta-delete-time meta-chip meta-chip-success" title="${escapeHtml(formatDateTime(deletedAt))}">
                                <i data-lucide="clock-3" class="icon-sm"></i>
                                ${escapeHtml(formatDeletedTime(deletedAt))}
                            </span>
                            ` : ''}
                        ` : ''}
                        ${completed_time ? `
                            <span class="meta-completed meta-chip meta-chip-success">
                                <i data-lucide="check" class="icon-sm"></i>
                                ${escapeHtml(formatCompleted(completed_time))}
                            </span>
                        ` : ''}
                        ${hidden ? `
                            <span class="meta-hidden meta-chip">
                                <i data-lucide="eye-off" class="icon-sm"></i>
                                已隐藏
                            </span>
                        ` : ''}
                        <span class="meta-category meta-chip">
                            <i data-lucide="tag" class="icon-sm"></i>
                            ${escapeHtml(categoryText)}
                        </span>
                        <span class="meta-size meta-chip">
                            <i data-lucide="package" class="icon-sm"></i>
                            ${formatSize(size)}
                        </span>
                        <span class="meta-time meta-chip">
                            <i data-lucide="calendar" class="icon-sm"></i>
                            ${formatDateTime(added_at)}
                        </span>
                        <span class="meta-ago meta-chip">
                            <i data-lucide="clock-3" class="icon-sm"></i>
                            ${escapeHtml(timeAgo)}
                        </span>
                    </div>
                </div>
                <button class="btn btn-secondary btn-sm history-delete-btn" onclick="deleteOne('${escapeHtml(id)}', event)" title="删除记录">
                    <i data-lucide="trash-2" class="icon-sm"></i>
                </button>
            </div>
        `;
    }).join('');
    
    container.innerHTML = html;
    
    // 为每个卡片添加点击事件（整卡点击切换复选框）
    container.querySelectorAll('.history-item').forEach(item => {
        item.addEventListener('click', (event) => {
            // 排除删除按钮和复选框点击
            if (event.target.closest('.history-delete-btn') || event.target.closest('input[type="checkbox"]')) {
                return;
            }
            const checkbox = item.querySelector('input[type="checkbox"]');
            if (checkbox) {
                checkbox.checked = !checkbox.checked;
                updateSelectedCount();
            }
        });
    });
    
    updateSelectedCount();
    refreshLucideIcons();
    
    // 更新分页信息
    updatePaginationInfo();
}

/**
 * 点击历史记录项切换复选框（点击整个卡片）
 * @param {Event} event - 点击事件
 * @param {string} id - 记录 ID
 */
export function toggleHistoryItem(event, id) {
    // 阻止事件冒泡
    event.stopPropagation();
    
    // 查找复选框并切换状态
    const checkbox = document.querySelector(`#historyList input[type="checkbox"][data-id="${id}"]`);
    if (checkbox) {
        checkbox.checked = !checkbox.checked;
        updateSelectedCount();
    }
}

/**
 * 根据 ID 切换选中状态（兼容旧版）
 * @param {string} id - 记录 ID
 * @param {Event} event - 点击事件
 */
export function toggleSelectByTitle(id, event) {
    if (event) event.stopPropagation();
    
    const checkbox = document.querySelector(`#historyList input[type="checkbox"][data-id="${id}"]`);
    if (checkbox) {
        checkbox.checked = !checkbox.checked;
        updateSelectedCount();
    }
}

/**
 * 更新分页信息
 */
function updatePaginationInfo() {
    const totalEl = document.getElementById('historyTotal');
    const currentPageEl = document.getElementById('currentPage');
    const totalPagesEl = document.getElementById('totalPages');
    const pageNumEl = document.getElementById('currentPageNum');
    const totalPageNumEl = document.getElementById('totalPageNum');
    
    if (totalEl) totalEl.textContent = totalRecords;
    if (currentPageEl) currentPageEl.textContent = currentPage;
    if (totalPagesEl) totalPagesEl.textContent = totalPages;
    if (pageNumEl) pageNumEl.textContent = currentPage;
    if (totalPageNumEl) totalPageNumEl.textContent = totalPages;
    
    // 更新分页按钮状态
    updatePaginationButtons();
}

/**
 * 更新分页按钮状态
 */
export function updatePaginationButtons() {
    const firstBtn = document.getElementById('firstPageBtn');
    const prevBtn = document.getElementById('prevPageBtn');
    const nextBtn = document.getElementById('nextPageBtn');
    const lastBtn = document.getElementById('lastPageBtn');
    
    // 更新首页/上一页按钮
    if (firstBtn && prevBtn) {
        const disabled = currentPage <= 1;
        firstBtn.disabled = disabled;
        prevBtn.disabled = disabled;
    }
    
    // 更新下一页/末页按钮
    if (nextBtn && lastBtn) {
        const disabled = currentPage >= totalPages;
        nextBtn.disabled = disabled;
        lastBtn.disabled = disabled;
    }
}

/**
 * 跳转到指定页
 * @param {number} page - 页码
 */
export function goToPage(page) {
    if (page < 1 || page > totalPages) {
        return;
    }

    currentPage = page;
    applyHistoryFiltersAndRender(false);
}

/**
 * 上一页
 */
export function prevPage() {
    if (currentPage > 1) {
        goToPage(currentPage - 1);
    }
}

/**
 * 下一页
 */
export function nextPage() {
    if (currentPage < totalPages) {
        goToPage(currentPage + 1);
    }
}

/**
 * 到首页
 */
export function goToFirstPage() {
    goToPage(1);
}

/**
 * 到末页
 */
export function goToLastPage() {
    goToPage(totalPages);
}

/**
 * 更改每页数量
 */
export function changePageSize() {
    const pageSizeEl = document.getElementById('historyPageSize');
    if (pageSizeEl) {
        page_size = parseInt(pageSizeEl.value, 10) || 20;
        currentPage = 1;
        applyHistoryFiltersAndRender(false);
    }
}

/**
 * 全选/取消全选
 * @param {HTMLInputElement} checkbox - 全选复选框
 */
export function toggleAll(checkbox) {
    const items = document.querySelectorAll('#historyList input[type="checkbox"]');
    items.forEach(item => item.checked = checkbox.checked);
    updateSelectedCount();
}

/**
 * 反选
 */
export function invertSelection() {
    const items = document.querySelectorAll('#historyList input[type="checkbox"]');
    items.forEach(item => item.checked = !item.checked);
    updateSelectedCount();
}

/**
 * 更新选中数量
 */
export function updateSelectedCount() {
    const checkboxes = Array.from(document.querySelectorAll('#historyList input[type="checkbox"]'));
    const count = checkboxes.filter(item => item.checked).length;
    const countEl = document.getElementById('selectedCount');
    const countDisplayEl = document.getElementById('selectedCountDisplay');
    const selectAllCheckbox = document.getElementById('selectAllCheckbox');
    
    if (countEl) countEl.textContent = count;
    if (countDisplayEl) countDisplayEl.textContent = count;
    if (selectAllCheckbox) {
        selectAllCheckbox.checked = checkboxes.length > 0 && count === checkboxes.length;
        selectAllCheckbox.indeterminate = count > 0 && count < checkboxes.length;
    }

    syncHistorySelectionClasses();
}

/**
 * 删除单条记录
 * @param {string} id - 记录 ID
 * @param {Event} event - 点击事件
 */
export async function deleteOne(id, event) {
    if (event) event.stopPropagation();
    
    // 使用自定义模态框确认
    if (window.showConfirmModal) {
        showConfirmModal(
            '🗑️ 删除确认',
            '确定要删除这条记录吗？',
            '删除后该种子的历史记录将被清除，允许重新下载。',
            async () => {
                await doDeleteOne(id);
            }
        );
    } else {
        // Fallback: 如果没有模态框，直接删除
        await doDeleteOne(id);
    }
}

/**
 * 执行删除单条记录
 * @param {string} id - 记录 ID
 */
async function doDeleteOne(id) {
    try {
        const result = await deleteHistoryApi([id]);
        if (result.success) {
            if (window.showToast) {
                showToast(`删除成功`, 'success');
            }
            await reloadHistoryDataAndRender(true);
            
            // 触发自定义事件，通知预览模块刷新
            window.dispatchEvent(new CustomEvent('historyDeleted', { detail: { ids: [id] } }));
        } else {
            if (window.showToast) {
                showToast(`删除失败：${result.message}`, 'error');
            }
        }
    } catch (e) {
        console.error('Delete one error:', e);
        if (window.showToast) {
            showToast(`删除失败：${e.message}`, 'error');
        }
    }
}

/**
 * 隐藏选中的记录（仅从列表隐藏，不删除种子）
 */
export async function hideSelected() {
    const items = document.querySelectorAll('#historyList input[type="checkbox"]:checked');
    if (items.length === 0) {
        if (window.showToast) {
            showToast('请先选择要隐藏的记录', 'warning');
        }
        return;
    }

    const ids = Array.from(items).map(item => item.dataset.id);
    const count = ids.length;

    try {
        const result = await apiPost('/api/history/hide', { ids: ids });

        if (result.success) {
            if (window.showToast) {
                showToast(`成功隐藏 ${result.hidden} 条记录`, 'success');
            }
            await reloadHistoryDataAndRender(true);
        } else {
            if (window.showToast) {
                showToast(`隐藏失败：${result.message}`, 'error');
            }
        }
    } catch (e) {
        console.error('Hide selected error:', e);
        if (window.showToast) {
            showToast(`隐藏失败：${e.message}`, 'error');
        }
    }
}

/**
 * 将隐藏列表中已勾选的记录恢复到主列表
 */
export async function restoreAllHidden() {
    if (currentHistoryVisibility !== 'hidden') {
        if (window.showToast) {
            showToast('请先切换到隐藏列表，再勾选要恢复到列表的记录', 'warning');
        }
        return;
    }

    const selectedItems = Array.from(document.querySelectorAll('#historyList input[type="checkbox"]:checked'));
    const selectedIds = selectedItems.map(item => item.dataset.id).filter(Boolean);

    if (selectedIds.length === 0) {
        if (window.showToast) {
            showToast('请先勾选要恢复到列表的记录', 'warning');
        }
        return;
    }

    try {
        const result = await apiPost('/api/history/restore', { ids: selectedIds });

        if (result.success) {
            if (window.showToast) {
                showToast(`成功将选中的 ${result.restored} 条记录恢复到列表`, 'success');
            }
            await reloadHistoryDataAndRender(true);
        } else {
            if (window.showToast) {
                showToast(`恢复到列表失败：${result.message}`, 'error');
            }
        }
    } catch (e) {
        console.error('Restore all error:', e);
        if (window.showToast) {
            showToast(`恢复到列表失败：${e.message}`, 'error');
        }
    }
}

export function toggleHistoryHiddenView() {
    currentHistoryVisibility = currentHistoryVisibility === 'hidden' ? 'visible' : 'hidden';
    currentPage = 1;
    applyHistoryFiltersAndRender(false);
    refreshLucideIcons();
}

/**
 * 删除选中的记录
 */
export async function deleteSelected() {
    const items = document.querySelectorAll('#historyList input[type="checkbox"]:checked');
    if (items.length === 0) {
        if (window.showToast) {
            showToast('请先选择要彻底删除的记录', 'warning');
        }
        return;
    }
    
    const ids = Array.from(items).map(item => item.dataset.id);
    const count = ids.length;
    
    // 使用自定义模态框确认
    if (window.showConfirmModal) {
        showConfirmModal(
            '🗑️ 彻底删除确认',
            `确定要彻底删除选中的 ${count} 条记录吗？`,
            '彻底删除后，这些种子的历史记录会被移除，之后允许重新下载。\n\n此操作不可恢复。',
            async () => {
                await doDeleteSelected(ids);
            }
        );
    } else {
        // Fallback
        await doDeleteSelected(ids);
    }
}

/**
 * 执行删除选中的记录
 * @param {Array<string>} ids - 记录 ID 数组
 */
async function doDeleteSelected(ids) {
    try {
        const result = await deleteHistoryApi(ids);
        if (result.success) {
            if (window.showToast) {
                showToast(`成功彻底删除 ${result.deleted} 条记录`, 'success');
            }
            await reloadHistoryDataAndRender(true);
            
            // 触发自定义事件，通知预览模块刷新
            window.dispatchEvent(new CustomEvent('historyDeleted', { detail: { ids: ids } }));
        } else {
            if (window.showToast) {
                showToast(`彻底删除失败：${result.message}`, 'error');
            }
        }
    } catch (e) {
        console.error('Delete selected error:', e);
        if (window.showToast) {
            showToast(`彻底删除失败：${e.message}`, 'error');
        }
    }
}

/**
 * 动态搜索（前端匹配，实时更新）
 * 输入时即时过滤全部历史记录（从缓存中搜索）
 * @param {string} searchTerm - 搜索关键词
 */
export function searchHistoryDynamic(searchTerm) {
    currentSearchTerm = searchTerm || '';
    
    // 清除之前的定时器
    if (searchTimer) clearTimeout(searchTimer);
    
    // 防抖 150ms，减少频繁渲染
    searchTimer = setTimeout(() => {
        currentPage = 1;
        applyHistoryFiltersAndRender(false);
    }, 150);
}

/**
 * 过滤（组合搜索 + 时间/站点/类型/排序）
 */
export function filterHistory() {
    currentPage = 1;
    applyHistoryFiltersAndRender(false);
}

/**
 * 加载历史记录（兼容旧版）
 * @deprecated 使用 loadHistoryData 代替
 */
export async function loadHistory() {
    await reloadHistoryDataAndRender(true);
}

// ==================== 导出全局函数 ====================
// 在模块加载时导出所有需要供 HTML onclick 使用的函数
// 必须在这里导出，因为函数定义都在前面
if (typeof window !== 'undefined') {
    // 分页相关
    window.goToPage = goToPage;
    window.prevPage = prevPage;
    window.nextPage = nextPage;
    window.goToFirstPage = goToFirstPage;
    window.goToLastPage = goToLastPage;
    window.changePageSize = changePageSize;
    window.updatePaginationButtons = updatePaginationButtons;
    
    // 历史记录操作
    window.toggleAll = toggleAll;
    window.invertSelection = invertSelection;
    window.updateSelectedCount = updateSelectedCount;
    window.deleteOne = deleteOne;
    window.deleteSelected = deleteSelected;
    window.toggleHistoryItem = toggleHistoryItem;
    window.toggleSelectByTitle = toggleSelectByTitle;
    
    // 搜索和过滤
    window.searchHistoryDynamic = searchHistoryDynamic;
    window.filterHistory = filterHistory;
    window.toggleHistoryHiddenView = toggleHistoryHiddenView;
    
    // 数据加载和渲染
    window.loadHistoryData = loadHistoryData;
    window.renderHistoryList = renderHistoryList;
    window.loadHistory = loadHistory;
}
