
import unittest
from unittest.mock import MagicMock, patch
from services.indicator_service import IndicatorService
from datetime import datetime, timezone

class TestIndicatorCache(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_client._get_now_ts.return_value = 1700000000
        self.service = IndicatorService(self.mock_client)

    def test_cache_reuse_smaller_limit(self):
        # 1. Setup mock response for limit 1000
        mock_kline_data = {
            "success": True,
            "data": {
                "list": [[str(1700000000000 - i * 900000), "100", "110", "90", "105", "1000"] for i in range(1000)]
            }
        }
        self.mock_client.get_kline.return_value = mock_kline_data

        # 2. Fetch limit 1000
        symbol = "BTCUSDT"
        interval = "15"
        candles_1000 = self.service.get_ohlcv(symbol, interval, limit=1000)
        
        self.assertEqual(len(candles_1000), 1000)
        self.assertEqual(self.mock_client.get_kline.call_count, 1)

        # 3. Fetch limit 200 - should reuse cache
        candles_200 = self.service.get_ohlcv(symbol, interval, limit=200)
        
        self.assertEqual(len(candles_200), 200)
        # Call count should still be 1
        self.assertEqual(self.mock_client.get_kline.call_count, 1)
        
        # Verify it's the same latest candle
        self.assertEqual(candles_200[-1]["close"], candles_1000[-1]["close"])

    def test_cache_miss_larger_limit(self):
        # 1. Setup mock response for limit 200
        self.mock_client.get_kline.return_value = {
            "success": True,
            "data": {
                "list": [[str(1700000000000 - i * 900000), "100", "110", "90", "105", "1000"] for i in range(200)]
            }
        }

        # 2. Fetch limit 200
        self.service.get_ohlcv("BTCUSDT", "15", limit=200)
        self.assertEqual(self.mock_client.get_kline.call_count, 1)

        # 3. Fetch limit 1000 - should be a miss because cached is only 200
        self.mock_client.get_kline.return_value = {
            "success": True,
            "data": {
                "list": [[str(1700000000000 - i * 900000), "100", "110", "90", "105", "1000"] for i in range(1000)]
            }
        }
        self.service.get_ohlcv("BTCUSDT", "15", limit=1000)
        self.assertEqual(self.mock_client.get_kline.call_count, 2)

    def test_indicator_cache_reuse(self):
        # Setup mock for compute_indicators (indirectly uses get_ohlcv)
        mock_kline_data = {
            "success": True,
            "data": {
                "list": [[str(1700000000000 - i * 900000), "100", "110", "90", "105", "1000"] for i in range(1000)]
            }
        }
        self.mock_client.get_kline.return_value = mock_kline_data

        # 1. Compute for 1000
        self.service.compute_indicators("BTCUSDT", "15", limit=1000)
        self.assertEqual(self.mock_client.get_kline.call_count, 1)

        # 2. Compute for 200 - should reuse indicator cache
        # We'll patch compute_rsi etc if needed, but the main goal is to check if it returns early
        self.service.compute_indicators("BTCUSDT", "15", limit=200)
        
        # Should NOT have called get_ohlcv again for the second compute_indicators call
        # because it hits the _indicator_cache reuse logic.
        self.assertEqual(self.mock_client.get_kline.call_count, 1)

    def test_prefers_stream_kline_snapshot_when_available(self):
        stream_service = MagicMock()
        stream_service.get_kline_response.return_value = {
            "success": True,
            "from_stream": True,
            "data": {
                "list": [
                    ["1700000900000", "101", "111", "91", "106", "1001", "0"],
                    ["1700000000000", "100", "110", "90", "105", "1000", "0"],
                ]
            },
        }
        self.mock_client.stream_service = stream_service

        candles = self.service.get_ohlcv("BTCUSDT", "15", limit=2)

        self.assertEqual(len(candles), 2)
        self.assertEqual(candles[-1]["close"], 106.0)
        self.mock_client.get_kline.assert_not_called()

    def test_seeds_stream_cache_after_rest_fetch(self):
        stream_service = MagicMock()
        stream_service.get_kline_response.return_value = None
        self.mock_client.stream_service = stream_service
        self.mock_client.get_kline.return_value = {
            "success": True,
            "data": {
                "list": [
                    ["1700000900000", "101", "111", "91", "106", "1001", "0"],
                    ["1700000000000", "100", "110", "90", "105", "1000", "0"],
                ]
            },
        }

        candles = self.service.get_ohlcv("BTCUSDT", "15", limit=2)

        self.assertEqual(len(candles), 2)
        stream_service.seed_kline_snapshot.assert_called_once()

    def test_falls_back_to_rest_when_stream_kline_is_missing(self):
        stream_service = MagicMock()
        stream_service.get_kline_response.return_value = None
        self.mock_client.stream_service = stream_service
        self.mock_client.get_kline.return_value = {
            "success": True,
            "data": {
                "list": [
                    ["1700000900000", "101", "111", "91", "106", "1001", "0"],
                    ["1700000000000", "100", "110", "90", "105", "1000", "0"],
                ]
            },
        }

        candles = self.service.get_ohlcv("BTCUSDT", "15", limit=2)

        self.assertEqual(len(candles), 2)
        self.assertEqual(self.mock_client.get_kline.call_count, 1)

    def test_prefers_stream_kline_snapshot_for_60m_when_available(self):
        stream_service = MagicMock()
        stream_service.get_kline_response.return_value = {
            "success": True,
            "from_stream": True,
            "data": {
                "list": [
                    ["1700003600000", "201", "211", "191", "206", "2001", "0"],
                    ["1700000000000", "200", "210", "190", "205", "2000", "0"],
                ]
            },
        }
        self.mock_client.stream_service = stream_service

        candles = self.service.get_ohlcv("BTCUSDT", "60", limit=2)

        self.assertEqual(len(candles), 2)
        self.assertEqual(candles[-1]["close"], 206.0)
        self.mock_client.get_kline.assert_not_called()

    def test_60m_small_request_promotes_to_canonical_transport_bundle(self):
        self.mock_client.get_kline.return_value = {
            "success": True,
            "data": {
                "list": [
                    [str(1700000000000 - i * 3600000), "200", "210", "190", str(205 + i), "2000"]
                    for i in range(200)
                ]
            },
        }

        candles_50 = self.service.get_ohlcv("BTCUSDT", "60", limit=50)
        candles_200 = self.service.get_ohlcv("BTCUSDT", "60", limit=200)

        self.assertEqual(len(candles_50), 50)
        self.assertEqual(len(candles_200), 200)
        self.assertEqual(self.mock_client.get_kline.call_count, 1)
        self.assertEqual(
            self.mock_client.get_kline.call_args.kwargs,
            {"symbol": "BTCUSDT", "interval": "60", "limit": 200},
        )
        self.assertEqual(candles_50[-1], candles_200[-1])

    def test_high_tf_request_above_bundle_limit_keeps_explicit_limit(self):
        self.mock_client.get_kline.return_value = {
            "success": True,
            "data": {
                "list": [
                    [str(1700000000000 - i * 14400000), "300", "310", "290", str(305 + i), "3000"]
                    for i in range(250)
                ]
            },
        }

        candles = self.service.get_ohlcv("BTCUSDT", "240", limit=250)

        self.assertEqual(len(candles), 250)
        self.mock_client.get_kline.assert_called_once_with(
            symbol="BTCUSDT",
            interval="240",
            limit=250,
        )

if __name__ == "__main__":
    unittest.main()
