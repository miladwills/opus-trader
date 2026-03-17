from services.runtime_settings_service import RuntimeSettingsService


def test_runtime_settings_service_defaults(tmp_path):
    service = RuntimeSettingsService(str(tmp_path / "runtime_settings.json"))

    settings = service.get_settings()

    assert settings["auto_stop_on_direction_change"] is False
    assert settings["updated_at"] is None


def test_runtime_settings_service_persists_direction_change_toggle(tmp_path):
    path = tmp_path / "runtime_settings.json"
    service = RuntimeSettingsService(str(path))

    saved = service.set_auto_stop_on_direction_change(True)
    reloaded = RuntimeSettingsService(str(path)).get_settings()

    assert saved["auto_stop_on_direction_change"] is True
    assert saved["updated_at"]
    assert reloaded["auto_stop_on_direction_change"] is True


def test_runtime_settings_service_persists_bot_triage_overrides(tmp_path):
    path = tmp_path / "runtime_settings.json"
    service = RuntimeSettingsService(str(path))

    service.set_bot_triage_override("bot-1", mode="dismissed", verdict="KEEP")
    service.set_bot_triage_override(
        "bot-2",
        mode="snoozed",
        verdict="REDUCE",
        snooze_until="2026-03-12T14:00:00+00:00",
    )
    reloaded = RuntimeSettingsService(str(path)).get_bot_triage_overrides()

    assert reloaded["bot-1"]["mode"] == "dismissed"
    assert reloaded["bot-1"]["verdict"] == "KEEP"
    assert reloaded["bot-2"]["mode"] == "snoozed"
    assert reloaded["bot-2"]["verdict"] == "REDUCE"
    assert reloaded["bot-2"]["snooze_until"] == "2026-03-12T14:00:00+00:00"


def test_runtime_settings_service_persists_bot_config_advisor_queued_apply(tmp_path):
    path = tmp_path / "runtime_settings.json"
    service = RuntimeSettingsService(str(path))

    service.set_bot_config_advisor_queued_apply(
        "bot-9",
        {
            "state": "waiting_for_flat",
            "recommendation_type": "REDUCE_RISK",
            "base_settings_version": 11,
            "applicable_changes": [
                {"field": "leverage", "from": 6.0, "to": 3.0, "label": "Leverage"},
                {"field": "grid_count", "from": 15, "to": 8, "label": "Grid count"},
            ],
            "advisory_only_changes": [
                {"field": "range_posture", "from": "tight", "to": "keep", "label": "Range posture"},
            ],
            "queued_at": "2026-03-12T14:00:00+00:00",
        },
    )
    reloaded = RuntimeSettingsService(str(path)).get_bot_config_advisor_queued_apply("bot-9")

    assert reloaded["state"] == "waiting_for_flat"
    assert reloaded["recommendation_type"] == "REDUCE_RISK"
    assert reloaded["base_settings_version"] == 11
    assert reloaded["queued_fields"] == ["leverage", "grid_count"]
    assert reloaded["advisory_only_fields"] == ["range_posture"]
    assert reloaded["queued_at"] == "2026-03-12T14:00:00+00:00"
