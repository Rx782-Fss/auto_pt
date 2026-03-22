import { apiGet } from './api.js?v=174';
import { escapeHtml } from './utils.js';

const SITE_SCHEDULE_VISIBLE_ROWS = 2;

function formatIntervalText(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) {
        return '-';
    }

    if (value % 3600 === 0) {
        return `${value / 3600} 小时`;
    }

    if (value % 60 === 0) {
        return `${value / 60} 分钟`;
    }

    return `${value} 秒`;
}

function formatSwitchState(enabled) {
    return enabled ? '开' : '关';
}

function refreshLucideIcons() {
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

function syncSiteScheduleListHeight() {
    const listEl = document.getElementById('siteScheduleList');
    if (!listEl) {
        return;
    }

    const items = Array.from(listEl.querySelectorAll('.site-schedule-item'));
    if (items.length === 0) {
        listEl.classList.remove('is-scrollable');
        listEl.style.removeProperty('height');
        listEl.style.removeProperty('max-height');
        return;
    }

    const listRect = listEl.getBoundingClientRect();
    const itemMetrics = items.map((item) => {
        const rect = item.getBoundingClientRect();
        return {
            item,
            top: Math.round(rect.top - listRect.top + listEl.scrollTop),
            height: Math.ceil(rect.height)
        };
    });

    const rowTops = [];
    itemMetrics.forEach(({ top }) => {
        const currentTop = top;
        if (!rowTops.includes(currentTop)) {
            rowTops.push(currentTop);
        }
    });

    rowTops.sort((a, b) => a - b);

    const visibleRowCount = Math.min(SITE_SCHEDULE_VISIBLE_ROWS, rowTops.length);
    if (visibleRowCount === 0) {
        listEl.classList.remove('is-scrollable');
        listEl.style.removeProperty('height');
        listEl.style.removeProperty('max-height');
        return;
    }

    const lastVisibleRowTop = rowTops[visibleRowCount - 1];
    let lastVisibleRowBottom = 0;

    itemMetrics.forEach(({ top, height }) => {
        if (top === lastVisibleRowTop) {
            lastVisibleRowBottom = Math.max(lastVisibleRowBottom, top + height);
        }
    });

    if (lastVisibleRowBottom > 0) {
        const lockedHeight = `${Math.ceil(lastVisibleRowBottom)}px`;
        listEl.style.height = lockedHeight;
        listEl.style.maxHeight = lockedHeight;
        listEl.classList.toggle('is-scrollable', listEl.scrollHeight > Math.ceil(lastVisibleRowBottom) + 1);
    }
}

function queueSiteScheduleListHeightSync() {
    window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
            syncSiteScheduleListHeight();
        });
    });
}

function renderSiteSchedules(siteSchedules = []) {
    const listEl = document.getElementById('siteScheduleList');
    const summaryEl = document.getElementById('siteScheduleSummary');
    const displaySiteSchedules = Array.isArray(siteSchedules) ? siteSchedules : [];

    if (!listEl) {
        return;
    }

    if (displaySiteSchedules.length === 0) {
        listEl.innerHTML = `
            <div class="site-schedule-empty">
                <div class="site-schedule-empty-icon"><i data-lucide="clock-3" class="icon-xl"></i></div>
                <div class="site-schedule-empty-title">暂无站点配置</div>
                <div class="site-schedule-empty-hint">添加站点后，这里会展示每个站点的调度状态和下载策略。</div>
            </div>
        `;
        if (summaryEl) {
            summaryEl.innerHTML = '<span class="site-schedule-summary-pill is-empty">0 个站点</span>';
        }
        refreshLucideIcons();
        queueSiteScheduleListHeightSync();
        return;
    }

    const enabledCount = displaySiteSchedules.filter(site => site.enabled).length;
    const pausedCount = displaySiteSchedules.length - enabledCount;
    if (summaryEl) {
        const summaryNoteClass = pausedCount > 0 ? 'site-schedule-summary-note is-warning' : 'site-schedule-summary-note is-ready';
        const summaryNoteText = pausedCount > 0 ? `${pausedCount} 个暂停` : '全部运行中';
        summaryEl.innerHTML =
            `<span class="site-schedule-summary-pill">${enabledCount}/${displaySiteSchedules.length} 已启用</span>` +
            `<span class="${summaryNoteClass}">${summaryNoteText}</span>`;
    }

    listEl.innerHTML = displaySiteSchedules.map(site => {
        const checkIntervalText = formatIntervalText(site.check_interval);
        const cleanupIntervalText = formatIntervalText(site.effective_cleanup_interval);
        const itemClasses = [
            'site-schedule-item',
            site.enabled ? 'is-enabled' : 'is-disabled',
            site.auto_download ? 'is-auto-on' : 'is-auto-off'
        ];
        const badgeClass = site.enabled ? 'enabled' : 'disabled';
        const badgeText = site.enabled ? '已启用' : '已暂停';
        const captionText = site.auto_download ? '自动下载已开启' : '自动下载已关闭';

        return `
            <div class="${itemClasses.join(' ')}">
                <div class="site-schedule-name-row">
                    <div class="site-schedule-name-group">
                        <span class="site-schedule-name">${escapeHtml(site.name || 'unknown')}</span>
                        <span class="site-schedule-caption">${captionText}</span>
                    </div>
                    <span class="site-schedule-badge ${badgeClass}">${badgeText}</span>
                </div>
                <div class="site-schedule-metrics">
                    <div class="site-schedule-metric">
                        <div class="site-schedule-metric-head">
                            <span class="site-schedule-metric-label">检查周期</span>
                        </div>
                        <strong class="site-schedule-metric-value">${checkIntervalText}</strong>
                    </div>
                    <div class="site-schedule-metric">
                        <div class="site-schedule-metric-head">
                            <span class="site-schedule-metric-label">清理周期</span>
                        </div>
                        <strong class="site-schedule-metric-value">${cleanupIntervalText}</strong>
                    </div>
                </div>
                <div class="site-schedule-state-row">
                    <span class="site-state-chip ${site.auto_download ? 'is-on' : 'is-off'}">自动下载 ${formatSwitchState(site.auto_download)}</span>
                    <span class="site-state-chip ${site.auto_delete ? 'is-on' : 'is-off'}">自动删种 ${formatSwitchState(site.auto_delete)}</span>
                </div>
            </div>
        `;
    }).join('');

    refreshLucideIcons();
    queueSiteScheduleListHeightSync();
}

function updateStatsValue(id, value) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = value;
    }
}

export async function refreshDashboardStats() {
    try {
        const data = await apiGet('/api/stats');

        if (data.success) {
            const historyStats = data.history_stats || data.download_trend || {};
            const qbStats = data.qb_stats || {};
            const activeSeedingCount = (Number(qbStats.seeding) || 0) + (Number(qbStats.completed) || 0);
            updateStatsValue('todayCount', historyStats.today_completed ?? historyStats.today ?? 0);
            updateStatsValue('weekCount', historyStats.total_completed ?? historyStats.total ?? 0);
            updateStatsValue('totalHistory', activeSeedingCount);

            updateStatsValue('qbDownloading', qbStats.downloading || 0);
            updateStatsValue('qbPaused', qbStats.paused || 0);
            updateStatsValue('qbSeeding', historyStats.total_deleted ?? historyStats.deleted ?? 0);
            renderSiteSchedules(data.site_schedules || []);
        }
    } catch (e) {
        console.error('刷新统计信息失败:', e);
        updateStatsValue('todayCount', '-');
        updateStatsValue('weekCount', '-');
        updateStatsValue('totalHistory', '-');
        updateStatsValue('qbDownloading', '-');
        updateStatsValue('qbPaused', '-');
        updateStatsValue('qbSeeding', '-');

        renderSiteSchedules();
        const summaryEl = document.getElementById('siteScheduleSummary');
        if (summaryEl) {
            summaryEl.innerHTML = '<span class="site-schedule-summary-pill is-error">加载失败</span>';
        }
        queueSiteScheduleListHeightSync();
    }
}

let siteScheduleResizeTimer = null;
window.addEventListener('resize', () => {
    clearTimeout(siteScheduleResizeTimer);
    siteScheduleResizeTimer = window.setTimeout(() => {
        queueSiteScheduleListHeightSync();
    }, 120);
});

window.addEventListener('load', () => {
    queueSiteScheduleListHeightSync();
});

if (document.fonts && typeof document.fonts.ready?.then === 'function') {
    document.fonts.ready.then(() => {
        queueSiteScheduleListHeightSync();
    }).catch(() => {
        // 忽略字体事件异常，避免影响主流程。
    });
}
