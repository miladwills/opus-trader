from services.bot_manager_service import BotManagerService


class _StubStorage:
    def save_bot(self, bot):
        saved = dict(bot)
        saved.setdefault("id", "bot-1")
        return saved


def make_service():
    service = BotManagerService.__new__(BotManagerService)
    service.bot_storage = _StubStorage()
    service.client = None
    service.risk_manager = None
    service.account_service = None
    service._compute_min_notional_requirement = lambda bot_data: None
    return service


def test_blank_tp_pct_stays_empty():
    service = make_service()

    saved = service.create_or_update_bot(
        {
            "symbol": "BTCUSDT",
            "lower_price": 90000,
            "upper_price": 100000,
            "investment": 100,
            "leverage": 3,
            "mode": "long",
            "tp_pct": None,
        }
    )

    assert saved["tp_pct"] is None


def test_positive_tp_pct_is_preserved():
    service = make_service()

    saved = service.create_or_update_bot(
        {
            "symbol": "BTCUSDT",
            "lower_price": 90000,
            "upper_price": 100000,
            "investment": 100,
            "leverage": 3,
            "mode": "long",
            "tp_pct": 0.025,
        }
    )

    assert saved["tp_pct"] == 0.025
