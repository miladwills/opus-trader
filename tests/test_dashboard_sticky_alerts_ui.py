from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_template_exposes_ready_cards_quick_jump_and_quick_edit_defaults():
    html = (ROOT / "templates" / "dashboard.html").read_text()

    # Ready To Trade standalone section removed; consolidated into emergency/restart cards
    assert 'id="emergency-ready-list"' in html
    # ready-trade-board-mobile and ready-trade-count-mobile were removed from HTML;
    # JS references them optionally via .filter() fallback
    assert 'id="floating-active-bots-button"' in html
    assert 'id="active-bots-section"' in html
    assert 'id="active-bots-table-section"' in html
    assert 'id="quick-bot-safety-card"' in html
    assert 'id="milestone-banner"' in html
    assert 'id="activity-feed-list"' not in html
    assert "This rail fills automatically when entry readiness turns green." not in html
    assert "Ready coins, guard trips, smart rotation, and backend direction-change actions stay visible here." not in html
    assert 'placeholder="0.5"' in html
    assert 'placeholder="0.3"' in html
    assert 'placeholder="0.15"' in html
    assert 'placeholder="50"' in html
    assert 'placeholder="60"' in html
    assert html.index('id="quick-bot-safety-card"') < html.index('id="quick-bot-trailing-sl-row"')


def test_dashboard_js_uses_server_runtime_settings_for_direction_change_guard():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert "function renderReadyTradeBoard(bots)" in js_text
    assert 'ready-trade-board-mobile' in js_text
    assert 'ready-trade-count-mobile' in js_text
    assert "No actionable directional setups right now" in js_text
    assert "No coins are ready to trade right now." not in js_text
    assert "entry-ready-badge--flashy" in js_text
    assert "ready-trade-card--flashy" in js_text
    assert "playReadyAlertSound" in js_text
    assert "Ready!" in js_text
    assert 'fetchJSON("/runtime-settings")' in js_text
    assert "floating-active-bots-button" in js_text
    assert '"active-bots-table-section"' in js_text
    assert 'category: "ready"' in js_text
    assert "direction_change_guard_last_event_at" in js_text
