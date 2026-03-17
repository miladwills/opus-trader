from services.bot_manager_service import BotManagerService
from services.bot_storage_service import BotStorageService


def test_editing_existing_bot_preserves_versions_and_updates_leverage(tmp_path):
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
            "leverage": 5.0,
        }
    )

    persisted = storage.get_bot("bot-1")

    assert saved["leverage"] == 5.0
    assert persisted["leverage"] == 5.0
    assert saved["status"] == "paused"
    assert saved["control_version"] == 4
    assert saved["settings_version"] == 8


def test_new_ui_save_persists_configured_mode_and_explicit_locked_mode_policy(tmp_path):
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
            "auto_direction": True,
            "mode_policy": "locked",
        }
    )

    persisted = storage.get_bot(saved["id"])

    assert saved["mode"] == "short"
    assert saved["configured_mode"] == "short"
    assert saved["configured_range_mode"] == "dynamic"
    assert saved["mode_policy"] == "locked"
    assert saved["effective_runtime_mode"] is None
    assert persisted["mode"] == "short"
    assert persisted["configured_mode"] == "short"
    assert persisted["mode_policy"] == "locked"


def test_legacy_bot_without_mode_policy_keeps_runtime_auto_switch_fallback(tmp_path):
    storage = BotStorageService(str(tmp_path / "bots.json"))
    service = BotManagerService.__new__(BotManagerService)
    service.bot_storage = storage
    service.client = None
    service.risk_manager = None
    service.account_service = None
    service._compute_min_notional_requirement = lambda bot_data: None

    saved = service.create_or_update_bot(
        {
            "symbol": "BTCUSDT",
            "mode": "neutral",
            "range_mode": "fixed",
            "lower_price": 90000.0,
            "upper_price": 100000.0,
            "investment": 100.0,
            "leverage": 3.0,
            "auto_direction": True,
        }
    )

    assert saved["mode_policy"] == "runtime_auto_switch_non_persistent"
