from services.grid_bot_service import GridBotService


def make_service():
    return GridBotService.__new__(GridBotService)


def test_learned_scalp_opening_cap_uses_lowest_margin_ceiling():
    service = make_service()
    bot = {}

    learned = service._learn_scalp_opening_order_cap(
        bot=bot,
        opening_order_count=21,
        requested_cap=25,
        now_iso="2026-03-06T18:44:00+00:00",
        reason="insufficient_margin",
    )
    assert learned == 21
    assert bot["scalp_learned_opening_order_cap"] == 21

    learned = service._learn_scalp_opening_order_cap(
        bot=bot,
        opening_order_count=23,
        requested_cap=25,
        now_iso="2026-03-06T18:45:00+00:00",
        reason="insufficient_margin",
    )
    assert learned == 21
    assert bot["scalp_learned_opening_order_cap"] == 21


def test_scalp_opening_cap_relaxes_by_one_when_margin_recovers():
    service = make_service()
    bot = {"scalp_learned_opening_order_cap": 21}

    relaxed = service._maybe_relax_scalp_opening_order_cap(
        bot=bot,
        current_opening_order_count=21,
        requested_cap=25,
        available_balance=5.0,
        reserve_usd=1.0,
        margin_per_order=0.75,
        now_iso="2026-03-06T18:46:00+00:00",
    )

    assert relaxed == 22
    assert bot["scalp_learned_opening_order_cap"] == 22
    assert bot["scalp_learned_opening_cap_reason"] == "margin_recovered"


def test_flat_scalp_one_sided_guard_blocks_when_buy_side_is_gone():
    service = make_service()

    should_skip, missing_side = service._should_skip_flat_scalp_one_sided_grid(
        flat_position=True,
        current_opening_buy_count=0,
        current_opening_sell_count=0,
        buy_levels_needed=[],
        sell_levels_needed=[17.1, 17.2],
    )

    assert should_skip is True
    assert missing_side == "buy"


def test_flat_scalp_one_sided_guard_allows_balanced_or_non_flat_cycles():
    service = make_service()

    should_skip, missing_side = service._should_skip_flat_scalp_one_sided_grid(
        flat_position=True,
        current_opening_buy_count=0,
        current_opening_sell_count=0,
        buy_levels_needed=[16.9],
        sell_levels_needed=[17.1],
    )
    assert should_skip is False
    assert missing_side is None

    should_skip, missing_side = service._should_skip_flat_scalp_one_sided_grid(
        flat_position=False,
        current_opening_buy_count=0,
        current_opening_sell_count=0,
        buy_levels_needed=[],
        sell_levels_needed=[17.1],
    )
    assert should_skip is False
    assert missing_side is None


def test_flat_scalp_one_sided_guard_respects_existing_opening_orders():
    service = make_service()

    should_skip, missing_side = service._should_skip_flat_scalp_one_sided_grid(
        flat_position=True,
        current_opening_buy_count=12,
        current_opening_sell_count=12,
        buy_levels_needed=[],
        sell_levels_needed=[17.2],
    )

    assert should_skip is False
    assert missing_side is None
