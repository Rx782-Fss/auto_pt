const PANEL_CONFIG = {
    qb: {
        panelId: 'qbSlidePanel',
        overlayId: 'qbPanelOverlay',
        shortcutSelector: '[data-panel-key="qb"]'
    },
    notify: {
        panelId: 'notifySlidePanel',
        overlayId: 'notifyPanelOverlay',
        shortcutSelector: '[data-panel-key="notify"]'
    },
    system: {
        panelId: 'systemSlidePanel',
        overlayId: 'systemPanelOverlay',
        shortcutSelector: '[data-panel-key="system"]'
    },
    sites: {
        panelId: 'siteSlidePanel',
        overlayId: 'sitePanelOverlay',
        shortcutSelector: '[data-panel-key="sites"]'
    }
};

function setElementToneClass(element, prefix, tone) {
    if (!element) {
        return;
    }

    const tones = ['empty', 'error', 'ready', 'warning', 'info'];
    element.classList.remove(...tones.map(item => `${prefix}-${item}`));
    if (tone) {
        element.classList.add(`${prefix}-${tone}`);
    }
}

function getPanelElements(panelKey) {
    const config = PANEL_CONFIG[panelKey];
    if (!config) {
        return {};
    }

    return {
        panel: document.getElementById(config.panelId),
        overlay: document.getElementById(config.overlayId),
        shortcut: document.querySelector(config.shortcutSelector)
    };
}

function setPanelState(panelKey, isOpen) {
    const { panel, overlay, shortcut } = getPanelElements(panelKey);

    if (panel) {
        panel.classList.toggle('open', isOpen);
    }

    if (overlay) {
        overlay.classList.toggle('show', isOpen);
    }

    if (shortcut) {
        shortcut.classList.toggle('is-active', isOpen);
        shortcut.setAttribute('aria-pressed', isOpen ? 'true' : 'false');
    }
}

export function closeAllPanels(exceptKey = null) {
    Object.keys(PANEL_CONFIG).forEach((panelKey) => {
        if (panelKey !== exceptKey) {
            setPanelState(panelKey, false);
        }
    });
}

export async function togglePanel(panelKey, onOpen) {
    const { panel } = getPanelElements(panelKey);
    if (!panel) {
        return false;
    }

    const shouldOpen = !panel.classList.contains('open');
    closeAllPanels(shouldOpen ? panelKey : null);
    setPanelState(panelKey, shouldOpen);

    if (shouldOpen && typeof onOpen === 'function') {
        await onOpen();
    }

    return shouldOpen;
}

export function updateSitePanelSummary(sites = null) {
    const summaryEl = document.getElementById('sitePanelSummary');
    if (!summaryEl) {
        return;
    }

    if (!Array.isArray(sites)) {
        summaryEl.textContent = '站点摘要加载失败';
        setElementToneClass(summaryEl, 'site-panel-summary', 'error');
        return;
    }

    const total = sites.length;
    const enabled = sites.filter(site => site.enabled).length;
    const autoDownload = sites.filter(site => site.auto_download).length;

    if (total === 0) {
        summaryEl.textContent = '还没有配置站点';
        setElementToneClass(summaryEl, 'site-panel-summary', 'empty');
        return;
    }

    summaryEl.textContent = `${total} 个站点 · ${enabled} 个启用 · ${autoDownload} 个自动下载`;
    setElementToneClass(summaryEl, 'site-panel-summary', 'ready');
}

export function updateSiteResultMeta(text, tone = 'info') {
    const metaEl = document.getElementById('siteResultMeta');
    if (metaEl) {
        metaEl.textContent = text;
        setElementToneClass(metaEl, 'site-result-meta', tone);
    }
}
