from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_template_exposes_new_bot_preset_controls():
    template = (ROOT / "templates" / "dashboard.html").read_text()

    assert 'id="bot-preset-section"' in template
    assert 'id="bot-preset-select"' in template
    assert 'id="bot-preset-auto-recommend"' in template
    assert 'id="bot-preset-summary"' in template
    assert 'id="bot-preset-summary-name"' in template
    assert 'id="bot-preset-summary-confidence"' in template
    assert 'id="bot-preset-summary-reason"' in template
    assert 'id="bot-preset-sizing-warning"' in template
    assert 'id="bot-preset-summary-signals"' in template
    assert 'id="bot-preset-summary-alternatives"' in template
    assert "New Bot Presets" in template


def test_dashboard_js_wires_bot_preset_catalog_and_apply_flow():
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert "let botPresetState = {" in js
    assert "const BOT_PRESET_MANAGED_FIELD_IDS = Object.freeze([" in js
    assert "function getBotPresetConfidenceMeta(confidence)" in js
    assert "function getBotPresetCatalogItems()" in js
    assert "function getBotPresetSizingViability()" in js
    assert "function renderBotPresetSizingWarning()" in js
    assert "function applyBotPresetSettings(settings" in js
    assert "function populateBotPresetSelector()" in js
    assert "async function loadBotPresetCatalog()" in js
    assert "async function autoRecommendBotPreset()" in js
    assert 'fetchJSON("/bot-presets")' in js
    assert 'fetchJSON("/bot-presets/recommend"' in js
    assert "_creation_preset_name" in js
    assert "_creation_preset_source" in js
    assert "_creation_preset_recommended" in js
    assert "_creation_preset_fields" in js
    assert "botPresetState.confidence" in js
    assert "botPresetState.matchedSignals" in js
    assert "botPresetState.alternativePresets" in js
    assert "Preset-applied values remain editable before save." in js
    assert "Per-order slice passes min_notional" in js
    assert "updateBotPresetSectionVisibility();" in js
    assert "bot-preset-select" in js
    assert "bot-preset-auto-recommend" in js
