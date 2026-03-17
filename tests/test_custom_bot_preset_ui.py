from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_template_exposes_custom_preset_library_controls():
    template = (ROOT / "templates" / "dashboard.html").read_text()

    assert 'id="bot-preset-rename-selected"' in template
    assert 'id="bot-preset-delete-selected"' in template
    assert 'id="bot-preset-summary-meta"' in template
    assert 'id="btn-save-custom-preset"' in template
    assert "Rename Preset" in template
    assert "Delete Preset" in template
    assert "Save as Custom Preset" in template


def test_dashboard_js_wires_custom_preset_library_flow():
    js = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert "function getCustomBotPresetCatalogItems()" in js
    assert 'optgroup label="Built-in Presets"' in js
    assert 'optgroup label="My Custom Presets"' in js
    assert "function saveCurrentBotAsCustomPreset()" in js
    assert "function deleteSelectedCustomBotPreset()" in js
    assert "function renameSelectedCustomBotPreset()" in js
    assert 'fetchJSON(`/custom-bot-presets/from-bot/${encodeURIComponent(botId)}`' in js
    assert 'fetchJSON(`/custom-bot-presets/${encodeURIComponent(presetId)}`' in js
    assert 'method: "PATCH"' in js
    assert "session_time_safety" in js
    assert 'const saveCustomPresetButton = $("btn-save-custom-preset");' in js
    assert 'const renameCustomPresetButton = $("bot-preset-rename-selected");' in js
    assert 'const deleteCustomPresetButton = $("bot-preset-delete-selected");' in js
