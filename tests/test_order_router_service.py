import logging
import threading
import time

from services.order_router_service import OrderRouterService


def test_order_router_serializes_commands_per_symbol():
    router = OrderRouterService(default_timeout_sec=2.0)
    started_first = threading.Event()
    release_first = threading.Event()
    completed_second = threading.Event()
    call_order = []
    results = []

    def first_callback():
        call_order.append("first:start")
        started_first.set()
        assert release_first.wait(timeout=1.0)
        call_order.append("first:end")
        return "first-result"

    def second_callback():
        call_order.append("second")
        completed_second.set()
        return "second-result"

    def run_first():
        results.append(router.execute("BTCUSDT", "first", first_callback))

    def run_second():
        results.append(router.execute("BTCUSDT", "second", second_callback))

    thread_one = threading.Thread(target=run_first)
    thread_two = threading.Thread(target=run_second)

    thread_one.start()
    assert started_first.wait(timeout=1.0)
    thread_two.start()
    time.sleep(0.05)
    assert completed_second.is_set() is False

    release_first.set()
    thread_one.join(timeout=1.0)
    thread_two.join(timeout=1.0)
    router.close()

    assert call_order == ["first:start", "first:end", "second"]
    assert sorted(results) == ["first-result", "second-result"]


def test_order_router_adds_queue_timing_for_dict_results():
    router = OrderRouterService(default_timeout_sec=2.0)
    release_first = threading.Event()
    first_started = threading.Event()
    results = []

    def first_callback():
        first_started.set()
        assert release_first.wait(timeout=1.0)
        return {"success": True, "name": "first"}

    def second_callback():
        return {"success": True, "name": "second"}

    thread_one = threading.Thread(
        target=lambda: results.append(router.execute("BTCUSDT", "first", first_callback))
    )
    thread_two = threading.Thread(
        target=lambda: results.append(router.execute("BTCUSDT", "second", second_callback))
    )

    thread_one.start()
    assert first_started.wait(timeout=1.0)
    thread_two.start()
    time.sleep(0.05)
    release_first.set()
    thread_one.join(timeout=1.0)
    thread_two.join(timeout=1.0)
    router.close()

    timed_result = next(item for item in results if item["name"] == "second")
    assert timed_result["timing"]["order_router_wait_ms"] is not None
    assert timed_result["timing"]["order_router_total_ms"] >= timed_result["timing"]["order_router_wait_ms"]


def test_order_router_timeout_returns_ambiguous_in_flight_result(caplog):
    router = OrderRouterService(default_timeout_sec=0.05)
    started = threading.Event()
    release = threading.Event()

    def slow_callback():
        started.set()
        assert release.wait(timeout=1.0)
        return {"success": True}

    with caplog.at_level(logging.WARNING):
        result = router.execute(
            "BTCUSDT",
            "create_order",
            slow_callback,
            timeout_sec=0.05,
        )

    assert started.wait(timeout=1.0)
    assert result["success"] is None
    assert result["status"] == "in_flight"
    assert result["retry_safe"] is False
    assert result["diagnostic_reason"] == "order_router_timeout"
    assert result["truth_check_required"] is True
    assert result["truth_check_status"] == "pending"
    assert "ORDER_ROUTER_TIMEOUT symbol=BTCUSDT action=create_order" in caplog.text

    release.set()
    router.close(timeout_sec=0.5)


def test_order_router_close_logs_unresolved_inflight_work(caplog):
    router = OrderRouterService(default_timeout_sec=0.05)
    started = threading.Event()
    release = threading.Event()

    def slow_callback():
        started.set()
        assert release.wait(timeout=1.0)
        return {"success": True}

    result = router.execute(
        "BTCUSDT",
        "cancel_all_orders",
        slow_callback,
        timeout_sec=0.05,
    )
    assert started.wait(timeout=1.0)
    assert result["success"] is None

    with caplog.at_level(logging.WARNING):
        router.close(timeout_sec=0.05)

    assert "ORDER_ROUTER_SHUTDOWN_PENDING symbol=BTCUSDT" in caplog.text

    release.set()
    time.sleep(0.05)


def test_order_router_close_drains_queued_jobs_before_stopping():
    router = OrderRouterService(default_timeout_sec=0.05)
    started = threading.Event()
    release = threading.Event()
    second_completed = threading.Event()
    results = []

    def first_callback():
        started.set()
        assert release.wait(timeout=1.0)
        return "first-result"

    def second_callback():
        second_completed.set()
        return "second-result"

    thread_one = threading.Thread(
        target=lambda: results.append(
            router.execute("BTCUSDT", "first", first_callback, timeout_sec=1.0)
        )
    )
    thread_two = threading.Thread(
        target=lambda: results.append(
            router.execute("BTCUSDT", "second", second_callback, timeout_sec=1.0)
        )
    )

    thread_one.start()
    assert started.wait(timeout=1.0)
    thread_two.start()
    time.sleep(0.05)

    close_thread = threading.Thread(target=lambda: router.close(timeout_sec=1.0))
    close_thread.start()
    time.sleep(0.05)
    release.set()

    thread_one.join(timeout=1.0)
    thread_two.join(timeout=1.0)
    close_thread.join(timeout=1.0)

    assert second_completed.is_set() is True
    assert sorted(results) == ["first-result", "second-result"]
