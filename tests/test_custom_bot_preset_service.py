from datetime import datetime, timezone

from services.custom_bot_preset_service import CustomBotPresetService


class _AuditSink:
    def __init__(self):
        self.events = []

    def enabled(self):
        return True

    def record_event(self, payload, **kwargs):
        self.events.append(dict(payload))
        return True


class _BotStorage:
    def __init__(self, bot):
        self.bot = bot

    def get_bot(self, bot_id):
        if str(bot_id) == str(self.bot.get("id")):
            return dict(self.bot)
        return None


def _make_service(tmp_path, *, bot=None, audit_sink=None):
    return CustomBotPresetService(
        str(tmp_path / "custom_bot_presets.json"),
        bot_storage=_BotStorage(bot or {}),
        audit_diagnostics_service=audit_sink,
        now_fn=lambda: datetime(2026, 3, 12, 17, 0, tzinfo=timezone.utc),
    )


def test_create_from_bot_captures_only_supported_fields_and_persists(tmp_path):
    audit_sink = _AuditSink()
    service = _make_service(
        tmp_path,
        bot={
            "id": "bot-1",
            "symbol": "ETHUSDT",
            "mode": "neutral",
            "range_mode": "fixed",
            "leverage": 4,
            "grid_count": 12,
            "target_grid_count": 9,
            "grid_distribution": "balanced",
            "neutral_volatility_gate_threshold_pct": 4.2,
            "session_timer_enabled": True,
            "session_start_at": "2026-03-12T18:00:00+00:00",
            "session_stop_at": "2026-03-12T20:00:00+00:00",
            "session_end_mode": "green_grace_then_stop",
            "session_cancel_pending_orders_on_end": True,
            "status": "running",
            "position_size": 3.5,
            "realized_pnl": 88.1,
            "ai_advisor_summary": {"verdict": "review"},
        },
        audit_sink=audit_sink,
    )

    preset = service.create_from_bot("bot-1", preset_name="ETH Reuse")

    assert preset["preset_name"] == "ETH Reuse"
    assert preset["symbol_hint"] == "ETHUSDT"
    assert preset["mode_hint"] == "neutral"
    assert preset["fields"] == {
        "range_mode": "fixed",
        "leverage": 4.0,
        "grid_count": 9,
        "target_grid_count": 9,
        "grid_distribution": "balanced",
        "neutral_volatility_gate_threshold_pct": 4.2,
        "session_timer_enabled": True,
        "session_duration_min": 120,
        "session_time_selection_required": False,
        "session_end_mode": "green_grace_then_stop",
        "session_cancel_pending_orders_on_end": True,
    }
    assert "status" not in preset["fields"]
    assert "realized_pnl" not in preset["fields"]
    assert audit_sink.events[-1]["event_type"] == "custom_bot_preset_created_from_bot"

    reloaded = CustomBotPresetService(str(tmp_path / "custom_bot_presets.json"))
    saved = reloaded.get_preset(preset["preset_id"])
    assert saved is not None
    assert saved["fields"]["grid_count"] == 9


def test_delete_custom_preset_removes_it_without_touching_other_items(tmp_path):
    service = _make_service(tmp_path)

    first = service.create_preset(preset_name="Preset A", fields={"leverage": 3, "grid_count": 6})
    second = service.create_preset(preset_name="Preset B", fields={"leverage": 2, "grid_distribution": "balanced"})

    assert service.delete_preset(first["preset_id"]) is True
    assert service.get_preset(first["preset_id"]) is None
    assert service.get_preset(second["preset_id"]) is not None


def test_build_key_fields_summarizes_custom_preset_values():
    items = CustomBotPresetService.build_key_fields(
        {
            "leverage": 3.0,
            "grid_count": 8,
            "grid_distribution": "balanced",
            "session_timer_enabled": True,
            "session_duration_min": 120,
            "session_time_selection_required": False,
        }
    )

    assert items == [
        {"field": "leverage", "label": "Leverage", "value": 3.0},
        {"field": "grid_count", "label": "Grid count", "value": 8},
        {"field": "grid_distribution", "label": "Grid distribution", "value": "balanced"},
        {"field": "session_timer_enabled", "label": "Session timer", "value": True},
        {"field": "session_duration_min", "label": "Session duration", "value": 120},
    ]


def test_update_preset_renames_and_persists(tmp_path):
    service = _make_service(tmp_path)
    preset = service.create_preset(preset_name="Preset A", fields={"leverage": 3, "grid_count": 6})

    updated = service.update_preset(preset["preset_id"], preset_name="Preset B")

    assert updated["preset_name"] == "Preset B"
    assert service.get_preset(preset["preset_id"])["preset_name"] == "Preset B"


def test_old_persisted_absolute_session_times_are_sanitized_on_read(tmp_path):
    raw_file = tmp_path / "custom_bot_presets.json"
    raw_file.write_text(
        """
{
  "items": [
    {
      "preset_id": "custom:legacy",
      "preset_name": "Legacy Session",
      "preset_type": "custom",
      "source_bot_id": "bot-legacy",
      "fields": {
        "leverage": 3,
        "grid_count": 8,
        "session_timer_enabled": true,
        "session_start_at": "2026-03-12T10:00:00+00:00",
        "session_stop_at": "2026-03-12T12:00:00+00:00",
        "session_end_mode": "green_grace_then_stop"
      }
    }
  ]
}
        """.strip(),
        encoding="utf-8",
    )

    service = CustomBotPresetService(str(raw_file))
    preset = service.get_preset("custom:legacy")

    assert preset is not None
    assert preset["fields"]["session_duration_min"] == 120
    assert preset["fields"]["session_time_selection_required"] is False
    assert "session_start_at" not in preset["fields"]
    assert "session_stop_at" not in preset["fields"]


def test_session_preset_without_duration_requires_fresh_times(tmp_path):
    service = _make_service(tmp_path)
    preset = service.create_preset(
        preset_name="Session Recheck",
        fields={
            "leverage": 3,
            "grid_count": 8,
            "session_timer_enabled": True,
            "session_stop_at": "2026-03-12T20:00:00+00:00",
            "session_end_mode": "green_grace_then_stop",
        },
    )

    assert preset["fields"]["session_time_selection_required"] is True
    assert "session_stop_at" not in preset["fields"]
