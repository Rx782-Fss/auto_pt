// 从 utils.js 导入工具函数
import { escapeHtml, formatDateTime } from './utils.js';

// 从 api.js 导入 API 函数
import { downloadSingle, downloadTorrents, previewTorrents } from './api.js?v=174';

// 预览数据缓存
let previewCache = {
    torrents: {},
    newTorrents: [],
    downloadedTorrents: []
};

// 搜索相关变量
let previewSearchTimer = null;
let currentPreviewSearchTerm = '';
let currentPreviewSiteFilter = '';
let currentPreviewCategoryFilter = '';
let currentPreviewSort = 'default';

// 预览框分页配置
let previewCurrentPage = 1;
let previewPageSize = 20;
let previewTotalPages = 1;
let previewCurrentRecords = [];

const FILTER_ALL_VALUE = '';
const FILTER_UNKNOWN_VALUE = '__unknown__';

function refreshLucideIcons() {
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

function normalizePreviewValue(value) {
    return String(value || '').trim();
}

function getPreviewTimestamp(torrent) {
    if (!torrent?.pub_date) {
        return null;
    }
    const timestamp = new Date(torrent.pub_date).getTime();
    return Number.isFinite(timestamp) ? timestamp : null;
}

function getPreviewSize(torrent) {
    const size = Number(torrent?.size);
    return Number.isFinite(size) && size > 0 ? size : null;
}

function comparePreviewSearchPriority(a, b, term) {
    const aTitle = normalizePreviewValue(a.title).toLowerCase();
    const bTitle = normalizePreviewValue(b.title).toLowerCase();
    const aSite = normalizePreviewValue(a.site_name).toLowerCase();
    const bSite = normalizePreviewValue(b.site_name).toLowerCase();
    const aCategory = normalizePreviewValue(a.category).toLowerCase();
    const bCategory = normalizePreviewValue(b.category).toLowerCase();

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

function compareNullablePreviewValues(aValue, bValue, descending) {
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

function resetPreviewViewState() {
    currentPreviewSearchTerm = '';
    currentPreviewSiteFilter = FILTER_ALL_VALUE;
    currentPreviewCategoryFilter = FILTER_ALL_VALUE;
    currentPreviewSort = 'default';
    previewCurrentPage = 1;
}

function buildPreviewFilterOptions(values, selectedValue, allLabel, unknownLabel, includeUnknown) {
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

function getAllPreviewTorrents() {
    return [...previewCache.newTorrents, ...previewCache.downloadedTorrents];
}

function filterAndSortPreviewTorrents(torrents) {
    const term = normalizePreviewValue(currentPreviewSearchTerm).toLowerCase();

    const filtered = torrents.filter(torrent => {
        const title = normalizePreviewValue(torrent.title).toLowerCase();
        const siteName = normalizePreviewValue(torrent.site_name);
        const category = normalizePreviewValue(torrent.category);
        const siteNameLower = siteName.toLowerCase();
        const categoryLower = category.toLowerCase();

        if (currentPreviewSiteFilter === FILTER_UNKNOWN_VALUE) {
            if (siteName) {
                return false;
            }
        } else if (currentPreviewSiteFilter && siteName !== currentPreviewSiteFilter) {
            return false;
        }

        if (currentPreviewCategoryFilter === FILTER_UNKNOWN_VALUE) {
            if (category) {
                return false;
            }
        } else if (currentPreviewCategoryFilter && category !== currentPreviewCategoryFilter) {
            return false;
        }

        if (!term) {
            return true;
        }

        return (
            title.includes(term) ||
            siteNameLower.includes(term) ||
            categoryLower.includes(term)
        );
    });

    if (currentPreviewSort === 'default') {
        if (!term) {
            return filtered;
        }
        return filtered.sort((a, b) => comparePreviewSearchPriority(a, b, term));
    }

    return filtered.sort((a, b) => {
        switch (currentPreviewSort) {
            case 'time_desc':
                return compareNullablePreviewValues(getPreviewTimestamp(a), getPreviewTimestamp(b), true);
            case 'time_asc':
                return compareNullablePreviewValues(getPreviewTimestamp(a), getPreviewTimestamp(b), false);
            case 'size_desc':
                return compareNullablePreviewValues(getPreviewSize(a), getPreviewSize(b), true);
            case 'size_asc':
                return compareNullablePreviewValues(getPreviewSize(a), getPreviewSize(b), false);
            default:
                return 0;
        }
    });
}

/**
 * 渲染预览框工具栏（完全按照历史记录布局）
 */
export function renderPreviewToolbar() {
    const container = document.getElementById('torrentPreviewList');
    if (!container) return;

    const allTorrents = getAllPreviewTorrents();
    const categoryValues = Array.from(
        new Set(allTorrents.map(torrent => normalizePreviewValue(torrent.category)).filter(Boolean))
    ).sort((a, b) => a.localeCompare(b));
    const hasUnknownCategory = allTorrents.some(torrent => !normalizePreviewValue(torrent.category));
    currentPreviewSiteFilter = FILTER_ALL_VALUE;

    const categoryOptions = buildPreviewFilterOptions(
        categoryValues,
        currentPreviewCategoryFilter,
        '类型',
        '未知类型',
        hasUnknownCategory
    );
    currentPreviewCategoryFilter = categoryOptions.selectedValue;

    const toolbarHtml = `
        <!-- 搜索工具栏 -->
        <div class="history-toolbar history-toolbar-compact preview-toolbar">
            <input type="text" id="previewSearch" placeholder="搜索标题 / 类型" 
                   class="toolbar-search-input toolbar-search-input-wide record-toolbar-search"
                   value="${escapeHtml(currentPreviewSearchTerm)}"
                   oninput="searchPreviewDynamic(this.value)"/>
            <select id="previewCategoryFilter" class="toolbar-select record-toolbar-select record-toolbar-select-category" onchange="filterPreviewByCategory(this.value)" title="按种子类型过滤">
                ${categoryOptions.optionsHtml}
            </select>
            <select id="previewSort" class="toolbar-select record-toolbar-select record-toolbar-select-sort" onchange="sortPreviewRecords(this.value)" title="排序方式">
                <option value="default"${currentPreviewSort === 'default' ? ' selected' : ''}>排序</option>
                <option value="time_desc"${currentPreviewSort === 'time_desc' ? ' selected' : ''}>最新</option>
                <option value="time_asc"${currentPreviewSort === 'time_asc' ? ' selected' : ''}>最早</option>
                <option value="size_desc"${currentPreviewSort === 'size_desc' ? ' selected' : ''}>最大</option>
                <option value="size_asc"${currentPreviewSort === 'size_asc' ? ' selected' : ''}>最小</option>
            </select>
            <select id="previewPageSize" class="toolbar-select record-toolbar-select record-toolbar-select-page" onchange="changePreviewPageSize()" title="每页条数">
                <option value="10"${previewPageSize === 10 ? ' selected' : ''}>10/页</option>
                <option value="20"${previewPageSize === 20 ? ' selected' : ''}>20/页</option>
                <option value="50"${previewPageSize === 50 ? ' selected' : ''}>50/页</option>
                <option value="100"${previewPageSize === 100 ? ' selected' : ''}>100/页</option>
            </select>
        </div>
        
        <!-- 操作栏 -->
        <div class="history-batch-bar preview-batch-bar">
            <div class="toolbar-inline-group">
                <label class="toolbar-check-label">
                    <input type="checkbox" id="previewSelectAllCheckbox" class="toolbar-check-input" onchange="togglePreviewAll(this)">
                    全选
                </label>
                <button class="btn btn-secondary btn-compact" onclick="togglePreviewInvert()">反选</button>
            </div>
            <div class="toolbar-meta">
                共 <span id="previewTotal">0</span> 条 | 已选 <span id="previewSelectedCount">0</span> 条
            </div>
        </div>
        
        <!-- 列表区 -->
        <div id="previewListContent" class="preview-list-shell"></div>
        
        <!-- 分页栏 -->
        <div class="history-pagination-bar preview-pagination-bar">
            <div class="toolbar-meta">
                第 <span id="previewCurrentPage">1</span> / <span id="previewTotalPages">1</span> 页
            </div>
            <div class="toolbar-actions-compact">
                <button class="btn btn-secondary btn-compact" onclick="goToPreviewPage(1)" id="previewFirstPageBtn" disabled><i data-lucide="chevrons-left" class="icon-sm"></i></button>
                <button class="btn btn-secondary btn-compact" onclick="goToPreviewPrevPage()" id="previewPrevPageBtn" disabled><i data-lucide="chevron-left" class="icon-sm"></i> 上一页</button>
                <button class="btn btn-secondary btn-compact" onclick="goToPreviewNextPage()" id="previewNextPageBtn" disabled>下一页 <i data-lucide="chevron-right" class="icon-sm"></i></button>
                <button class="btn btn-secondary btn-compact" onclick="goToPreviewLastPage()" id="previewLastPageBtn" disabled><i data-lucide="chevrons-right" class="icon-sm"></i></button>
            </div>
        </div>
    `;
    
    container.innerHTML = toolbarHtml;
    
    // 重新渲染 lucide 图标
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

/**
 * 预览框动态搜索（前端匹配，实时更新）
 * 输入时即时过滤所有预览种子（从缓存中搜索）
 * @param {string} searchTerm - 搜索关键词
 */
export function searchPreviewDynamic(searchTerm) {
    currentPreviewSearchTerm = searchTerm || '';
    previewCurrentPage = 1;
    
    // 清除之前的定时器
    if (previewSearchTimer) clearTimeout(previewSearchTimer);
    
    // 防抖 150ms，减少频繁渲染
    previewSearchTimer = setTimeout(() => {
        // 重新渲染列表（会自动过滤）
        renderPreviewList('torrentPreviewList');
    }, 150);
}

export function filterPreviewBySite(siteName) {
    currentPreviewSiteFilter = siteName || FILTER_ALL_VALUE;
    previewCurrentPage = 1;
    renderPreviewList('torrentPreviewList');
}

export function filterPreviewByCategory(category) {
    currentPreviewCategoryFilter = category || FILTER_ALL_VALUE;
    previewCurrentPage = 1;
    renderPreviewList('torrentPreviewList');
}

export function sortPreviewRecords(sortMode) {
    currentPreviewSort = sortMode || 'default';
    previewCurrentPage = 1;
    renderPreviewList('torrentPreviewList');
}

/**
 * 更新选中种子数量显示
 */
export function updateSelectedCountInModal() {
    const count = document.querySelectorAll('#torrentPreviewList input[type="checkbox"]:checked:not(:disabled)').length;
    const countEl = document.getElementById('previewSelectedCount') || document.getElementById('selectedTorrentCount');
    const btnCountEl = document.getElementById('btnSelectedCount');
    const downloadBtn = document.getElementById('downloadBtn');
    
    if (countEl) countEl.textContent = count;
    if (btnCountEl) btnCountEl.textContent = count;
    if (downloadBtn) {
        downloadBtn.classList.toggle('is-hidden', count === 0);
        downloadBtn.disabled = count === 0;
    }
}

/**
 * 渲染单个种子项
 * @param {Object} torrent - 种子数据
 * @param {boolean} downloaded - 是否已下载
 * @param {Function} isDownloadedCallback - 判断是否已下载的回调
 * @returns {string} HTML 内容
 */
function renderTorrentItem(torrent, downloaded, isDownloadedCallback = null) {
    const isDownloaded = isDownloadedCallback ? isDownloadedCallback(torrent.id) : downloaded;
    const statusClass = isDownloaded ? 'downloaded' : 'new';
    
    return `
        <div class="torrent-item ${statusClass}" onclick="toggleTorrentSelection('${torrent.id}', event)">
            <input type="checkbox" data-id="${torrent.id}" data-title="${torrent.title}" data-link="${torrent.link}" data-site_name="${torrent.site_name || ''}" data-category="${torrent.category || ''}" data-size="${torrent.size || 0}" data-downloaded="${isDownloaded}" onclick="event.stopPropagation(); toggleCheckboxHighlight(this); updateSelectedCountInModal()">
            <div class="torrent-info">
                <div class="torrent-title-row">
                    <div class="torrent-title">${escapeHtml(torrent.title)}</div>
                    ${isDownloaded
                        ? `
                            <span class="status-badge preview-status-badge status-badge-green downloaded">
                                <i data-lucide="check" class="icon-sm"></i>
                                已下载
                            </span>
                        `
                        : `
                            <span class="status-badge preview-status-badge status-badge-blue new">
                                <i data-lucide="download" class="icon-sm"></i>
                                新种子
                            </span>
                        `}
                </div>
                <div class="torrent-meta">
                    ${torrent.site_name ? `
                        <span class="site-badge meta-chip meta-chip-accent">
                            <i data-lucide="globe" class="icon-sm"></i>
                            ${escapeHtml(torrent.site_name)}
                        </span>
                    ` : ''}
                    <span class="meta-item meta-chip">
                        <i data-lucide="calendar" class="icon-sm"></i>
                        ${torrent.pub_date ? formatDateTime(torrent.pub_date) : '未知'}
                    </span>
                    ${typeof torrent.size === 'number' && torrent.size >= 0 ? `
                        <span class="meta-item meta-chip">
                            <i data-lucide="package" class="icon-sm"></i>
                            ${torrent.size.toFixed(2)} GB
                        </span>
                    ` : ''}
                    ${torrent.category ? `
                        <span class="meta-item meta-chip">
                            <i data-lucide="tag" class="icon-sm"></i>
                            ${escapeHtml(torrent.category)}
                        </span>
                    ` : ''}
                </div>
            </div>
        </div>
    `;
}

/**
 * 切换种子选择状态
 * @param {string} torrentId - 种子 ID
 * @param {Event} event - 点击事件
 */
export function toggleTorrentSelection(torrentId, event) {
    if (event.target.tagName === 'INPUT' && event.target.type === 'checkbox') {
        return;
    }
    
    const checkbox = document.querySelector(`#torrentPreviewList input[data-id="${torrentId}"]`);
    if (checkbox) {
        checkbox.checked = !checkbox.checked;
        toggleCheckboxHighlight(checkbox);
        updateSelectedCountInModal();
    }
}

/**
 * 切换 checkbox 高亮
 * @param {HTMLInputElement} checkbox - checkbox 元素
 */
function toggleCheckboxHighlight(checkbox) {
    const torrentItem = checkbox.closest('.torrent-item');
    if (torrentItem) {
        if (checkbox.checked) {
            torrentItem.classList.add('selected');
        } else {
            torrentItem.classList.remove('selected');
        }
    }
}

/**
 * 获取种子预览数据
 * @returns {Promise<Object>} 预览数据
 */
export async function loadPreviewData() {
    try {
        const data = await previewTorrents();
        
        if (data.success) {
            previewCache.newTorrents = data.torrents?.new || [];
            previewCache.downloadedTorrents = data.torrents?.downloaded || [];
            
            // 构建 ID 到种子的映射
            previewCache.torrents = {};
            [...previewCache.newTorrents, ...previewCache.downloadedTorrents].forEach(t => {
                previewCache.torrents[t.id] = t;
            });
        }
        
        return data;
    } catch (e) {
        console.error('Load preview error:', e);
        throw e;
    }
}

/**
 * 获取选中的种子 ID 列表
 * @param {string} containerId - 容器 ID
 * @returns {Array<Object>} 选中的种子数据
 */
export function getSelectedTorrents(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return [];
    
    const checkboxes = container.querySelectorAll('input[type="checkbox"]:checked:not(:disabled)');
    return Array.from(checkboxes).map(cb => ({
        id: cb.dataset.id,
        title: cb.dataset.title,
        link: cb.dataset.link,
        site_name: cb.dataset.site_name || '',
        category: cb.dataset.category || '',
        size: parseFloat(cb.dataset.size) || 0
    }));
}

/**
 * 下载单个种子
 * @param {string} torrentId - 种子 ID
 * @param {string} title - 种子标题
 * @param {string} link - 种子链接
 * @param {string} site_name - 站点名称
 * @param {number} size - 种子大小
 * @returns {Promise<Object>} 响应数据
 */
export async function downloadSingleTorrent(torrentId, title, link, site_name = '', size = 0, category = '') {
    try {
        return await downloadSingle({
            id: torrentId,
            title: title,
            link: link,
            site_name: site_name,
            category: category,
            size: size
        });
    } catch (e) {
        console.error('Download single error:', e);
        throw e;
    }
}

/**
 * 下载多个种子
 * @param {Array<Object>} torrents - 种子数据数组
 * @returns {Promise<Object>} 响应数据
 */
export async function downloadMultipleTorrents(torrents) {
    try {
        return await downloadTorrents(torrents);
    } catch (e) {
        console.error('Download multiple error:', e);
        throw e;
    }
}

/**
 * 更新种子状态
 * @param {string} torrentId - 种子 ID
 * @param {boolean} isDownloaded - 是否已下载
 */
export function updateTorrentStatus(torrentId, isDownloaded) {
    const torrent = previewCache.torrents[torrentId];
    if (!torrent) return;
    
    if (isDownloaded) {
        // 从新种子移到已下载
        const index = previewCache.newTorrents.findIndex(t => t.id === torrentId);
        if (index > -1) {
            previewCache.newTorrents.splice(index, 1);
            previewCache.downloadedTorrents.push(torrent);
        }
    }
    
    renderPreviewList('torrentPreviewList');
}

/**
 * 清除预览缓存
 */
export function clearPreviewCache() {
    previewCache = {
        torrents: {},
        newTorrents: [],
        downloadedTorrents: []
    };
    resetPreviewViewState();
}

/**
 * 获取统计信息
 * @returns {Object} 统计信息
 */
export function getStats() {
    return {
        newCount: previewCache.newTorrents.length,
        downloadedCount: previewCache.downloadedTorrents.length,
        totalCount: previewCache.newTorrents.length + previewCache.downloadedTorrents.length
    };
}

/**
 * 更新预览缓存
 * @param {Object} data - 预览数据
 */
export function updatePreviewCache(data) {
    if (data.success) {
        previewCache.newTorrents = data.torrents?.new || [];
        previewCache.downloadedTorrents = data.torrents?.downloaded || [];
        
        // 构建 ID 到种子的映射
        previewCache.torrents = {};
        [...previewCache.newTorrents, ...previewCache.downloadedTorrents].forEach(t => {
            previewCache.torrents[t.id] = t;
        });
        resetPreviewViewState();
    }
}

/**
 * 询问是否重新下载
 * @param {string} torrentId - 种子 ID
 */
export function askRedownload(torrentId) {
    const torrent = previewCache.torrents[torrentId];
    if (!torrent) return;
    
    if (confirm(`确定要重新下载 "${torrent.title}" 吗？`)) {
        downloadSingleTorrent(torrent.id, torrent.title, torrent.link, torrent.site_name, torrent.size, torrent.category)
            .then(() => {
                updateTorrentStatus(torrent.id, true);
                if (typeof showToast === 'function') {
                    showToast('已重新下载', 'success');
                }
            })
            .catch(e => {
                if (typeof showToast === 'function') {
                    showToast('下载失败：' + e.message, 'error');
                }
            });
    }
}

// ==================== 分页功能 ====================

/**
 * 更改每页显示数量
 */
export function changePreviewPageSize() {
    const select = document.getElementById('previewPageSize');
    previewPageSize = parseInt(select.value, 10) || 20;
    previewCurrentPage = 1;
    renderPreviewList('torrentPreviewList');
}

/**
 * 渲染预览列表（支持分页）
 */
export function renderPreviewList(containerId, isDownloadedCallback = null) {
    const contentContainer = document.getElementById('previewListContent');
    if (!contentContainer) return;
    
    const { newTorrents, downloadedTorrents } = previewCache;

    const displayNewTorrents = filterAndSortPreviewTorrents(newTorrents);
    const displayDownloadedTorrents = filterAndSortPreviewTorrents(downloadedTorrents);
    
    // 合并所有种子
    const allTorrents = [
        ...displayNewTorrents.map(t => ({ ...t, _isDownloaded: false })),
        ...displayDownloadedTorrents.map(t => ({ ...t, _isDownloaded: true }))
    ];
    
    // 更新总数和分页
    previewTotalPages = Math.max(1, Math.ceil(allTorrents.length / previewPageSize));
    if (previewCurrentPage > previewTotalPages) {
        previewCurrentPage = previewTotalPages;
    }
    
    // 计算当前页的数据
    const startIndex = (previewCurrentPage - 1) * previewPageSize;
    const endIndex = Math.min(startIndex + previewPageSize, allTorrents.length);
    previewCurrentRecords = allTorrents.slice(startIndex, endIndex);
    
    // 更新总数显示
    const totalEl = document.getElementById('previewTotal');
    if (totalEl) {
        totalEl.textContent = allTorrents.length;
    }
    
    // 更新分页显示
    updatePreviewPagination();
    
    if (allTorrents.length === 0) {
        contentContainer.innerHTML = `
            <div class="preview-empty-state">
                <div class="empty-icon"><i data-lucide="search" class="icon-xl"></i></div>
                <div class="empty-text">暂无可预览种子</div>
                <div class="empty-hint">当前站点或筛选条件下还没有可下载内容。</div>
            </div>
        `;
        updateSelectedCountInModal();
        refreshLucideIcons();
        return;
    }
    
    // 渲染当前页的种子列表
    let html = '<div class="torrent-list preview-sections">';
    
    // 新种子区域（当前页）
    const currentNewTorrents = previewCurrentRecords.filter(t => !t._isDownloaded);
    const totalNewTorrents = displayNewTorrents.length;
    if (currentNewTorrents.length > 0) {
        html += `
            <div class="torrent-section">
                <div class="torrent-section-title">
                    <span class="torrent-section-heading">
                        <i data-lucide="download" class="icon-sm"></i>
                        新种子
                    </span>
                    <span class="count">${totalNewTorrents}</span>
                </div>
                <div class="torrent-list">
                    ${currentNewTorrents.map(t => renderTorrentItem(t, false, isDownloadedCallback)).join('')}
                </div>
            </div>
        `;
    }
    
    // 已下载种子区域（当前页）
    const currentDownloadedTorrents = previewCurrentRecords.filter(t => t._isDownloaded);
    if (currentDownloadedTorrents.length > 0) {
        html += `
            <div class="torrent-section">
                <div class="torrent-section-title">
                    <span class="torrent-section-heading">
                        <i data-lucide="check" class="icon-sm"></i>
                        已下载
                    </span>
                    <span class="count">${currentDownloadedTorrents.length}</span>
                    <span class="redownload-hint">
                        <i data-lucide="rotate-ccw" class="icon-sm"></i>
                        可再次勾选下载
                    </span>
                </div>
                <div class="torrent-list">
                    ${currentDownloadedTorrents.map(t => renderTorrentItem(t, true, isDownloadedCallback)).join('')}
                </div>
            </div>
        `;
    }
    
    html += '</div>';
    contentContainer.innerHTML = html;
    
    // 更新选中数量显示
    if (typeof updateSelectedCountInModal === 'function') {
        updateSelectedCountInModal();
    }
    refreshLucideIcons();
}

/**
 * 更新分页按钮状态
 */
export function updatePreviewPagination() {
    const currentPageEl = document.getElementById('previewCurrentPage');
    const totalPagesEl = document.getElementById('previewTotalPages');
    const firstBtn = document.getElementById('previewFirstPageBtn');
    const prevBtn = document.getElementById('previewPrevPageBtn');
    const nextBtn = document.getElementById('previewNextPageBtn');
    const lastBtn = document.getElementById('previewLastPageBtn');
    
    if (currentPageEl) currentPageEl.textContent = previewCurrentPage;
    if (totalPagesEl) totalPagesEl.textContent = previewTotalPages;
    
    if (firstBtn) firstBtn.disabled = previewCurrentPage === 1;
    if (prevBtn) prevBtn.disabled = previewCurrentPage === 1;
    if (nextBtn) nextBtn.disabled = previewCurrentPage === previewTotalPages;
    if (lastBtn) lastBtn.disabled = previewCurrentPage === previewTotalPages;
}

/**
 * 跳转到指定页
 */
export function goToPreviewPage(page) {
    if (page < 1 || page > previewTotalPages) return;
    previewCurrentPage = page;
    renderPreviewList('torrentPreviewList');
}

/**
 * 上一页
 */
export function goToPreviewPrevPage() {
    if (previewCurrentPage > 1) {
        previewCurrentPage--;
        renderPreviewList('torrentPreviewList');
    }
}

/**
 * 下一页
 */
export function goToPreviewNextPage() {
    if (previewCurrentPage < previewTotalPages) {
        previewCurrentPage++;
        renderPreviewList('torrentPreviewList');
    }
}

/**
 * 跳转到最后一页
 */
export function goToPreviewLastPage() {
    previewCurrentPage = previewTotalPages;
    renderPreviewList('torrentPreviewList');
}

/**
 * 全选/取消全选
 */
export function togglePreviewAll(checkbox) {
    const listContainer = document.getElementById('previewListContent');
    if (!listContainer) return;
    
    const checkboxes = listContainer.querySelectorAll('input[type="checkbox"]');
    checkboxes.forEach(cb => {
        if (!cb.disabled) {
            cb.checked = checkbox.checked;
            toggleCheckboxHighlight(cb);
        }
    });
    
    if (typeof updateSelectedCountInModal === 'function') {
        updateSelectedCountInModal();
    }
}

/**
 * 反选
 */
export function togglePreviewInvert() {
    const listContainer = document.getElementById('previewListContent');
    if (!listContainer) return;
    
    const checkboxes = listContainer.querySelectorAll('input[type="checkbox"]');
    checkboxes.forEach(cb => {
        if (!cb.disabled) {
            cb.checked = !cb.checked;
            toggleCheckboxHighlight(cb);
        }
    });
    
    if (typeof updateSelectedCountInModal === 'function') {
        updateSelectedCountInModal();
    }
}

// 导出全局函数
if (typeof window !== 'undefined') {
    window.searchPreviewDynamic = searchPreviewDynamic;
    window.filterPreviewBySite = filterPreviewBySite;
    window.filterPreviewByCategory = filterPreviewByCategory;
    window.sortPreviewRecords = sortPreviewRecords;
    window.renderPreviewToolbar = renderPreviewToolbar;
    window.updateSelectedCountInModal = updateSelectedCountInModal;
    window.changePreviewPageSize = changePreviewPageSize;
    window.goToPreviewPage = goToPreviewPage;
    window.goToPreviewPrevPage = goToPreviewPrevPage;
    window.goToPreviewNextPage = goToPreviewNextPage;
    window.goToPreviewLastPage = goToPreviewLastPage;
    window.togglePreviewAll = togglePreviewAll;
    window.togglePreviewInvert = togglePreviewInvert;
    window.toggleTorrentSelection = toggleTorrentSelection;
    window.askRedownload = askRedownload;
}
