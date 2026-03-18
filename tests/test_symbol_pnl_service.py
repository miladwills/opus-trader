from services.symbol_pnl_service import SymbolPnlService


def test_get_all_symbols_pnl_excludes_bot_scoped_entries(tmp_path):
    service = SymbolPnlService(str(tmp_path / "symbol_pnl.json"))
    service._write_data(
        {
            "BTCUSDT": {"symbol": "BTCUSDT", "net_pnl": 1.0},
            "bot:bot-1": {"bot_id": "bot-1", "symbol": "BTCUSDT", "net_pnl": 1.0},
            "ETHUSDT": {"symbol": "ETHUSDT", "net_pnl": -0.5},
        }
    )

    result = service.get_all_symbols_pnl()

    assert result == {
        "BTCUSDT": {"symbol": "BTCUSDT", "net_pnl": 1.0},
        "ETHUSDT": {"symbol": "ETHUSDT", "net_pnl": -0.5},
    }


def test_get_all_pnl_data_returns_symbol_and_bot_entries(tmp_path):
    service = SymbolPnlService(str(tmp_path / "symbol_pnl.json"))
    payload = {
        "BTCUSDT": {"symbol": "BTCUSDT", "net_pnl": 1.0},
        "bot:bot-1": {"bot_id": "bot-1", "symbol": "BTCUSDT", "net_pnl": 1.0},
    }
    service._write_data(payload)

    result = service.get_all_pnl_data()

    assert result == payload
