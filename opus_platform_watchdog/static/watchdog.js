/**
 * Opus Platform Watchdog - Client-side auto-refresh
 */

(function() {
    const REFRESH_INTERVAL = 10000; // 10 seconds
    let refreshTimer = null;

    async function refreshDashboard() {
        try {
            // Fetch latest health
            const healthResp = await fetch('/api/health/current');
            if (!healthResp.ok) return;
            const health = await healthResp.json();

            // Update health banner
            const banner = document.getElementById('health-banner');
            if (banner && health.overall_score !== undefined) {
                const scoreEl = banner.querySelector('.text-3xl');
                if (scoreEl) scoreEl.textContent = health.overall_score;

                const statusEl = banner.querySelector('.text-sm.font-medium');
                if (statusEl) statusEl.textContent = health.overall_status || 'unknown';
            }

            // Fetch latest incidents
            const incResp = await fetch('/api/incidents/recent?limit=10');
            if (!incResp.ok) return;

        } catch (e) {
            // Silent fail - page still shows last known state
            console.debug('Refresh failed:', e.message);
        }
    }

    // Only auto-refresh on pages that benefit from it
    const path = window.location.pathname;
    if (path === '/' || path === '/incidents' || path === '/bridge' || path === '/system') {
        refreshTimer = setInterval(() => {
            refreshDashboard();
        }, REFRESH_INTERVAL);
    }

    // Update auto-refresh badge
    const badge = document.getElementById('auto-refresh-badge');
    if (badge && refreshTimer) {
        badge.textContent = 'auto-refresh: 10s';
        badge.classList.add('text-emerald-600');
    }
})();
