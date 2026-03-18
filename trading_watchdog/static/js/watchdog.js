/* Trading Watchdog v1 — Dashboard JS */

const REFRESH_MS = 30000;
let refreshTimer = null;

async function fetchSnapshot() {
    try {
        const res = await fetch('/api/snapshot');
        if (!res.ok) {
            if (res.status === 503) {
                document.getElementById('last-update').textContent = 'Initializing...';
                return null;
            }
            throw new Error(`HTTP ${res.status}`);
        }
        return await res.json();
    } catch (e) {
        console.error('Fetch failed:', e);
        document.getElementById('last-update').textContent = 'Fetch error';
        return null;
    }
}

function render(snap) {
    if (!snap) return;

    // Header
    const dt = new Date(snap.collected_at);
    document.getElementById('last-update').textContent =
        dt.toLocaleTimeString() + ' (' + Math.round(snap.bridge_age_sec) + 's bridge)';

    const bs = document.getElementById('bridge-status');
    if (snap.bridge_fresh) {
        bs.textContent = 'bridge: fresh';
        bs.className = 'chip chip-success';
    } else {
        bs.textContent = 'bridge: stale';
        bs.className = 'chip chip-danger';
    }

    renderOverview(snap.overview || {});
    renderTruth(snap.truth || {});
    renderReadiness(snap.readiness || {});
    renderBlockers(snap.blockers || {});
    renderFunnel(snap.funnel || {});
    renderFit(snap.symbol_fit || {});
    renderDrift(snap.drift || {});
    renderExperiments(snap.experiments || {});
    renderVerdicts(snap.verdicts || []);
    renderAccount(snap.account || {});
}

/* Overview */
function renderOverview(ov) {
    const healthCard = document.getElementById('ov-health');
    healthCard.className = 'overview-card health-' + (ov.health_label || 'unknown');
    setText('ov-health-score', ov.health_score ?? '--');
    setText('ov-health-label', ov.health_label || '');
    setText('ov-blocked-count', ov.setup_ready_blocked ?? 0);
    setText('ov-top-blocker-name', formatBlocker(ov.top_blocker || 'none'));
    setText('ov-top-blocker-count', ov.blocker_count ? ov.blocker_count + ' total blocked' : '');
    setText('ov-repeat-count', ov.repeat_fail_count ?? 0);
    setText('ov-fit-count', ov.poor_fit_count ?? 0);
    setText('ov-drift-count', ov.drift_risk_count ?? 0);
}

/* Truth */
function renderTruth(t) {
    setNum('truth-mismatch', t.score_stage_mismatch_count, [1, 1]);
    setNum('truth-null-score', t.null_score_count, [999, 999]); // neutral
    setNum('truth-stability', t.stability_issue_count, [2, 5]);
    setNum('truth-hard-inv', t.hard_invalidated_count, [999, 999]);

    const details = document.getElementById('truth-details');
    details.innerHTML = '';
    if (t.score_stage_mismatches && t.score_stage_mismatches.length > 0) {
        t.score_stage_mismatches.forEach(m => {
            details.innerHTML += `<div class="detail-item sev-high">${m.symbol}: score=${m.score} at stage=${m.stage}</div>`;
        });
    }
}

/* Readiness */
function renderReadiness(r) {
    const dist = r.distribution || [];
    const maxCount = Math.max(1, ...dist.map(d => d.count));
    const chart = document.getElementById('readiness-distribution');
    chart.innerHTML = '';

    dist.forEach(d => {
        const pct = (d.count / maxCount * 100).toFixed(0);
        chart.innerHTML += `
            <div class="bar-row">
                <span class="bar-label">${formatStage(d.stage)}</span>
                <div class="bar-track">
                    <div class="bar-fill stage-${d.stage}" style="width:${pct}%"></div>
                </div>
                <span class="bar-count">${d.count}</span>
            </div>`;
    });

    setText('rd-running', (r.running_count || 0) + ' running');
    setText('rd-stopped', (r.stopped_count || 0) + ' stopped');
    setText('rd-actionable', (r.actionable_count || 0) + ' actionable');
    setText('rd-near', (r.near_trigger_count || 0) + ' near-trigger');
}

/* Blockers */
function renderBlockers(b) {
    const tbody = document.querySelector('#blocker-table tbody');
    tbody.innerHTML = '';
    (b.blocker_table || []).forEach(row => {
        const syms = (row.symbols || []).join(', ') || '-';
        tbody.innerHTML += `<tr><td>${row.label}</td><td>${row.count}</td><td>${syms}</td></tr>`;
    });

    if ((b.blocker_table || []).length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" style="color:var(--green)">No execution blockers</td></tr>';
    }

    const buckets = document.getElementById('blocker-buckets');
    buckets.innerHTML = '';
    (b.bucket_table || []).forEach(bk => {
        if (bk.count === 0 && bk.bucket !== 'viable') return;
        const cls = bk.bucket === 'viable' ? 'chip-success' : 'chip-warn';
        buckets.innerHTML += `<span class="chip ${cls}">${bk.label}: ${bk.count}</span>`;
    });
}

/* Funnel */
function renderFunnel(f) {
    const funnel = f.funnel || {};
    const flow = document.getElementById('funnel-flow');
    const stages = [
        { key: 'watch', label: 'Watch', cls: 'f-watch' },
        { key: 'armed', label: 'Armed', cls: 'f-armed' },
        { key: 'trigger_ready', label: 'Trigger', cls: 'f-trigger' },
        { key: 'executing', label: 'Exec', cls: 'f-executing' },
    ];

    flow.innerHTML = '';
    stages.forEach((s, i) => {
        if (i > 0) flow.innerHTML += '<span class="funnel-arrow">&rarr;</span>';
        flow.innerHTML += `
            <div class="funnel-box ${s.cls}">
                <span class="funnel-num">${funnel[s.key] ?? 0}</span>
                <span class="funnel-lbl">${s.label}</span>
            </div>`;
    });

    // Blocked (separate)
    const blocked = funnel.blocked || 0;
    if (blocked > 0 || (f.blocked_at_stage && Object.values(f.blocked_at_stage).some(v => v > 0))) {
        const totalBlocked = Object.values(f.blocked_at_stage || {}).reduce((a, b) => a + b, 0);
        flow.innerHTML += `<span class="funnel-arrow">|</span>
            <div class="funnel-box f-blocked">
                <span class="funnel-num">${totalBlocked || blocked}</span>
                <span class="funnel-lbl">Blocked</span>
            </div>`;
    }

    setText('funnel-top-blocker',
        f.top_blocker_reason && f.top_blocker_reason !== 'none'
            ? 'Top: ' + formatBlocker(f.top_blocker_reason) + ' (' + f.top_blocker_count + 'x)'
            : '');

    const rates = f.funnel_rates || {};
    setText('funnel-rates',
        `Executing: ${rates.executing_pct || 0}% | Blocked: ${rates.blocked_pct || 0}%`);
}

/* Symbol Fit */
function renderFit(sf) {
    const tbody = document.querySelector('#fit-table tbody');
    tbody.innerHTML = '';

    const poor = sf.poor_fit_symbols || [];
    if (poor.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="color:var(--green)">No poor-fit symbols</td></tr>';
    } else {
        poor.forEach(s => {
            const pnlCls = s.net_pnl > 0 ? 'pnl-pos' : s.net_pnl < 0 ? 'pnl-neg' : 'pnl-zero';
            const issues = (s.blocker_issues || []).join(', ') || '-';
            tbody.innerHTML += `<tr>
                <td>${s.symbol}</td>
                <td class="${pnlCls}">${s.net_pnl.toFixed(4)}</td>
                <td>${s.win_rate}%</td>
                <td>${issues}</td>
            </tr>`;
        });
    }

    const supp = document.getElementById('fit-suppressed');
    supp.innerHTML = '';
    (sf.size_suppressed || []).forEach(s => {
        supp.innerHTML += `<div class="detail-item">${s.symbol}: ${s.reason}</div>`;
    });
}

/* Drift */
function renderDrift(d) {
    setNum('drift-stale-preview', d.stale_preview_count, [2, 5]);
    setNum('drift-runtime-stale', d.runtime_stale_count, [1, 1]);
    setNum('drift-preview-disabled', d.preview_disabled_count, [999, 999]);
    setNum('drift-preview-unavail', d.preview_unavailable_count, [999, 999]);

    const ks = document.getElementById('drift-kill-switch');
    if (d.kill_switch_active) {
        ks.textContent = 'KILL SWITCH ACTIVE';
        ks.classList.remove('hidden');
    } else {
        ks.classList.add('hidden');
    }
}

/* Experiments */
function renderExperiments(exp) {
    const section = document.getElementById('experiments');
    if (!exp.available) {
        section.classList.add('hidden');
        return;
    }
    section.classList.remove('hidden');

    const tbody = document.querySelector('#exp-table tbody');
    tbody.innerHTML = '';
    (exp.tag_summary || []).forEach(t => {
        tbody.innerHTML += `<tr>
            <td>${t.tag}</td>
            <td>${t.count}</td>
            <td>${t.blocked}</td>
            <td>${t.with_position}</td>
        </tr>`;
    });

    const unavail = document.getElementById('exp-unavailable');
    unavail.textContent = '';
}

/* Verdicts */
function renderVerdicts(verdicts) {
    setText('verdict-count', verdicts.length);
    const tbody = document.querySelector('#verdict-table tbody');
    tbody.innerHTML = '';

    if (verdicts.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="color:var(--green)">No active verdicts</td></tr>';
        return;
    }

    verdicts.forEach(v => {
        const sevCls = 'sev-' + v.severity;
        const time = v.freshness_at ? new Date(v.freshness_at).toLocaleTimeString() : '-';
        tbody.innerHTML += `<tr>
            <td class="${sevCls}">${v.severity.toUpperCase()}</td>
            <td>${v.category}</td>
            <td>${v.summary}</td>
            <td>${v.affected_symbol || '-'}</td>
            <td class="meta-text">${time}</td>
        </tr>`;
    });
}

/* Account */
function renderAccount(a) {
    setText('acct-equity', fmtUsd(a.equity));
    setText('acct-available', fmtUsd(a.available_balance));
    setText('acct-unrealized', fmtUsd(a.unrealized_pnl));

    const today = a.today_pnl || {};
    const todayNet = today.net;
    const todayEl = document.getElementById('acct-today');
    todayEl.textContent = fmtUsd(todayNet);
    todayEl.className = todayNet > 0 ? 'pnl-pos' : todayNet < 0 ? 'pnl-neg' : '';

    const dloss = a.daily_loss_pct;
    const dlEl = document.getElementById('acct-daily-loss');
    dlEl.textContent = dloss != null ? dloss.toFixed(2) + '%' : '--';
    dlEl.className = dloss && dloss < -2 ? 'pnl-neg' : '';
}

/* Helpers */
function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val ?? '--';
}

function setNum(id, val, thresholds) {
    const el = document.getElementById(id);
    if (!el) return;
    const n = val ?? 0;
    el.textContent = n;
    el.classList.remove('warn', 'danger');
    if (thresholds && n >= thresholds[1]) el.classList.add('danger');
    else if (thresholds && n >= thresholds[0]) el.classList.add('warn');
}

function fmtUsd(val) {
    if (val == null) return '--';
    return '$' + Number(val).toFixed(2);
}

function formatBlocker(reason) {
    if (!reason || reason === 'none') return 'None';
    return reason.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function formatStage(stage) {
    const labels = {
        trigger_ready: 'Trigger Ready',
        armed: 'Armed',
        watch: 'Watch',
        late: 'Late',
        blocked: 'Blocked',
    };
    return labels[stage] || stage;
}

/* Init */
async function refresh() {
    const indicator = document.getElementById('refresh-indicator');
    indicator.textContent = '...';
    const snap = await fetchSnapshot();
    render(snap);
    indicator.textContent = '';
}

refresh();
refreshTimer = setInterval(refresh, REFRESH_MS);
