"""Tests for AI Ops collector and source functions."""

import asyncio
import json
import os
import tempfile
import time
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from opus_aiops.collector import (
    _read_bridge_bots_light,
    _read_log_tail,
    StaggeredCollector,
)
from opus_aiops.models import SystemSnapshot


class TestReadBridgeBotsLight:
    def test_missing_file(self):
        with patch("opus_aiops.collector.config") as cfg:
            cfg.BRIDGE_JSON_PATH = "/nonexistent/path.json"
            result = _read_bridge_bots_light()
            assert "source_error" in result

    def test_valid_bridge_file(self):
        bridge_data = {
            "sections": {
                "bots_runtime_light": {
                    "payload": {
                        "bots": [
                            {"bot_id": "a", "lifecycle_status": "running"},
                            {"bot_id": "b", "lifecycle_status": "stopped"},
                        ]
                    }
                }
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bridge_data, f)
            path = f.name

        try:
            with patch("opus_aiops.collector.config") as cfg:
                cfg.BRIDGE_JSON_PATH = path
                result = _read_bridge_bots_light()
                assert "bridge_bots_light" in result
                assert len(result["bridge_bots_light"]) == 2
        finally:
            os.unlink(path)


class TestReadLogTail:
    def test_missing_file(self):
        result = _read_log_tail("/nonexistent/log.txt", 1024)
        assert result == []

    def test_small_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("line1\nline2\nline3\n")
            path = f.name

        try:
            result = _read_log_tail(path, 65536)
            assert len(result) == 3
            assert "line1\n" in result
        finally:
            os.unlink(path)

    def test_bounded_read(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            for i in range(1000):
                f.write(f"line {i}: some content here\n")
            path = f.name

        try:
            result = _read_log_tail(path, 512)
            # Should only get the tail, not all 1000 lines
            assert len(result) < 1000
            assert len(result) > 0
        finally:
            os.unlink(path)


class TestStaggeredCollector:
    @pytest.mark.asyncio
    async def test_initial_collect_runs_all_lanes(self):
        collector = StaggeredCollector()

        # Mock the HTTP clients
        mock_watchdog = AsyncMock()
        mock_trader = AsyncMock()
        collector._watchdog_client = mock_watchdog
        collector._trader_client = mock_trader

        # Mock all fetch functions to return clean data
        with patch("opus_aiops.collector.fetch_watchdog_health", return_value={"health_score": 90.0, "health_status": "healthy"}), \
             patch("opus_aiops.collector.fetch_trader_status", return_value={"runner_active": True}), \
             patch("opus_aiops.collector.fetch_watchdog_incidents", return_value={"active_incidents": []}), \
             patch("opus_aiops.collector.fetch_watchdog_probes", return_value={"probe_results": {}}), \
             patch("opus_aiops.collector.fetch_trader_health_summary", return_value={"bot_total": 2, "bot_status_counts": {}}), \
             patch("opus_aiops.collector.fetch_trader_bridge_diagnostics", return_value={"bridge_diagnostics": {}}), \
             patch("opus_aiops.collector.fetch_file_sources", return_value={"runner_log_lines": [], "app_log_lines": []}):

            snapshot = await collector.collect()
            assert isinstance(snapshot, SystemSnapshot)
            assert snapshot.health_score == 90.0
            assert snapshot.runner_active is True
            assert collector.collection_count == 1

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_source_failure(self):
        collector = StaggeredCollector()
        collector._watchdog_client = AsyncMock()
        collector._trader_client = AsyncMock()

        with patch("opus_aiops.collector.fetch_watchdog_health", return_value={"source_error": "connection refused"}), \
             patch("opus_aiops.collector.fetch_trader_status", return_value={"runner_active": True}), \
             patch("opus_aiops.collector.fetch_watchdog_incidents", return_value={"active_incidents": []}), \
             patch("opus_aiops.collector.fetch_watchdog_probes", return_value={"probe_results": {}}), \
             patch("opus_aiops.collector.fetch_trader_health_summary", return_value={"bot_total": 1}), \
             patch("opus_aiops.collector.fetch_trader_bridge_diagnostics", return_value={"bridge_diagnostics": {}}), \
             patch("opus_aiops.collector.fetch_file_sources", return_value={"runner_log_lines": [], "app_log_lines": []}):

            snapshot = await collector.collect()
            # Should still succeed with partial data
            assert isinstance(snapshot, SystemSnapshot)
            assert snapshot.health_score is None  # watchdog failed
            assert snapshot.runner_active is True  # trader succeeded
            assert "watchdog_health" in snapshot.source_errors

    @pytest.mark.asyncio
    async def test_lane_cadence_respected(self):
        collector = StaggeredCollector()
        collector._watchdog_client = AsyncMock()
        collector._trader_client = AsyncMock()

        mock_returns = {
            "fetch_watchdog_health": {"health_score": 90.0, "health_status": "healthy"},
            "fetch_trader_status": {"runner_active": True},
            "fetch_watchdog_incidents": {"active_incidents": []},
            "fetch_watchdog_probes": {"probe_results": {}},
            "fetch_trader_health_summary": {"bot_total": 2},
            "fetch_trader_bridge_diagnostics": {"bridge_diagnostics": {}},
            "fetch_file_sources": {"runner_log_lines": [], "app_log_lines": []},
        }

        with patch("opus_aiops.collector.fetch_watchdog_health", return_value=mock_returns["fetch_watchdog_health"]) as wh, \
             patch("opus_aiops.collector.fetch_trader_status", return_value=mock_returns["fetch_trader_status"]) as ts, \
             patch("opus_aiops.collector.fetch_watchdog_incidents", return_value=mock_returns["fetch_watchdog_incidents"]) as wi, \
             patch("opus_aiops.collector.fetch_watchdog_probes", return_value=mock_returns["fetch_watchdog_probes"]) as wp, \
             patch("opus_aiops.collector.fetch_trader_health_summary", return_value=mock_returns["fetch_trader_health_summary"]) as ths, \
             patch("opus_aiops.collector.fetch_trader_bridge_diagnostics", return_value=mock_returns["fetch_trader_bridge_diagnostics"]) as tbd, \
             patch("opus_aiops.collector.fetch_file_sources", return_value=mock_returns["fetch_file_sources"]) as fs:

            # First collect: all lanes fire
            await collector.collect()
            assert wh.call_count == 1  # fast
            assert wi.call_count == 1  # medium
            assert tbd.call_count == 1  # slow

            # Second collect immediately: no lanes should fire (cadence not elapsed)
            await collector.collect()
            assert wh.call_count == 1  # still 1
            assert wi.call_count == 1
            assert tbd.call_count == 1
