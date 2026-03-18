"""Tests for collectors."""

import json
import os
import tempfile
import time

import pytest
from trading_watchdog.collectors.bridge_collector import BridgeCollector
from trading_watchdog.collectors.storage_collector import StorageCollector


class TestBridgeCollector:
    def _write_bridge(self, tmpdir, data):
        path = os.path.join(tmpdir, "bridge.json")
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def test_collect_valid(self, tmp_path):
        data = {
            "version": 1,
            "meta": {"producer": "runner", "producer_pid": 123, "stream_health": {}},
            "snapshot_epoch": 42,
            "sections": {
                "bots_runtime_light": {"bots": [{"id": "b1", "symbol": "BTCUSDT", "status": "running"}]},
                "positions": {"positions": [], "summary": {}},
                "market": {"health": "ok"},
                "summary": {"account": {"equity": 100}},
            }
        }
        path = self._write_bridge(str(tmp_path), data)
        bc = BridgeCollector(path=path)
        result = bc.collect()
        assert result is not None
        assert result["version"] == 1
        assert result["_tw_meta"]["fresh"] is True

    def test_collect_missing_file(self, tmp_path):
        bc = BridgeCollector(path=os.path.join(str(tmp_path), "nope.json"))
        result = bc.collect()
        assert result is None

    def test_get_bots_runtime(self, tmp_path):
        data = {"sections": {"bots_runtime_light": {"bots": [{"id": "b1"}, {"id": "b2"}]}}}
        path = self._write_bridge(str(tmp_path), data)
        bc = BridgeCollector(path=path)
        result = bc.collect()
        bots = bc.get_bots_runtime(result)
        assert len(bots) == 2

    def test_get_bots_empty(self):
        bc = BridgeCollector()
        assert bc.get_bots_runtime(None) == []
        assert bc.get_bots_runtime({}) == []

    def test_get_bridge_meta(self, tmp_path):
        data = {"meta": {"producer_pid": 99}, "snapshot_epoch": 5, "sections": {}}
        path = self._write_bridge(str(tmp_path), data)
        bc = BridgeCollector(path=path)
        result = bc.collect()
        meta = bc.get_bridge_meta(result)
        assert meta["snapshot_epoch"] == 5
        assert meta["producer_pid"] == 99

    def test_corrupt_json_returns_last(self, tmp_path):
        path = os.path.join(str(tmp_path), "bridge.json")
        with open(path, "w") as f:
            json.dump({"version": 1, "sections": {}}, f)

        bc = BridgeCollector(path=path)
        first = bc.collect()
        assert first is not None

        with open(path, "w") as f:
            f.write("{corrupt json")

        second = bc.collect()
        assert second is first  # Returns cached last-good


class TestStorageCollector:
    def test_collect_bots(self, tmp_path, monkeypatch):
        bots_path = os.path.join(str(tmp_path), "bots.json")
        with open(bots_path, "w") as f:
            json.dump([{"id": "b1", "symbol": "ETH"}], f)
        monkeypatch.setattr("trading_watchdog.collectors.storage_collector.BOTS_PATH", bots_path)

        sc = StorageCollector()
        result = sc.collect_bots()
        assert len(result["bots"]) == 1
        assert result["fresh"] is True

    def test_collect_missing_returns_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "trading_watchdog.collectors.storage_collector.BOTS_PATH",
            os.path.join(str(tmp_path), "missing.json"),
        )
        sc = StorageCollector()
        result = sc.collect_bots()
        assert result["bots"] == []
        assert result["fresh"] is False

    def test_collect_trade_logs_bounded(self, tmp_path, monkeypatch):
        logs_path = os.path.join(str(tmp_path), "trade_logs.json")
        with open(logs_path, "w") as f:
            json.dump([{"id": i} for i in range(500)], f)
        monkeypatch.setattr("trading_watchdog.collectors.storage_collector.TRADE_LOGS_PATH", logs_path)

        sc = StorageCollector()
        result = sc.collect_trade_logs()
        assert len(result["trades"]) == 200  # Bounded to last 200
