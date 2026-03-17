import json
import logging
import os
import time
from hashlib import sha1
from typing import Any, Dict, List, Optional

import requests

import config.strategy_config as strategy_cfg
from services.audit_diagnostics_service import AuditDiagnosticsService

logger = logging.getLogger(__name__)


class AdvisorResponseValidationError(ValueError):
    """Structured-output contract failure with compact diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[str] = None,
        raw_response_excerpt: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.raw_response_excerpt = raw_response_excerpt


class AIAdvisorService:
    """Low-cost, read-only advisor for bounded entry-candidate reviews."""

    EVENT_TYPE = "ai_advisor_decision"
    VALID_VERDICTS = {"APPROVE", "CAUTION", "REJECT"}
    CONTRACT_KEYS = (
        "verdict",
        "confidence",
        "reasons",
        "risk_note",
        "escalate",
        "summary",
    )

    def __init__(
        self,
        audit_diagnostics_service: Optional[AuditDiagnosticsService] = None,
        session: Optional[requests.Session] = None,
        now_fn: Optional[Any] = None,
    ) -> None:
        self.audit_diagnostics_service = (
            audit_diagnostics_service or AuditDiagnosticsService()
        )
        self.session = session or requests.Session()
        self.now_fn = now_fn or time.time
        self._decision_cache: Dict[str, Dict[str, Any]] = {}
        self._symbol_call_windows: Dict[str, List[float]] = {}
        self._bot_last_call_ts: Dict[str, float] = {}
        self._health = {
            "total_calls": 0,
            "success_count": 0,
            "error_count": 0,
            "timeout_count": 0,
            "disabled_count": 0,
            "deduped_count": 0,
            "rate_limited_count": 0,
            "missing_key_count": 0,
            "last_error": None,
            "last_status": None,
            "last_model": None,
            "last_provider": None,
            "last_base_url": None,
        }

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off", ""}:
            return False
        return default

    @staticmethod
    def _trim_text(value: Any, max_len: int = 160) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        if len(text) <= max_len:
            return text
        return text[: max_len - 3].rstrip() + "..."

    @classmethod
    def _round_number(cls, value: Any, digits: int = 4) -> Optional[float]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return round(number, digits)

    @classmethod
    def _round_mapping(
        cls,
        values: Optional[Dict[str, Any]],
        keys: List[str],
        digits: int = 4,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        for key in keys:
            rounded = cls._round_number((values or {}).get(key), digits=digits)
            if rounded is not None:
                payload[key] = rounded
        return payload

    @staticmethod
    def _entry_gate_truth(
        bot: Optional[Dict[str, Any]],
        mode: Optional[str],
    ) -> Dict[str, Any]:
        normalized_mode = str(mode or "").strip().lower()
        global_master_applicable = normalized_mode in {"long", "short"}
        bot_enabled = bool((bot or {}).get("entry_gate_enabled", True))
        global_master_enabled = (
            bool(getattr(strategy_cfg, "ENTRY_GATE_ENABLED", False))
            if global_master_applicable
            else True
        )
        contract_active = bool(bot_enabled and global_master_enabled)
        return {
            "entry_gate_bot_enabled": bot_enabled,
            "entry_gate_global_master_applicable": global_master_applicable,
            "entry_gate_global_master_enabled": global_master_enabled,
            "entry_gate_contract_active": contract_active,
        }

    @staticmethod
    def _entry_gate_disabled_reason(gate_truth: Dict[str, Any]) -> Optional[str]:
        if gate_truth.get("entry_gate_contract_active"):
            return None
        if gate_truth.get("entry_gate_global_master_applicable") and not gate_truth.get(
            "entry_gate_global_master_enabled"
        ):
            return "Directional entry gate disabled"
        if gate_truth.get("entry_gate_global_master_applicable"):
            return "Directional entry gate disabled for this bot"
        return "Entry gate disabled for this bot"

    @staticmethod
    def _decision_key(context: Dict[str, Any]) -> str:
        return ":".join(
            [
                str(context.get("bot_id") or "na"),
                str(context.get("symbol") or "na"),
                str(context.get("decision_type") or "entry"),
            ]
        )

    @staticmethod
    def _build_decision_id(
        context: Dict[str, Any],
        fingerprint: str,
        now_ts: float,
    ) -> str:
        bot_token = str(context.get("bot_id") or "na").replace("-", "")[:8] or "na"
        return f"adv:{bot_token}:{int(max(now_ts, 0.0) * 1000)}:{fingerprint[:10]}"

    @staticmethod
    def _normalized_side_bias(
        mode: str,
        candidate_open_sides: List[str],
    ) -> str:
        normalized_mode = str(mode or "").strip().lower()
        sides = sorted({str(side or "").strip().lower() for side in candidate_open_sides if side})
        if normalized_mode == "long":
            return "long"
        if normalized_mode == "short":
            return "short"
        if sides == ["buy"]:
            return "buy"
        if sides == ["sell"]:
            return "sell"
        if len(sides) >= 2:
            return "balanced"
        return normalized_mode or "unknown"

    @classmethod
    def build_entry_context(
        cls,
        *,
        bot: Dict[str, Any],
        symbol: str,
        mode: str,
        range_mode: str,
        last_price: float,
        decision_type: str,
        candidate_open_sides: List[str],
        candidate_counts: Dict[str, int],
        fast_indicators: Optional[Dict[str, Any]] = None,
        gate_result: Optional[Dict[str, Any]] = None,
        blockers: Optional[List[Dict[str, Any]]] = None,
        position_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        scores = dict((gate_result or {}).get("scores") or {})
        setup_quality = dict(scores.get("setup_quality") or {})
        entry_signal = dict(scores.get("entry_signal") or {})
        price_action_context = dict(scores.get("price_action") or {})
        breakout_confirmation = dict(scores.get("breakout_confirmation") or {})
        scanner_summary = {
            "recommended_mode": bot.get("scanner_recommended_mode"),
            "recommendation_differs": bool(bot.get("scanner_recommendation_differs")),
            "auto_pilot_candidate_source": bot.get("auto_pilot_candidate_source"),
            "auto_pilot_top_candidate_symbol": bot.get("auto_pilot_top_candidate_symbol"),
            "auto_pilot_top_candidate_score": cls._round_number(
                bot.get("auto_pilot_top_candidate_score"),
                digits=2,
            ),
        }
        scanner_summary = {k: v for k, v in scanner_summary.items() if v not in (None, "", False)}

        compact_blockers = []
        for blocker in blockers or []:
            if not isinstance(blocker, dict):
                continue
            compact_blockers.append(
                {
                    "code": cls._trim_text(blocker.get("code"), 48),
                    "reason": cls._trim_text(blocker.get("reason"), 120),
                    "phase": cls._trim_text(blocker.get("phase"), 32),
                    "side": cls._trim_text(blocker.get("side"), 24),
                }
            )
        compact_blockers = [
            {
                key: value
                for key, value in item.items()
                if value not in (None, "")
            }
            for item in compact_blockers[:4]
        ]

        rationale: List[str] = []
        entry_label = cls._trim_text(
            entry_signal.get("label") or bot.get("entry_signal_label"),
            80,
        )
        entry_detail = cls._trim_text(
            entry_signal.get("detail") or bot.get("entry_signal_detail"),
            120,
        )
        setup_summary = cls._trim_text(
            setup_quality.get("summary") or bot.get("setup_quality_summary"),
            120,
        )
        gate_truth = cls._entry_gate_truth(bot, mode)
        gate_reason = cls._trim_text(
            (gate_result or {}).get("reason")
            or bot.get("_entry_gate_blocked_reason")
            or cls._entry_gate_disabled_reason(gate_truth),
            140,
        )
        if entry_label:
            rationale.append(entry_label)
        if entry_detail and entry_detail not in rationale:
            rationale.append(entry_detail)
        if setup_summary and setup_summary not in rationale:
            rationale.append(setup_summary)
        if gate_reason and gate_reason not in rationale and compact_blockers:
            rationale.append(gate_reason)
        if not rationale:
            buy_count = cls._safe_int((candidate_counts or {}).get("buy"), 0)
            sell_count = cls._safe_int((candidate_counts or {}).get("sell"), 0)
            rationale.append(f"opening candidates buy={buy_count} sell={sell_count}")

        watchdog_summary = dict(bot.get("watchdog_bottleneck_summary") or {})
        watchdog_payload = {
            "position_cap_active": bool(bot.get("_watchdog_position_cap_active")),
            "capital_compression_active": bool(
                watchdog_summary.get("capital_compression_active")
            ),
            "capital_starved_active": bool(
                watchdog_summary.get("capital_starved_active")
            ),
            "last_skip_reason": bot.get("last_skip_reason"),
            "runtime_blocker": bot.get("capital_starved_reason")
            or bot.get("last_skip_reason"),
        }
        watchdog_payload = {
            key: value for key, value in watchdog_payload.items() if value not in (None, "")
        }

        position_payload = {
            "side": cls._trim_text((position_snapshot or {}).get("side"), 16),
            "size": cls._round_number((position_snapshot or {}).get("size"), digits=6),
            "unrealized_pnl": cls._round_number(
                (position_snapshot or {}).get("unrealized_pnl"),
                digits=4,
            ),
            "has_position": bool(
                cls._safe_float((position_snapshot or {}).get("size"), 0.0) > 0
            ),
        }
        position_payload = {
            key: value for key, value in position_payload.items() if value not in (None, "")
        }

        market_payload = {
            "last_price": cls._round_number(last_price, digits=6),
            "regime_effective": bot.get("regime_effective"),
            "regime_confidence": bot.get("regime_confidence"),
            "trend_status": cls._trim_text(bot.get("trend_status"), 96),
            "atr_5m_pct": cls._round_number(bot.get("atr_5m_pct"), digits=6),
            "atr_15m_pct": cls._round_number(bot.get("atr_15m_pct"), digits=6),
            "bbw_pct": cls._round_number((fast_indicators or {}).get("bbw_pct"), digits=6),
            "price_action_direction": cls._trim_text(
                price_action_context.get("direction"),
                16,
            ),
            "price_action_summary": cls._trim_text(
                price_action_context.get("summary"),
                120,
            ),
        }
        market_payload.update(
            cls._round_mapping(
                fast_indicators,
                keys=["rsi", "adx", "price_velocity"],
                digits=4,
            )
        )
        market_payload = {
            key: value for key, value in market_payload.items() if value not in (None, "")
        }
        raw_preferred = bool(
            entry_signal.get("preferred", bot.get("entry_signal_preferred", False))
        )
        raw_executable = bool(
            entry_signal.get(
                "executable",
                bot.get("entry_signal_executable", False),
            )
        )
        effective_preferred = bool(
            raw_preferred and gate_truth["entry_gate_contract_active"]
        )
        effective_executable = bool(
            raw_executable and gate_truth["entry_gate_contract_active"]
        )

        local_decision = {
            "candidate_ready": True,
            "reason_to_enter": rationale[:3],
            "entry_signal": {
                "code": entry_signal.get("code") or bot.get("entry_signal_code"),
                "phase": entry_signal.get("phase") or bot.get("entry_signal_phase"),
                "preferred": effective_preferred,
                "raw_preferred": raw_preferred,
                "late": bool(entry_signal.get("late", bot.get("entry_signal_late", False))),
                "executable": effective_executable,
                "raw_executable": raw_executable,
            },
            "setup_quality": {
                "score": cls._round_number(
                    setup_quality.get("score") or bot.get("setup_quality_score"),
                    digits=2,
                ),
                "band": setup_quality.get("band") or bot.get("setup_quality_band"),
                "entry_allowed": bool(
                    setup_quality.get("entry_allowed", not compact_blockers)
                ),
                "breakout_ready": bool(
                    setup_quality.get(
                        "breakout_ready",
                        bot.get("setup_quality_breakout_ready", False),
                    )
                ),
                "summary": setup_summary,
            },
            "gate": {
                "blocked": bool(
                    compact_blockers or not gate_truth["entry_gate_contract_active"]
                ),
                "reason": gate_reason,
                "blocked_by": list((gate_result or {}).get("blocked_by") or [])[:4],
                "entry_gate_bot_enabled": gate_truth["entry_gate_bot_enabled"],
                "entry_gate_global_master_applicable": gate_truth[
                    "entry_gate_global_master_applicable"
                ],
                "entry_gate_global_master_enabled": gate_truth[
                    "entry_gate_global_master_enabled"
                ],
                "entry_gate_contract_active": gate_truth[
                    "entry_gate_contract_active"
                ],
            },
            "breakout_confirmation": {
                "required": bool(breakout_confirmation.get("required")),
                "confirmed": breakout_confirmation.get("confirmed"),
                "reason": cls._trim_text(breakout_confirmation.get("reason"), 120),
            },
            "blockers": compact_blockers,
        }

        context = {
            "bot_id": str(bot.get("id") or "").strip() or None,
            "symbol": str(symbol or "").strip().upper(),
            "mode": str(mode or "").strip().lower(),
            "range_mode": str(range_mode or "").strip().lower(),
            "decision_type": str(decision_type or "").strip().lower(),
            "side_bias": cls._normalized_side_bias(mode, candidate_open_sides),
            "candidate_open_sides": sorted(
                {
                    str(side or "").strip().lower()
                    for side in candidate_open_sides or []
                    if str(side or "").strip()
                }
            ),
            "candidate_counts": {
                "buy": cls._safe_int((candidate_counts or {}).get("buy"), 0),
                "sell": cls._safe_int((candidate_counts or {}).get("sell"), 0),
            },
            "market": market_payload,
            "local_decision": local_decision,
            "position": position_payload,
            "risk": {
                "reduce_only_mode": bool(bot.get("reduce_only_mode")),
                "capital_starved": bool(bot.get("_capital_starved_block_opening_orders")),
                "volatility_block_opening_orders": bool(
                    bot.get("_volatility_block_opening_orders")
                ),
                "entry_gate_enabled": gate_truth["entry_gate_contract_active"],
                "entry_gate_bot_enabled": gate_truth["entry_gate_bot_enabled"],
                "entry_gate_global_master_applicable": gate_truth[
                    "entry_gate_global_master_applicable"
                ],
                "entry_gate_global_master_enabled": gate_truth[
                    "entry_gate_global_master_enabled"
                ],
                "entry_gate_contract_active": gate_truth[
                    "entry_gate_contract_active"
                ],
            },
            "watchdogs": watchdog_payload,
            "scanner": scanner_summary,
        }
        return context

    @classmethod
    def build_decision_fingerprint(cls, context: Dict[str, Any]) -> str:
        material_context = dict(context or {})
        material_context.pop("requested_at", None)
        fingerprint = json.dumps(
            material_context,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        )
        return sha1(fingerprint.encode("utf-8")).hexdigest()

    def _bot_is_enabled(
        self,
        bot: Optional[Dict[str, Any]],
        decision_type: str,
        mode: str,
    ) -> bool:
        if not bool(getattr(strategy_cfg, "AI_ADVISOR_ENABLED", False)):
            return False
        if not isinstance(bot, dict) or not bool(bot.get("ai_advisor_enabled", False)):
            return False
        trigger_policies = set(getattr(strategy_cfg, "AI_ADVISOR_TRIGGER_POLICIES", ()) or ())
        if trigger_policies and decision_type not in trigger_policies:
            return False
        return True

    @staticmethod
    def _provider() -> str:
        return str(getattr(strategy_cfg, "AI_ADVISOR_PROVIDER", "openrouter") or "openrouter").strip().lower()

    @classmethod
    def _resolved_api_key(cls) -> str:
        provider = cls._provider()
        if provider == "openrouter":
            return str(os.getenv("OPENROUTER_API_KEY") or "").strip()
        return str((getattr(strategy_cfg, "AI_ADVISOR_API_KEY", "") or "")).strip()

    @classmethod
    def _response_headers(cls) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cls._resolved_api_key()}",
        }
        provider = cls._provider()
        if strategy_cfg.AI_ADVISOR_HTTP_REFERER:
            headers["HTTP-Referer"] = strategy_cfg.AI_ADVISOR_HTTP_REFERER
        if strategy_cfg.AI_ADVISOR_X_TITLE:
            if provider == "openrouter":
                headers["X-OpenRouter-Title"] = strategy_cfg.AI_ADVISOR_X_TITLE
            else:
                headers["X-Title"] = strategy_cfg.AI_ADVISOR_X_TITLE
        return headers

    @staticmethod
    def _configured_base_url() -> str:
        return str(getattr(strategy_cfg, "AI_ADVISOR_BASE_URL", "") or "").strip()

    @staticmethod
    def _is_gpt5_model(model: str) -> bool:
        model_name = str(model or "").strip().lower()
        return model_name.startswith("gpt-5") or "/gpt-5" in model_name

    @classmethod
    def _chat_completions_url(cls) -> str:
        return cls._configured_base_url().rstrip("/") + "/chat/completions"

    @classmethod
    def _public_runtime_config(cls) -> Dict[str, Any]:
        api_key = cls._resolved_api_key()
        return {
            "provider": cls._provider(),
            "base_url": cls._configured_base_url() or None,
            "request_url": cls._chat_completions_url(),
            "api_key_configured": bool(api_key),
            "primary_model": str(getattr(strategy_cfg, "AI_ADVISOR_PRIMARY_MODEL", "") or "").strip() or None,
            "escalation_model": str(getattr(strategy_cfg, "AI_ADVISOR_ESCALATION_MODEL", "") or "").strip() or None,
            "escalation_enabled": bool(getattr(strategy_cfg, "AI_ADVISOR_ESCALATION_ENABLED", False)),
            "referer": str(getattr(strategy_cfg, "AI_ADVISOR_HTTP_REFERER", "") or "").strip() or None,
            "app_name": str(getattr(strategy_cfg, "AI_ADVISOR_X_TITLE", "") or "").strip() or None,
            "enabled_globally": bool(getattr(strategy_cfg, "AI_ADVISOR_ENABLED", False)),
        }

    def get_health(self) -> Dict[str, Any]:
        payload = dict(self._health)
        payload.update(self._public_runtime_config())
        return payload

    def _record_health_status(
        self,
        *,
        status: str,
        model: Optional[str] = None,
        error: Optional[str] = None,
        timeout: bool = False,
        missing_key: bool = False,
    ) -> None:
        self._health["last_status"] = str(status or "").strip().lower() or None
        self._health["last_model"] = str(model or "").strip() or None
        self._health["last_provider"] = self._provider()
        self._health["last_base_url"] = self._configured_base_url() or None
        self._health["last_error"] = self._trim_text(error, 200)
        if status == "ok":
            self._health["success_count"] = int(self._health.get("success_count", 0) or 0) + 1
        elif status == "error":
            self._health["error_count"] = int(self._health.get("error_count", 0) or 0) + 1
            if timeout:
                self._health["timeout_count"] = int(self._health.get("timeout_count", 0) or 0) + 1
        elif status == "disabled":
            self._health["disabled_count"] = int(self._health.get("disabled_count", 0) or 0) + 1
        elif status == "deduped":
            self._health["deduped_count"] = int(self._health.get("deduped_count", 0) or 0) + 1
        elif status == "rate_limited":
            self._health["rate_limited_count"] = int(self._health.get("rate_limited_count", 0) or 0) + 1
        if missing_key:
            self._health["missing_key_count"] = int(self._health.get("missing_key_count", 0) or 0) + 1

    @classmethod
    def _extract_message_content(cls, payload: Dict[str, Any]) -> str:
        choices = list(payload.get("choices") or [])
        if not choices:
            return ""
        message = dict((choices[0] or {}).get("message") or {})
        for key in ("parsed", "json", "output"):
            structured = message.get(key)
            if isinstance(structured, dict) and structured:
                return json.dumps(structured, ensure_ascii=True, separators=(",", ":"))
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
                    continue
                for key in ("json", "arguments", "content"):
                    nested = item.get(key)
                    if isinstance(nested, dict) and nested:
                        parts.append(
                            json.dumps(
                                nested,
                                ensure_ascii=True,
                                separators=(",", ":"),
                            )
                        )
                        break
            return "\n".join(parts)
        return ""

    @staticmethod
    def _find_payload_key(
        payload: Optional[Dict[str, Any]],
        *candidate_keys: str,
    ) -> Optional[str]:
        if not isinstance(payload, dict):
            return None
        key_map = {
            str(key).strip().lower(): key
            for key in payload.keys()
            if isinstance(key, str)
        }
        for candidate in candidate_keys:
            normalized = str(candidate or "").strip().lower()
            if normalized in key_map:
                return key_map[normalized]
        return None

    @classmethod
    def _payload_value(
        cls,
        payload: Optional[Dict[str, Any]],
        *candidate_keys: str,
    ) -> Any:
        key = cls._find_payload_key(payload, *candidate_keys)
        if key is None:
            return None
        return payload.get(key)

    @classmethod
    def _coerce_json_object(cls, raw_payload: Any) -> Dict[str, Any]:
        if isinstance(raw_payload, dict):
            return raw_payload
        text = str(raw_payload or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        payload = json.loads(text or "{}")
        if isinstance(payload, dict):
            return payload
        raise ValueError("advisor response must be a JSON object")

    @classmethod
    def _extract_contract_payload(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        if cls._payload_value(payload, "verdict") is not None:
            return payload
        for key in ("result", "output", "response", "advisor", "decision", "data"):
            nested = cls._payload_value(payload, key)
            if isinstance(nested, dict):
                extracted = cls._extract_contract_payload(nested)
                if extracted:
                    return extracted
        for value in payload.values():
            if isinstance(value, dict):
                extracted = cls._extract_contract_payload(value)
                if extracted:
                    return extracted
        return payload

    @classmethod
    def _normalize_verdict(cls, raw_verdict: Any) -> str:
        text = str(raw_verdict or "").strip().upper()
        if text in cls.VALID_VERDICTS:
            return text
        compact = "".join(ch for ch in text if ch.isalpha())
        mapping = {
            "APPROVE": "APPROVE",
            "APPROVED": "APPROVE",
            "CAUTION": "CAUTION",
            "CAUTIOUS": "CAUTION",
            "WARNING": "CAUTION",
            "WARN": "CAUTION",
            "REJECT": "REJECT",
            "REJECTED": "REJECT",
        }
        return mapping.get(compact, "")

    @classmethod
    def normalize_response_payload(cls, raw_payload: Any) -> Dict[str, Any]:
        payload = cls._extract_contract_payload(cls._coerce_json_object(raw_payload))
        verdict = cls._normalize_verdict(cls._payload_value(payload, "verdict"))
        if verdict not in cls.VALID_VERDICTS:
            raise ValueError(f"invalid verdict: {verdict or 'missing'}")
        confidence = cls._payload_value(payload, "confidence")
        normalized_confidence: Optional[float] = None
        if confidence not in (None, ""):
            normalized_confidence = cls._safe_float(confidence, -1.0)
            if normalized_confidence < 0.0 or normalized_confidence > 1.0:
                raise ValueError("confidence must be within 0..1")
            normalized_confidence = round(normalized_confidence, 4)
        reasons = cls._payload_value(payload, "reasons")
        if isinstance(reasons, str):
            reasons = [reasons]
        elif not isinstance(reasons, list):
            reasons = []
        cleaned_reasons = []
        for reason in reasons[:3]:
            trimmed = cls._trim_text(reason, 80)
            if trimmed:
                cleaned_reasons.append(trimmed)
        return {
            "verdict": verdict,
            "confidence": normalized_confidence,
            "reasons": cleaned_reasons,
            "risk_note": cls._trim_text(cls._payload_value(payload, "risk_note"), 160),
            "escalate": cls._safe_bool(cls._payload_value(payload, "escalate"), False),
            "summary": cls._trim_text(cls._payload_value(payload, "summary"), 160),
        }

    @classmethod
    def _response_error_code(cls, error: Any) -> str:
        message = str(error or "").strip().lower()
        if "invalid verdict: missing" in message:
            return "invalid_verdict_missing"
        if message.startswith("invalid verdict:"):
            return "invalid_verdict_value"
        if "confidence must be within 0..1" in message:
            return "invalid_confidence_range"
        if "json object" in message:
            return "invalid_json_shape"
        if "expecting value" in message or "expecting property name" in message:
            return "invalid_json_shape"
        return "invalid_output"

    @classmethod
    def _response_format_payload(cls, model: str) -> Dict[str, Any]:
        if not cls._is_gpt5_model(model):
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "opus_trader_ai_advisor_review",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(cls.CONTRACT_KEYS),
                    "properties": {
                        "verdict": {
                            "type": "string",
                            "enum": sorted(cls.VALID_VERDICTS),
                        },
                        "confidence": {
                            "type": ["number", "null"],
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                        "reasons": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 3,
                        },
                        "risk_note": {
                            "type": ["string", "null"],
                        },
                        "escalate": {"type": "boolean"},
                        "summary": {
                            "type": ["string", "null"],
                        },
                    },
                },
            },
        }

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are Opus Trader AI Advisor v1, a read-only reviewer for candidate entries. "
            "Respect local gates and risk context as primary truth. "
            "Return strict JSON with keys verdict, confidence, reasons, risk_note, escalate, summary. "
            "verdict must be APPROVE, CAUTION, or REJECT. "
            "Output only compact JSON with no prose outside the JSON object. "
            "Keep reasons to at most 3 short items and summary under 160 chars. "
            "Do not suggest trade execution control or bot mutations."
        )

    def _request_model(self, model: str, context: Dict[str, Any]) -> Dict[str, Any]:
        started_at = self.now_fn()
        payload = {
            "model": model,
            "max_tokens": int(
                getattr(strategy_cfg, "AI_ADVISOR_MAX_OUTPUT_TOKENS", 180)
            ),
            "response_format": self._response_format_payload(model),
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(
                        context,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    ),
                },
            ],
        }
        if (
            self._provider() == "openrouter"
            and payload["response_format"].get("type") == "json_schema"
        ):
            payload["provider"] = {"require_parameters": True}
        if self._is_gpt5_model(model):
            payload["reasoning"] = {"effort": "minimal"}
        else:
            payload["temperature"] = float(
                getattr(strategy_cfg, "AI_ADVISOR_TEMPERATURE", 0.1)
            )
        response = self.session.post(
            self._chat_completions_url(),
            headers=self._response_headers(),
            json=payload,
            timeout=float(getattr(strategy_cfg, "AI_ADVISOR_TIMEOUT_SECONDS", 8.0)),
        )
        response.raise_for_status()
        body = response.json()
        usage = dict(body.get("usage") or {})
        content = self._extract_message_content(body)
        try:
            parsed = self.normalize_response_payload(content)
        except Exception as exc:
            raise AdvisorResponseValidationError(
                str(exc),
                error_code=self._response_error_code(exc),
                raw_response_excerpt=self._trim_text(content, 240),
            ) from exc
        parsed.update(
            {
                "status": "ok",
                "provider": self._provider(),
                "base_url": self._configured_base_url() or None,
                "request_url": self._chat_completions_url(),
                "model": model,
                "latency_ms": int(round((self.now_fn() - started_at) * 1000)),
                "usage": {
                    "prompt_tokens": self._safe_int(usage.get("prompt_tokens"), 0),
                    "completion_tokens": self._safe_int(
                        usage.get("completion_tokens"),
                        0,
                    ),
                    "total_tokens": self._safe_int(usage.get("total_tokens"), 0),
                },
            }
        )
        return parsed

    def _within_symbol_budget(self, symbol: str, now_ts: float) -> bool:
        max_calls = max(
            int(getattr(strategy_cfg, "AI_ADVISOR_MAX_CALLS_PER_SYMBOL_WINDOW", 1)),
            1,
        )
        window_sec = max(
            int(getattr(strategy_cfg, "AI_ADVISOR_CALL_WINDOW_SECONDS", 900)),
            60,
        )
        events = [
            ts
            for ts in self._symbol_call_windows.get(symbol, [])
            if (now_ts - float(ts or 0.0)) < window_sec
        ]
        self._symbol_call_windows[symbol] = events
        return len(events) < max_calls

    def _mark_symbol_call(self, symbol: str, bot_key: str, now_ts: float) -> None:
        events = list(self._symbol_call_windows.get(symbol, []))
        events.append(now_ts)
        self._symbol_call_windows[symbol] = events
        self._bot_last_call_ts[bot_key] = now_ts

    def _bot_min_interval_allows(self, bot: Dict[str, Any], bot_key: str, now_ts: float) -> bool:
        min_interval = self._safe_int(bot.get("ai_advisor_interval_seconds"), 0)
        if min_interval <= 0:
            return True
        last_ts = self._safe_float(self._bot_last_call_ts.get(bot_key), 0.0)
        return (now_ts - last_ts) >= float(min_interval)

    def _should_escalate(self, bot: Dict[str, Any], primary_result: Dict[str, Any]) -> bool:
        if not bool(getattr(strategy_cfg, "AI_ADVISOR_ESCALATION_ENABLED", False)):
            return False
        escalation_model = str(
            getattr(strategy_cfg, "AI_ADVISOR_ESCALATION_MODEL", "") or ""
        ).strip()
        if not escalation_model:
            return False
        if primary_result.get("status") != "ok":
            return False
        confidence_threshold = self._safe_float(
            bot.get("ai_advisor_confidence_threshold"),
            getattr(strategy_cfg, "AI_ADVISOR_PRIMARY_MIN_CONFIDENCE", 0.60),
        )
        confidence = self._safe_float(primary_result.get("confidence"), 0.0)
        verdict = str(primary_result.get("verdict") or "").strip().upper()
        return bool(primary_result.get("escalate")) or (
            verdict == "CAUTION" and confidence < confidence_threshold
        )

    def _record_event(
        self,
        *,
        context: Dict[str, Any],
        fingerprint: str,
        result: Dict[str, Any],
    ) -> None:
        diagnostics_service = getattr(self, "audit_diagnostics_service", None)
        if diagnostics_service is None or not diagnostics_service.enabled():
            return
        payload = {
            "event_type": self.EVENT_TYPE,
            "bot_id": context.get("bot_id"),
            "symbol": context.get("symbol"),
            "mode": context.get("mode"),
            "decision_type": context.get("decision_type"),
            "decision_id": result.get("decision_id"),
            "side_bias": context.get("side_bias"),
            "fingerprint": fingerprint,
            "status": result.get("status"),
            "verdict": result.get("verdict"),
            "confidence": result.get("confidence"),
            "reasons": list(result.get("reasons") or [])[:3],
            "risk_note": result.get("risk_note"),
            "summary": result.get("summary"),
            "model": result.get("model"),
            "provider": result.get("provider"),
            "base_url": result.get("base_url"),
            "escalated": bool(result.get("escalated")),
            "latency_ms": result.get("latency_ms"),
            "usage": dict(result.get("usage") or {}),
            "error": result.get("error"),
            "error_code": result.get("error_code"),
            "raw_response_excerpt": result.get("raw_response_excerpt"),
            "compact_context": {
                "candidate_counts": dict(context.get("candidate_counts") or {}),
                "side_bias": context.get("side_bias"),
                "regime_effective": ((context.get("market") or {}).get("regime_effective")),
                "setup_quality_score": (
                    ((context.get("local_decision") or {}).get("setup_quality") or {}).get("score")
                ),
                "setup_quality_band": (
                    ((context.get("local_decision") or {}).get("setup_quality") or {}).get("band")
                ),
                "gate_blocked": bool(
                    ((context.get("local_decision") or {}).get("gate") or {}).get("blocked")
                ),
                "entry_allowed": bool(
                    ((context.get("local_decision") or {}).get("setup_quality") or {}).get(
                        "entry_allowed"
                    )
                ),
                "entry_signal_code": (
                    ((context.get("local_decision") or {}).get("entry_signal") or {}).get("code")
                ),
                "watchdog_position_cap_active": (
                    (context.get("watchdogs") or {}).get("position_cap_active")
                ),
            },
        }
        diagnostics_service.record_event(
            payload,
            throttle_key=f"{self.EVENT_TYPE}:{context.get('bot_id')}:{fingerprint}:{result.get('model')}",
            throttle_sec=0,
        )

    def review_candidate(
        self,
        *,
        bot: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        mode = str(context.get("mode") or "").strip().lower()
        decision_type = str(context.get("decision_type") or "").strip().lower()
        symbol = str(context.get("symbol") or "").strip().upper()
        fingerprint = self.build_decision_fingerprint(context)
        cache_key = self._decision_key(context)
        now_ts = float(self.now_fn())
        cached = self._decision_cache.get(cache_key)
        dedupe_ttl = max(
            int(getattr(strategy_cfg, "AI_ADVISOR_DEDUPE_TTL_SECONDS", 900)),
            60,
        )
        decision_id = self._build_decision_id(context, fingerprint, now_ts)

        if not self._bot_is_enabled(bot, decision_type, mode):
            result = {
                "status": "disabled",
                "fingerprint": fingerprint,
                "called": False,
            }
            self._record_health_status(status="disabled")
            return result
        if not self._resolved_api_key():
            result = {
                "status": "disabled",
                "fingerprint": fingerprint,
                "called": False,
                "provider": self._provider(),
                "base_url": self._configured_base_url() or None,
                "request_url": self._chat_completions_url(),
                "error": (
                    "OPENROUTER_API_KEY not configured"
                    if self._provider() == "openrouter"
                    else "AI advisor API key not configured"
                ),
            }
            self._record_health_status(
                status="disabled",
                error=result.get("error"),
                missing_key=True,
            )
            return result

        if (
            cached
            and cached.get("fingerprint") == fingerprint
            and (now_ts - self._safe_float(cached.get("ts"), 0.0)) < dedupe_ttl
        ):
            result = dict(cached.get("result") or {})
            result.update(
                {
                    "status": "deduped",
                    "fingerprint": fingerprint,
                    "called": False,
                    "cached": True,
                }
            )
            self._record_health_status(status="deduped", model=result.get("model"))
            return result

        bot_key = cache_key
        if not self._bot_min_interval_allows(bot, bot_key, now_ts):
            result = {
                "status": "rate_limited",
                "fingerprint": fingerprint,
                "called": False,
                "error": "AI advisor min interval active",
            }
            self._record_health_status(status="rate_limited", error=result.get("error"))
            return result
        if not self._within_symbol_budget(symbol, now_ts):
            result = {
                "status": "rate_limited",
                "fingerprint": fingerprint,
                "called": False,
                "error": "AI advisor symbol call budget exhausted",
            }
            self._record_health_status(status="rate_limited", error=result.get("error"))
            return result

        model = str(bot.get("ai_advisor_model") or strategy_cfg.AI_ADVISOR_PRIMARY_MODEL).strip()
        self._health["total_calls"] = int(self._health.get("total_calls", 0) or 0) + 1
        try:
            primary = self._request_model(model, context)
            primary.update(
                {
                    "decision_id": decision_id,
                    "fingerprint": fingerprint,
                    "called": True,
                    "cached": False,
                    "escalated": False,
                }
            )
            self._mark_symbol_call(symbol, bot_key, now_ts)

            final_result = primary
            if self._should_escalate(bot, primary):
                escalation_model = str(strategy_cfg.AI_ADVISOR_ESCALATION_MODEL or "").strip()
                if escalation_model:
                    escalation = self._request_model(escalation_model, context)
                    escalation.update(
                        {
                            "decision_id": decision_id,
                            "fingerprint": fingerprint,
                            "called": True,
                            "cached": False,
                            "escalated": True,
                            "primary_model": model,
                        }
                    )
                    self._mark_symbol_call(symbol, bot_key, float(self.now_fn()))
                    final_result = escalation

            self._decision_cache[cache_key] = {
                "fingerprint": fingerprint,
                "result": dict(final_result),
                "ts": float(self.now_fn()),
            }
            self._record_health_status(status="ok", model=final_result.get("model"))
            self._record_event(
                context=context,
                fingerprint=fingerprint,
                result=final_result,
            )
            return final_result
        except requests.Timeout:
            error_result = {
                "decision_id": decision_id,
                "status": "error",
                "fingerprint": fingerprint,
                "called": True,
                "cached": False,
                "timeout": True,
                "verdict": None,
                "confidence": None,
                "reasons": [],
                "risk_note": None,
                "summary": None,
                "error": "AI advisor request timed out",
                "error_code": "request_timeout",
                "raw_response_excerpt": None,
                "provider": self._provider(),
                "base_url": self._configured_base_url() or None,
                "request_url": self._chat_completions_url(),
                "model": model,
            }
        except Exception as exc:
            error_result = {
                "decision_id": decision_id,
                "status": "error",
                "fingerprint": fingerprint,
                "called": True,
                "cached": False,
                "timeout": False,
                "verdict": None,
                "confidence": None,
                "reasons": [],
                "risk_note": None,
                "summary": None,
                "error": self._trim_text(exc, 200),
                "error_code": getattr(exc, "error_code", None),
                "raw_response_excerpt": self._trim_text(
                    getattr(exc, "raw_response_excerpt", None),
                    240,
                ),
                "provider": self._provider(),
                "base_url": self._configured_base_url() or None,
                "request_url": self._chat_completions_url(),
                "model": model,
            }
            logger.warning("[%s] AI advisor review failed: %s", symbol, exc)

        self._mark_symbol_call(symbol, bot_key, now_ts)
        self._decision_cache[cache_key] = {
            "fingerprint": fingerprint,
            "result": dict(error_result),
            "ts": float(self.now_fn()),
        }
        self._record_health_status(
            status="error",
            model=model,
            error=error_result.get("error"),
            timeout=bool(error_result.get("timeout")),
        )
        self._record_event(
            context=context,
            fingerprint=fingerprint,
            result=error_result,
        )
        return error_result
