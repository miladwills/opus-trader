from services.bot_manager_service import BotManagerService
from services.grid_bot_service import GridBotService


def test_launch_analysis_honors_manual_open_order_cap_override():
    service = BotManagerService.__new__(BotManagerService)
    service.client = None
    service.account_service = None
    service.risk_manager = None
    service._safe_float = BotManagerService._safe_float
    service._requested_grid_count = BotManagerService._requested_grid_count
    service._compute_fee_aware_min_step_pct = (
        BotManagerService._compute_fee_aware_min_step_pct.__get__(
            service, BotManagerService
        )
    )
    service._get_account_snapshot = lambda: {"equity": 100.0, "available_balance": 100.0}
    service._compute_capital_partition = lambda *args, **kwargs: 11.08
    service._get_symbol_launch_constraints = (
        lambda symbol: {"max_leverage": 10.0, "min_notional_value": 5.0}
    )

    analysis = service.analyze_launch(
        {
            "symbol": "PIPPINUSDT",
            "mode": "long",
            "investment": 11.08,
            "leverage": 10.0,
            "grid_count": 8,
            "manual_runtime_open_order_cap_total": 4,
        }
    )

    assert analysis["affordable"] is True
    assert analysis["max_active_open_orders"] == 4
    assert analysis["manual_runtime_open_order_cap_total"] == 4
    assert "manual open-order cap override applied: 4" in analysis["notes"]


def test_ai_max_position_cap_override_is_per_bot():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._ai_cap_bounds = GridBotService._ai_cap_bounds.__get__(
        service, GridBotService
    )
    service._get_ai_max_position_cap_pct = GridBotService._get_ai_max_position_cap_pct.__get__(
        service, GridBotService
    )

    assert service._get_ai_max_position_cap_pct({}, "PIPPINUSDT") == 60.0
    assert (
        service._get_ai_max_position_cap_pct(
            {"ai_max_position_cap_pct": 55}, "PIPPINUSDT"
        )
        == 55.0
    )


def test_manual_runtime_open_order_cap_override_is_per_bot():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._get_manual_runtime_open_order_cap_total = (
        GridBotService._get_manual_runtime_open_order_cap_total.__get__(
            service, GridBotService
        )
    )

    assert service._get_manual_runtime_open_order_cap_total({}) == 0
    assert (
        service._get_manual_runtime_open_order_cap_total(
            {"manual_runtime_open_order_cap_total": 4}
        )
        == 4
    )


def test_manual_quick_profit_recenter_width_mult_is_per_bot():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._get_manual_quick_profit_recenter_width_mult = (
        GridBotService._get_manual_quick_profit_recenter_width_mult.__get__(
            service, GridBotService
        )
    )

    assert service._get_manual_quick_profit_recenter_width_mult({}) == 1.0
    assert (
        service._get_manual_quick_profit_recenter_width_mult(
            {"manual_quick_profit_recenter_width_mult": 0.75}
        )
        == 0.75
    )


def test_quick_profit_recenter_subset_rule_matches_only_long_dynamic_clustered():
    service = GridBotService.__new__(GridBotService)
    service._is_quick_profit_recenter_width_subset_bot = (
        GridBotService._is_quick_profit_recenter_width_subset_bot.__get__(
            service, GridBotService
        )
    )

    assert (
        service._is_quick_profit_recenter_width_subset_bot(
            {
                "mode": "long",
                "range_mode": "dynamic",
                "grid_distribution": "clustered",
            }
        )
        is True
    )
    assert (
        service._is_quick_profit_recenter_width_subset_bot(
            {
                "mode": "long",
                "range_mode": "trailing",
                "grid_distribution": "clustered",
            }
        )
        is False
    )
    assert (
        service._is_quick_profit_recenter_width_subset_bot(
            {
                "mode": "short",
                "range_mode": "dynamic",
                "grid_distribution": "clustered",
            }
        )
        is False
    )
    assert (
        service._is_quick_profit_recenter_width_subset_bot(
            {
                "mode": "long",
                "range_mode": "dynamic",
                "grid_distribution": "balanced",
            }
        )
        is False
    )


def test_quick_profit_recenter_width_policy_preserves_manual_priority():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._is_quick_profit_recenter_width_subset_bot = (
        GridBotService._is_quick_profit_recenter_width_subset_bot.__get__(
            service, GridBotService
        )
    )
    service._resolve_quick_profit_recenter_width_policy = (
        GridBotService._resolve_quick_profit_recenter_width_policy.__get__(
            service, GridBotService
        )
    )

    mult, source = service._resolve_quick_profit_recenter_width_policy(
        {
            "symbol": "PIPPINUSDT",
            "mode": "long",
            "range_mode": "dynamic",
            "grid_distribution": "clustered",
            "manual_quick_profit_recenter_width_mult": 0.75,
        }
    )

    assert mult == 0.75
    assert source == "manual_override"


def test_quick_profit_recenter_width_policy_applies_subset_default_only_to_matching_bots():
    service = GridBotService.__new__(GridBotService)
    service._safe_float = GridBotService._safe_float.__get__(service, GridBotService)
    service._is_quick_profit_recenter_width_subset_bot = (
        GridBotService._is_quick_profit_recenter_width_subset_bot.__get__(
            service, GridBotService
        )
    )
    service._resolve_quick_profit_recenter_width_policy = (
        GridBotService._resolve_quick_profit_recenter_width_policy.__get__(
            service, GridBotService
        )
    )

    matching_mult, matching_source = service._resolve_quick_profit_recenter_width_policy(
        {
            "mode": "long",
            "range_mode": "dynamic",
            "grid_distribution": "clustered",
        }
    )
    non_matching_mult, non_matching_source = (
        service._resolve_quick_profit_recenter_width_policy(
            {
                "mode": "long",
                "range_mode": "trailing",
                "grid_distribution": "clustered",
            }
        )
    )

    assert matching_mult == 0.8
    assert matching_source == "subset_dynamic_long_clustered"
    assert non_matching_mult == 1.0
    assert non_matching_source == "default"
