from unittest.mock import Mock

import pytest
import requests

import config.strategy_config as strategy_cfg
from services.ai_advisor_service import AIAdvisorService
from services.grid_bot_service import GridBotService


def test_openrouter_headers_and_base_url(monkeypatch):
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_PROVIDER", "openrouter")
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_HTTP_REFERER", "https://opus.example")
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_X_TITLE", "Opus Trader")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    headers = AIAdvisorService._response_headers()
    runtime_cfg = AIAdvisorService._public_runtime_config()

    assert AIAdvisorService._chat_completions_url() == "https://openrouter.ai/api/v1/chat/completions"
    assert headers["Authorization"] == "Bearer or-key"
    assert headers["HTTP-Referer"] == "https://opus.example"
    assert headers["X-OpenRouter-Title"] == "Opus Trader"
    assert "X-Title" not in headers
    assert runtime_cfg["provider"] == "openrouter"
    assert runtime_cfg["base_url"] == "https://openrouter.ai/api/v1"
    assert runtime_cfg["request_url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert runtime_cfg["api_key_configured"] is True


def test_build_entry_context_compacts_local_candidate_state():
    service = AIAdvisorService(audit_diagnostics_service=Mock())
    bot = {
        "id": "bot-1",
        "entry_signal_label": "Breakout",
        "entry_signal_detail": "15m breakout aligned with structure",
        "setup_quality_summary": "Trend aligned and supported",
        "regime_effective": "UP",
        "regime_confidence": "high",
        "atr_5m_pct": 0.01234,
        "entry_gate_enabled": True,
        "watchdog_bottleneck_summary": {"capital_compression_active": False},
    }
    gate_result = {
        "reason": "Entry conditions favorable",
        "blocked_by": [],
        "scores": {
            "setup_quality": {
                "score": 74.2,
                "band": "strong",
                "entry_allowed": True,
                "summary": "Trend aligned and supported",
                "breakout_ready": True,
            },
            "entry_signal": {
                "code": "breakout",
                "label": "Breakout",
                "phase": "confirm",
                "preferred": True,
                "executable": True,
            },
            "price_action": {
                "direction": "UP",
                "summary": "Higher highs with reclaim",
            },
            "breakout_confirmation": {
                "required": True,
                "confirmed": True,
                "reason": "Reclaim held",
            },
        },
    }

    context = service.build_entry_context(
        bot=bot,
        symbol="ethusdt",
        mode="long",
        range_mode="dynamic",
        last_price=2010.123456,
        decision_type="initial_entry",
        candidate_open_sides=["buy"],
        candidate_counts={"buy": 1, "sell": 0},
        fast_indicators={"bbw_pct": 0.0312, "rsi": 61.4, "adx": 24.8},
        gate_result=gate_result,
        blockers=[],
        position_snapshot={"side": None, "size": 0.0, "unrealized_pnl": None},
    )

    assert context["symbol"] == "ETHUSDT"
    assert context["decision_type"] == "initial_entry"
    assert context["side_bias"] == "long"
    assert context["candidate_counts"] == {"buy": 1, "sell": 0}
    assert context["market"]["last_price"] == round(2010.123456, 6)
    assert context["market"]["price_action_direction"] == "UP"
    assert context["local_decision"]["setup_quality"]["score"] == 74.2
    assert context["local_decision"]["entry_signal"]["code"] == "breakout"
    assert context["local_decision"]["reason_to_enter"][0] == "Breakout"


def test_build_entry_context_distinguishes_bot_toggle_from_global_gate_contract(monkeypatch):
    monkeypatch.setattr(strategy_cfg, "ENTRY_GATE_ENABLED", False)
    service = AIAdvisorService(audit_diagnostics_service=Mock())
    bot = {
        "id": "bot-2",
        "entry_gate_enabled": True,
        "entry_signal_code": "breakout",
        "entry_signal_phase": "confirm",
        "entry_signal_preferred": True,
        "entry_signal_executable": True,
    }

    context = service.build_entry_context(
        bot=bot,
        symbol="btcusdt",
        mode="long",
        range_mode="dynamic",
        last_price=60123.45,
        decision_type="initial_entry",
        candidate_open_sides=["buy"],
        candidate_counts={"buy": 1, "sell": 0},
        gate_result={"reason": "Directional entry gate disabled", "blocked_by": []},
        blockers=[],
        position_snapshot={"side": None, "size": 0.0},
    )

    assert context["risk"]["entry_gate_enabled"] is False
    assert context["risk"]["entry_gate_bot_enabled"] is True
    assert context["risk"]["entry_gate_global_master_enabled"] is False
    assert context["risk"]["entry_gate_contract_active"] is False
    assert context["local_decision"]["entry_signal"]["raw_preferred"] is True
    assert context["local_decision"]["entry_signal"]["preferred"] is False
    assert context["local_decision"]["entry_signal"]["raw_executable"] is True
    assert context["local_decision"]["entry_signal"]["executable"] is False
    assert context["local_decision"]["gate"]["blocked"] is True


def test_decision_fingerprint_ignores_non_material_requested_at():
    context = {
        "bot_id": "bot-1",
        "symbol": "ETHUSDT",
        "mode": "long",
        "decision_type": "grid_opening",
        "candidate_counts": {"buy": 2, "sell": 0},
        "requested_at": "2026-03-11T10:00:00Z",
    }
    updated = dict(context)
    updated["requested_at"] = "2026-03-11T10:05:00Z"

    assert (
        AIAdvisorService.build_decision_fingerprint(context)
        == AIAdvisorService.build_decision_fingerprint(updated)
    )


def test_normalize_response_payload_rejects_invalid_verdict():
    with pytest.raises(ValueError):
        AIAdvisorService.normalize_response_payload(
            '{"verdict":"ALLOW","confidence":0.7,"reasons":[]}'
        )


def test_normalize_response_payload_maps_safe_variants_and_nested_wrappers():
    payload = AIAdvisorService.normalize_response_payload(
        {
            "result": {
                "verdict": "warning",
                "reasons": "Needs cleaner confirmation",
                "risk_note": "Nearby resistance",
                "summary": "Borderline setup",
                "escalate": "true",
            }
        }
    )

    assert payload["verdict"] == "CAUTION"
    assert payload["confidence"] is None
    assert payload["reasons"] == ["Needs cleaner confirmation"]
    assert payload["risk_note"] == "Nearby resistance"
    assert payload["summary"] == "Borderline setup"
    assert payload["escalate"] is True


def test_normalize_response_payload_accepts_case_mismatched_contract_keys():
    payload = AIAdvisorService.normalize_response_payload(
        {
            "Output": {
                "Verdict": "approved",
                "Confidence": 0.71,
                "Reasons": ["Aligned with local gate"],
                "Risk_Note": "Watch resistance",
                "Escalate": "false",
                "Summary": "Looks acceptable",
            }
        }
    )

    assert payload["verdict"] == "APPROVE"
    assert payload["confidence"] == 0.71
    assert payload["reasons"] == ["Aligned with local gate"]
    assert payload["risk_note"] == "Watch resistance"
    assert payload["summary"] == "Looks acceptable"
    assert payload["escalate"] is False


def test_extract_message_content_uses_structured_parsed_payload():
    content = AIAdvisorService._extract_message_content(
        {
            "choices": [
                {
                    "message": {
                        "parsed": {
                            "verdict": "APPROVED",
                            "confidence": 0.74,
                            "reasons": ["Aligned"],
                        }
                    }
                }
            ]
        }
    )

    payload = AIAdvisorService.normalize_response_payload(content)

    assert payload["verdict"] == "APPROVE"
    assert payload["confidence"] == 0.74
    assert payload["reasons"] == ["Aligned"]


def test_review_candidate_timeout_returns_safe_error(monkeypatch):
    class _TimeoutSession:
        def post(self, *args, **kwargs):
            raise requests.Timeout("timed out")

    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_ENABLED", True)
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_PROVIDER", "openrouter")
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_BASE_URL", "https://example.test/v1")
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_PRIMARY_MODEL", "openai/gpt-5-nano")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    service = AIAdvisorService(
        audit_diagnostics_service=Mock(enabled=Mock(return_value=False)),
        session=_TimeoutSession(),
        now_fn=lambda: 1000.0,
    )
    bot = {"id": "bot-1", "ai_advisor_enabled": True}
    context = {
        "bot_id": "bot-1",
        "symbol": "ETHUSDT",
        "mode": "long",
        "decision_type": "initial_entry",
        "candidate_counts": {"buy": 1, "sell": 0},
    }

    result = service.review_candidate(bot=bot, context=context)

    assert result["status"] == "error"
    assert result["timeout"] is True
    assert result["called"] is True
    assert result.get("verdict") is None
    assert result["provider"] == "openrouter"
    assert result["base_url"] == "https://example.test/v1"
    assert result["request_url"] == "https://example.test/v1/chat/completions"


def test_review_candidate_missing_openrouter_key_fails_safely(monkeypatch):
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_ENABLED", True)
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_PROVIDER", "openrouter")
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    service = AIAdvisorService(
        audit_diagnostics_service=Mock(enabled=Mock(return_value=False)),
        now_fn=lambda: 1000.0,
    )
    bot = {"id": "bot-1", "ai_advisor_enabled": True}
    context = {
        "bot_id": "bot-1",
        "symbol": "ETHUSDT",
        "mode": "long",
        "decision_type": "initial_entry",
        "candidate_counts": {"buy": 1, "sell": 0},
    }

    result = service.review_candidate(bot=bot, context=context)
    health = service.get_health()

    assert result["status"] == "disabled"
    assert result["called"] is False
    assert "OPENROUTER_API_KEY" in result["error"]
    assert result["base_url"] == "https://openrouter.ai/api/v1"
    assert result["request_url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert health["api_key_configured"] is False
    assert health["missing_key_count"] == 1
    assert health["last_status"] == "disabled"
    assert health["base_url"] == "https://openrouter.ai/api/v1"
    assert health["request_url"] == "https://openrouter.ai/api/v1/chat/completions"


def test_request_model_posts_to_openrouter_with_expected_headers(monkeypatch):
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"verdict":"APPROVE","confidence":0.82,"reasons":["aligned"],'
                                '"risk_note":"tight stop","escalate":false,"summary":"Aligned"}'
                            )
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 8,
                    "total_tokens": 20,
                },
            }

    class _CaptureSession:
        def post(self, url, *, headers, json, timeout):
            captured["url"] = url
            captured["headers"] = dict(headers)
            captured["payload"] = dict(json)
            captured["timeout"] = timeout
            return _Response()

    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_PROVIDER", "openrouter")
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_HTTP_REFERER", "https://opus.example")
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_X_TITLE", "Opus Trader")
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_TIMEOUT_SECONDS", 6.5)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    service = AIAdvisorService(
        audit_diagnostics_service=Mock(enabled=Mock(return_value=False)),
        session=_CaptureSession(),
        now_fn=lambda: 1000.0,
    )

    result = service._request_model(
        "openai/gpt-5-nano",
        {"bot_id": "bot-1", "symbol": "ETHUSDT"},
    )

    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer or-key"
    assert captured["headers"]["HTTP-Referer"] == "https://opus.example"
    assert captured["headers"]["X-OpenRouter-Title"] == "Opus Trader"
    assert captured["payload"]["model"] == "openai/gpt-5-nano"
    assert captured["payload"]["response_format"]["type"] == "json_schema"
    assert captured["payload"]["response_format"]["json_schema"]["strict"] is True
    assert captured["payload"]["provider"] == {"require_parameters": True}
    assert captured["payload"]["reasoning"] == {"effort": "minimal"}
    assert "temperature" not in captured["payload"]
    assert captured["timeout"] == 6.5
    assert result["status"] == "ok"
    assert result["provider"] == "openrouter"
    assert result["base_url"] == "https://openrouter.ai/api/v1"
    assert result["request_url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert result["usage"]["total_tokens"] == 20


def test_request_model_normalizes_variant_verdict_from_openrouter_json(monkeypatch):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"output":{"verdict":"approved","confidence":0.67,'
                                '"reasons":"Aligned with local gate","risk_note":"Watch volatility",'
                                '"escalate":"false","summary":"Looks acceptable"}}'
                            )
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 12,
                    "total_tokens": 22,
                },
            }

    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_PROVIDER", "openrouter")
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    service = AIAdvisorService(
        audit_diagnostics_service=Mock(enabled=Mock(return_value=False)),
        session=Mock(post=Mock(return_value=_Response())),
        now_fn=lambda: 1000.0,
    )

    result = service._request_model(
        "openai/gpt-5-nano",
        {"bot_id": "bot-1", "symbol": "ETHUSDT"},
    )

    assert result["status"] == "ok"
    assert result["verdict"] == "APPROVE"
    assert result["confidence"] == 0.67
    assert result["reasons"] == ["Aligned with local gate"]
    assert result["escalate"] is False


def test_request_model_missing_verdict_remains_safe_error(monkeypatch):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"confidence":0.52,"reasons":["No verdict supplied"]}'
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 9,
                    "completion_tokens": 7,
                    "total_tokens": 16,
                },
            }

    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_ENABLED", True)
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_PROVIDER", "openrouter")
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_PRIMARY_MODEL", "openai/gpt-5-nano")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    service = AIAdvisorService(
        audit_diagnostics_service=Mock(enabled=Mock(return_value=False)),
        session=Mock(post=Mock(return_value=_Response())),
        now_fn=lambda: 1000.0,
    )
    bot = {"id": "bot-1", "ai_advisor_enabled": True}
    context = {
        "bot_id": "bot-1",
        "symbol": "ETHUSDT",
        "mode": "long",
        "decision_type": "initial_entry",
        "candidate_counts": {"buy": 1, "sell": 0},
    }

    result = service.review_candidate(bot=bot, context=context)

    assert result["status"] == "error"
    assert result["called"] is True
    assert result["verdict"] is None
    assert result["error_code"] == "invalid_verdict_missing"
    assert result["raw_response_excerpt"] == '{"confidence":0.52,"reasons":["No verdict supplied"]}'
    assert "invalid verdict: missing" in result["error"]


def test_grid_hook_disabled_does_not_touch_execution_flags(monkeypatch):
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_ENABLED", False)

    service = GridBotService.__new__(GridBotService)
    service.ai_advisor_service = Mock()
    bot = {
        "id": "bot-1",
        "ai_advisor_enabled": True,
        "_block_opening_orders": False,
        "_entry_gate_blocked": False,
    }

    result = GridBotService._maybe_review_ai_advisor_candidate(
        service,
        bot=bot,
        symbol="ETHUSDT",
        mode="long",
        range_mode="dynamic",
        last_price=2000.0,
        decision_type="grid_opening",
        candidate_open_sides=["buy"],
        candidate_counts={"buy": 1, "sell": 0},
        fast_indicators=None,
        gate_result=None,
        blockers=[],
        position_snapshot=None,
    )

    assert result is None
    assert bot["_block_opening_orders"] is False
    assert bot["_entry_gate_blocked"] is False
    service.ai_advisor_service.build_entry_context.assert_not_called()


def test_grid_hook_failure_keeps_execution_flags_unchanged(monkeypatch):
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_ENABLED", True)

    advisor_service = Mock()
    advisor_service.build_entry_context.return_value = {
        "bot_id": "bot-1",
        "symbol": "ETHUSDT",
        "mode": "long",
        "decision_type": "grid_opening",
        "candidate_counts": {"buy": 1, "sell": 0},
    }
    advisor_service.review_candidate.return_value = {
        "status": "error",
        "called": True,
        "timeout": True,
        "fingerprint": "abc123",
        "error": "AI advisor request timed out",
        "model": "gpt-5-nano",
    }

    service = GridBotService.__new__(GridBotService)
    service.ai_advisor_service = advisor_service

    bot = {
        "id": "bot-1",
        "ai_advisor_enabled": True,
        "_block_opening_orders": False,
        "_entry_gate_blocked": False,
    }

    result = GridBotService._maybe_review_ai_advisor_candidate(
        service,
        bot=bot,
        symbol="ETHUSDT",
        mode="long",
        range_mode="dynamic",
        last_price=2000.0,
        decision_type="grid_opening",
        candidate_open_sides=["buy"],
        candidate_counts={"buy": 1, "sell": 0},
        fast_indicators={"rsi": 60.0},
        gate_result=None,
        blockers=[],
        position_snapshot={"side": None, "size": 0.0},
    )

    assert result["status"] == "error"
    assert bot["_block_opening_orders"] is False
    assert bot["_entry_gate_blocked"] is False
    assert bot["ai_advisor_timeout_count"] == 1
    assert bot["ai_advisor_call_count"] == 1


def test_grid_hook_provider_failure_keeps_execution_flags_unchanged(monkeypatch):
    monkeypatch.setattr(strategy_cfg, "AI_ADVISOR_ENABLED", True)

    advisor_service = Mock()
    advisor_service.build_entry_context.return_value = {
        "bot_id": "bot-1",
        "symbol": "ETHUSDT",
        "mode": "long",
        "decision_type": "grid_opening",
        "candidate_counts": {"buy": 1, "sell": 0},
    }
    advisor_service.review_candidate.return_value = {
        "status": "disabled",
        "called": False,
        "fingerprint": "abc123",
        "error": "OPENROUTER_API_KEY not configured",
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "request_url": "https://openrouter.ai/api/v1/chat/completions",
    }

    service = GridBotService.__new__(GridBotService)
    service.ai_advisor_service = advisor_service

    bot = {
        "id": "bot-1",
        "ai_advisor_enabled": True,
        "_block_opening_orders": False,
        "_entry_gate_blocked": False,
    }

    result = GridBotService._maybe_review_ai_advisor_candidate(
        service,
        bot=bot,
        symbol="ETHUSDT",
        mode="long",
        range_mode="dynamic",
        last_price=2000.0,
        decision_type="grid_opening",
        candidate_open_sides=["buy"],
        candidate_counts={"buy": 1, "sell": 0},
        fast_indicators={"rsi": 60.0},
        gate_result=None,
        blockers=[],
        position_snapshot={"side": None, "size": 0.0},
    )

    assert result["status"] == "disabled"
    assert bot["_block_opening_orders"] is False
    assert bot["_entry_gate_blocked"] is False
    assert bot["ai_advisor_last_error"] == "OPENROUTER_API_KEY not configured"
