import runner


def test_legacy_rotation_stays_disabled_when_only_smart_rotation_is_enabled(
    monkeypatch,
):
    monkeypatch.setattr(runner, "ENABLE_SMART_ROTATION", True)
    monkeypatch.setattr(runner, "ENABLE_LEGACY_ROTATION", False)

    assert runner.should_run_legacy_rotation([{"id": "bot-1"}]) is False


def test_legacy_rotation_requires_its_own_explicit_gate(monkeypatch):
    monkeypatch.setattr(runner, "ENABLE_LEGACY_ROTATION", True)

    assert runner.should_run_legacy_rotation([{"id": "bot-1"}]) is True
    assert runner.should_run_legacy_rotation([]) is False
