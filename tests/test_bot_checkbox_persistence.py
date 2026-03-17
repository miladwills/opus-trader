from pathlib import Path

from services.bot_manager_service import BotManagerService
from services.bot_storage_service import BotStorageService


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_bot_payload_includes_explicit_boolean_fields_for_touched_config_surfaces():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert 'settings_version: parseOptionalIntInput("bot-settings-version", getEl),' in js_text
    assert 'auto_direction: autoDirectionSupported ? readBotConfigBooleanField(getEl, "auto_direction") : false' in js_text
    assert 'breakout_confirmed_entry: breakoutConfirmedSupported' in js_text
    assert 'auto_pilot: readBotConfigBooleanField(getEl, "auto_pilot")' in js_text
    assert 'trailing_sl_enabled: trailingSupported ? readBotConfigBooleanField(getEl, "trailing_sl_enabled") : false' in js_text
    assert 'quick_profit_enabled: quickProfitSupported ? readBotConfigBooleanField(getEl, "quick_profit_enabled") : false' in js_text
    assert 'neutral_volatility_gate_enabled: volatilityGateSupported ? readBotConfigBooleanField(getEl, "neutral_volatility_gate_enabled") : false' in js_text
    assert 'recovery_enabled: readBotConfigBooleanField(getEl, "recovery_enabled")' in js_text
    assert 'entry_gate_enabled: readBotConfigBooleanField(getEl, "entry_gate_enabled")' in js_text
    assert 'auto_stop_loss_enabled: readBotConfigBooleanField(getEl, "auto_stop_loss_enabled")' in js_text
    assert 'auto_take_profit_enabled: readBotConfigBooleanField(getEl, "auto_take_profit_enabled")' in js_text
    assert 'trend_protection_enabled: readBotConfigBooleanField(getEl, "trend_protection_enabled")' in js_text
    assert 'danger_zone_enabled: readBotConfigBooleanField(getEl, "danger_zone_enabled")' in js_text
    assert 'auto_neutral_mode_enabled: autoNeutralModeEnabled,' in js_text


def test_frontend_main_and_quick_forms_share_boolean_population_and_auditing():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()
    template_text = (ROOT / "templates" / "dashboard.html").read_text()

    assert "const SHARED_BOT_CONFIG_BOOLEAN_FIELDS = Object.freeze([" in js_text
    assert "const MAIN_ONLY_BOT_CONFIG_BOOLEAN_FIELDS = Object.freeze([" in js_text
    assert '<input type="hidden" id="bot-settings-version" />' in template_text
    assert '<input type="hidden" id="quick-bot-settings-version" />' in template_text
    assert "function hydrateSharedBotConfigFields(" in js_text
    assert "applyBotConfigBooleanFields(getEl, bot, booleanFields);" in js_text
    assert 'auditRenderedBotConfigBooleanFields(getEl, bot, booleanFields, auditContext);' in js_text
    assert 'hydrateSharedBotConfigFields(getEl, bot, {' in js_text
    assert 'hydrateSharedBotConfigFields($, bot, {' in js_text
    assert 'reportBotConfigSaveAudit(botData, resp, SHARED_BOT_CONFIG_BOOLEAN_FIELDS, "quick");' in js_text
    assert '], "main");' in js_text
    assert '"X-Bot-Config-Path": "main"' in js_text
    assert '"X-Bot-Config-Path": "quick"' in js_text
    assert 'fetchJSON("/config-integrity/report"' in js_text


def test_frontend_canonical_form_registry_covers_main_edit_and_quick_surfaces():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()
    template_text = (ROOT / "templates" / "dashboard.html").read_text()

    assert "const BOT_FORM_SECTION_REGISTRY = Object.freeze([" in js_text
    assert 'label: "Symbol / Market"' in js_text
    assert 'label: "Capital / Leverage / Sizing"' in js_text
    assert 'label: "Mode / Profile / Distribution / Range"' in js_text
    assert 'label: "Automation / Protection / Safety"' in js_text
    assert 'label: "Session / Timing"' in js_text
    assert "const BOT_FORM_FIELD_REGISTRY = Object.freeze({" in js_text
    assert 'mode: { label: "Configured Mode", section: "mode", surfaces: ["main", "quick"] }' in js_text
    assert 'mode_policy: { label: "Mode Policy", section: "mode", surfaces: ["main", "quick"] }' in js_text
    assert 'preset_context: { label: "Preset Context", section: "preset", surfaces: ["main", "quick"] }' in js_text
    assert "const BOT_FORM_SURFACE_DEFINITIONS = Object.freeze({" in js_text
    assert 'presetMode: "interactive_or_readonly"' in js_text
    assert 'presetMode: "readonly"' in js_text
    assert 'function getBotFormSurfaceOmittedFieldLabels(surface = "quick") {' in js_text
    assert 'function renderQuickFormLimitations() {' in js_text
    assert 'id="bot-mode-policy"' in template_text
    assert 'id="quick-bot-mode-policy"' in template_text
    assert 'id="quick-preset-context-card"' in template_text
    assert 'id="quick-form-limitation-note"' in template_text
    assert ">Configured Mode</label>" in template_text


def test_frontend_mode_semantics_panels_and_preset_context_are_rendered_on_main_and_quick_forms():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()
    template_text = (ROOT / "templates" / "dashboard.html").read_text()

    assert "function renderPresetContext(scope = \"main\", bot = null) {" in js_text
    assert "function renderModeSemanticsPanel(scope = \"main\", bot = null) {" in js_text
    assert "Runtime suggestion only; saved mode unchanged." in js_text
    assert 'id="bot-preset-heading"' in template_text
    assert 'id="bot-preset-subtitle"' in template_text
    assert 'id="bot-mode-runtime-summary"' in template_text
    assert 'id="bot-mode-runtime-comparison"' in template_text
    assert 'id="quick-bot-mode-runtime-summary"' in template_text
    assert 'id="quick-bot-mode-runtime-comparison"' in template_text
    assert 'id="quick-preset-context-title"' in template_text
    assert 'id="quick-preset-context-summary"' in template_text
    assert 'id="quick-preset-context-note"' in template_text


def test_frontend_trailing_null_hydration_is_consistent_between_main_and_quick_forms():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert 'trailingActiv.value = bot.trailing_sl_activation_pct != null ? (bot.trailing_sl_activation_pct * 100).toFixed(2) : "";' in js_text
    assert 'trailingDist.value = bot.trailing_sl_distance_pct != null ? (bot.trailing_sl_distance_pct * 100).toFixed(2) : "";' in js_text
    assert 'quickProfitTarget.value = bot.quick_profit_target != null ? String(bot.quick_profit_target) : "";' in js_text
    assert 'quickProfitClosePct.value = bot.quick_profit_close_pct != null ? String(bot.quick_profit_close_pct * 100) : "";' in js_text
    assert 'quickProfitCooldown.value = bot.quick_profit_cooldown != null ? String(bot.quick_profit_cooldown) : "";' in js_text


def test_frontend_quick_config_prefers_canonical_bot_read_on_open_and_reopen():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert "async function fetchCanonicalBotConfig(botId) {" in js_text
    assert "async function resolveEditorBotConfig(" in js_text
    assert 'const resp = await fetchJSON(`/bots/${encodeURIComponent(botId)}`);' in js_text
    assert 'canonicalErrorLog: "Quick config canonical fetch failed:"' in js_text
    assert 'runtimeRefreshErrorLog: "Quick config refresh failed:"' in js_text
    assert "const bot = await resolveEditorBotConfig(botOrId, {" in js_text


def test_frontend_main_form_also_prefers_canonical_bot_read_for_existing_bot_edit():
    js_text = (ROOT / "static" / "js" / "app_lf.js").read_text()

    assert "async function editBot(botOrId) {" in js_text
    assert 'canonicalErrorLog: "Main bot form canonical fetch failed:"' in js_text
    assert 'runtimeRefreshErrorLog: "Main bot form refresh failed:"' in js_text
    assert 'bot = typeof botOrId === "string"' in js_text
    assert '? getCachedBotConfig(botOrId)' in js_text
    assert "await refreshBots();" in js_text
    assert 'bot = buildFallbackEditorBotFromSettings(requestedBotId, settings);' in js_text


def test_bot_manager_persists_false_checkbox_values_for_shared_and_main_boolean_fields(tmp_path):
    storage = BotStorageService(str(tmp_path / "bots.json"))
    service = BotManagerService.__new__(BotManagerService)
    service.bot_storage = storage
    service.client = None
    service.risk_manager = None
    service.account_service = None
    service._compute_min_notional_requirement = lambda bot_data: None

    storage.save_bot(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "neutral",
            "range_mode": "fixed",
            "status": "paused",
            "lower_price": 90000.0,
            "upper_price": 100000.0,
            "investment": 100.0,
            "leverage": 3.0,
            "auto_direction": True,
            "breakout_confirmed_entry": True,
            "trailing_sl_enabled": True,
            "quick_profit_enabled": True,
            "neutral_volatility_gate_enabled": True,
            "recovery_enabled": True,
            "entry_gate_enabled": True,
            "auto_stop_loss_enabled": True,
            "auto_take_profit_enabled": True,
            "trend_protection_enabled": True,
            "danger_zone_enabled": True,
            "auto_neutral_mode_enabled": True,
            "control_version": 4,
            "control_updated_at": "2026-03-08T10:00:00+00:00",
            "settings_version": 7,
            "settings_updated_at": "2026-03-08T10:00:00+00:00",
        }
    )

    saved = service.create_or_update_bot(
        {
            "id": "bot-1",
            "symbol": "BTCUSDT",
            "mode": "neutral",
            "range_mode": "fixed",
            "lower_price": 90000.0,
            "upper_price": 100000.0,
            "investment": 100.0,
            "leverage": 3.0,
            "auto_direction": False,
            "breakout_confirmed_entry": False,
            "trailing_sl_enabled": False,
            "quick_profit_enabled": False,
            "neutral_volatility_gate_enabled": False,
            "recovery_enabled": False,
            "entry_gate_enabled": False,
            "auto_stop_loss_enabled": False,
            "auto_take_profit_enabled": False,
            "trend_protection_enabled": False,
            "danger_zone_enabled": False,
            "auto_neutral_mode_enabled": False,
        }
    )

    persisted = storage.get_bot("bot-1")

    assert saved["auto_direction"] is False
    assert saved["breakout_confirmed_entry"] is False
    assert saved["trailing_sl_enabled"] is False
    assert saved["quick_profit_enabled"] is False
    assert saved["neutral_volatility_gate_enabled"] is False
    assert saved["recovery_enabled"] is False
    assert saved["entry_gate_enabled"] is False
    assert saved["auto_stop_loss_enabled"] is False
    assert saved["auto_take_profit_enabled"] is False
    assert saved["trend_protection_enabled"] is False
    assert saved["danger_zone_enabled"] is False
    assert saved["auto_neutral_mode_enabled"] is False
    assert persisted["auto_direction"] is False
    assert persisted["breakout_confirmed_entry"] is False
    assert persisted["trailing_sl_enabled"] is False
    assert persisted["quick_profit_enabled"] is False
    assert persisted["neutral_volatility_gate_enabled"] is False
    assert persisted["recovery_enabled"] is False
    assert persisted["entry_gate_enabled"] is False
    assert persisted["auto_stop_loss_enabled"] is False
    assert persisted["auto_take_profit_enabled"] is False
    assert persisted["trend_protection_enabled"] is False
    assert persisted["danger_zone_enabled"] is False
    assert persisted["auto_neutral_mode_enabled"] is False


def test_bot_manager_preserves_quick_profit_tuning_and_trailing_nulls_when_flags_change(tmp_path):
    storage = BotStorageService(str(tmp_path / "bots.json"))
    service = BotManagerService.__new__(BotManagerService)
    service.bot_storage = storage
    service.client = None
    service.risk_manager = None
    service.account_service = None
    service._compute_min_notional_requirement = lambda bot_data: None

    saved = service.create_or_update_bot(
        {
            "symbol": "ETHUSDT",
            "mode": "short",
            "range_mode": "dynamic",
            "lower_price": 1900.0,
            "upper_price": 2100.0,
            "investment": 100.0,
            "leverage": 5.0,
            "quick_profit_enabled": False,
            "quick_profit_target": 0.15,
            "quick_profit_close_pct": 0.5,
            "quick_profit_cooldown": 60,
            "trailing_sl_enabled": True,
            "trailing_sl_activation_pct": None,
            "trailing_sl_distance_pct": None,
        }
    )

    assert saved["quick_profit_enabled"] is False
    assert saved["quick_profit_target"] == 0.15
    assert saved["quick_profit_close_pct"] == 0.5
    assert saved["quick_profit_cooldown"] == 60
    assert saved["trailing_sl_enabled"] is True
    assert saved["trailing_sl_activation_pct"] is None
    assert saved["trailing_sl_distance_pct"] is None
