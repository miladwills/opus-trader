"""Tests for direct runtime process probes."""

import asyncio
from io import StringIO
from pathlib import Path

from opus_platform_watchdog.probes.process_probes import (
    DirectRuntimeProbe,
    SystemResourcesProbe,
)


class _FakeProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self):
        return self._stdout.encode(), self._stderr.encode()


def test_direct_runtime_probe_prefers_pid_and_port_truth_over_systemd(monkeypatch):
    calls = []

    async def _fake_exec(*args, **kwargs):
        calls.append(args)
        if args[:3] == ("ps", "-eo", "pid=,args="):
            return _FakeProc(
                stdout="50646 /var/www/venv/bin/python /var/www/app.py\n"
            )
        if args[0] == "lsof":
            return _FakeProc(
                stdout=(
                    "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
                    "python 50646 claude 5u IPv4 0 0t0 TCP 127.0.0.1:8000 (LISTEN)\n"
                )
            )
        if args[:2] == ("systemctl", "is-active"):
            return _FakeProc(stdout="activating\n", returncode=3)
        raise AssertionError(f"unexpected exec args: {args}")

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        _fake_exec,
    )

    probe = DirectRuntimeProbe(
        probe_name="proc_trader",
        script_path="/var/www/app.py",
        label="app.py",
        match_terms=[
            "./venv/bin/python app.py",
            "gunicorn -c gunicorn.conf.py app:app",
        ],
        port=8000,
        systemd_unit="opus_trader",
    )

    result = asyncio.run(probe.execute())

    assert result.success is True
    assert result.status == "ok"
    assert result.detail["pid"] == 50646
    assert result.detail["port"] == 8000
    assert result.detail["port_listening"] is True
    assert result.detail["state"] == "listening"
    assert result.detail["systemd_state"] == "activating"
    assert any(call[:2] == ("systemctl", "is-active") for call in calls)


def test_direct_runtime_probe_matches_gunicorn_runtime_command(monkeypatch):
    async def _fake_exec(*args, **kwargs):
        if args[:3] == ("ps", "-eo", "pid=,args="):
            return _FakeProc(
                stdout=(
                    "52724 /var/www/venv/bin/python3 /var/www/venv/bin/gunicorn -c "
                    "gunicorn.conf.py app:app\n"
                )
            )
        if args[0] == "lsof":
            return _FakeProc(
                stdout=(
                    "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
                    "gunicorn 52724 claude 3u IPv4 0 0t0 TCP *:8000 (LISTEN)\n"
                )
            )
        if args[:2] == ("systemctl", "is-active"):
            return _FakeProc(stdout="activating\n", returncode=3)
        raise AssertionError(f"unexpected exec args: {args}")

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        _fake_exec,
    )

    probe = DirectRuntimeProbe(
        probe_name="proc_trader",
        script_path="/var/www/app.py",
        label="app.py",
        match_terms=[
            "./venv/bin/python app.py",
            "gunicorn -c gunicorn.conf.py app:app",
        ],
        port=8000,
        systemd_unit="opus_trader",
    )

    result = asyncio.run(probe.execute())

    assert result.success is True
    assert result.status == "ok"
    assert result.detail["pid"] == 52724
    assert result.detail["port_listening"] is True
    assert result.detail["state"] == "listening"


def test_direct_runtime_probe_matches_relative_app_command_listener(monkeypatch):
    async def _fake_exec(*args, **kwargs):
        if args[:3] == ("ps", "-eo", "pid=,args="):
            return _FakeProc(
                stdout=(
                    "53780 ./venv/bin/python app.py\n"
                    "53888 /var/www/venv/bin/python3 /var/www/venv/bin/gunicorn -c "
                    "gunicorn.conf.py app:app\n"
                )
            )
        if args[0] == "lsof":
            return _FakeProc(
                stdout=(
                    "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
                    "python 53780 claude 5u IPv4 0 0t0 TCP 127.0.0.1:8000 (LISTEN)\n"
                )
            )
        if args[:2] == ("systemctl", "is-active"):
            return _FakeProc(stdout="activating\n", returncode=3)
        raise AssertionError(f"unexpected exec args: {args}")

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        _fake_exec,
    )

    probe = DirectRuntimeProbe(
        probe_name="proc_trader",
        script_path="/var/www/app.py",
        label="app.py",
        match_terms=[
            "./venv/bin/python app.py",
            "gunicorn -c gunicorn.conf.py app:app",
        ],
        port=8000,
        systemd_unit="opus_trader",
    )

    result = asyncio.run(probe.execute())

    assert result.success is True
    assert result.status == "ok"
    assert result.detail["pid"] == 53780
    assert result.detail["port_listening"] is True
    assert result.detail["state"] == "listening"


def test_direct_runtime_probe_marks_app_down_when_pid_exists_but_port_is_missing(monkeypatch):
    async def _fake_exec(*args, **kwargs):
        if args[:3] == ("ps", "-eo", "pid=,args="):
            return _FakeProc(
                stdout="50646 /var/www/venv/bin/python /var/www/app.py\n"
            )
        if args[0] == "lsof":
            return _FakeProc(stdout="", returncode=1)
        if args[:2] == ("systemctl", "is-active"):
            return _FakeProc(stdout="active\n")
        raise AssertionError(f"unexpected exec args: {args}")

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        _fake_exec,
    )

    probe = DirectRuntimeProbe(
        probe_name="proc_trader",
        script_path="/var/www/app.py",
        label="app.py",
        port=8000,
        systemd_unit="opus_trader",
    )

    result = asyncio.run(probe.execute())

    assert result.success is True
    assert result.status == "down"
    assert result.detail["pid"] == 50646
    assert result.detail["port_listening"] is False
    assert result.detail["state"] == "port_not_listening"


def test_direct_runtime_probe_marks_runner_running_without_port(monkeypatch):
    async def _fake_exec(*args, **kwargs):
        if args[:3] == ("ps", "-eo", "pid=,args="):
            return _FakeProc(
                stdout="50659 /var/www/venv/bin/python /var/www/runner.py\n"
            )
        if args[:2] == ("systemctl", "is-active"):
            return _FakeProc(stdout="inactive\n", returncode=3)
        raise AssertionError(f"unexpected exec args: {args}")

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        _fake_exec,
    )

    probe = DirectRuntimeProbe(
        probe_name="proc_runner",
        script_path="/var/www/runner.py",
        label="runner.py",
        match_terms=["./venv/bin/python runner.py"],
        systemd_unit="opus_runner",
    )

    result = asyncio.run(probe.execute())

    assert result.success is True
    assert result.status == "ok"
    assert result.detail["pid"] == 50659
    assert result.detail["state"] == "running"
    assert result.detail["systemd_state"] == "inactive"


def test_system_resources_probe_reports_cpu_usage_after_second_sample(monkeypatch):
    proc_stat_samples = iter(
        [
            "cpu  100 0 50 800 0 0 0 0 0 0\n",
            "cpu  160 0 90 860 0 0 0 0 0 0\n",
        ]
    )

    def _fake_open(path, *args, **kwargs):
        if path == "/proc/loadavg":
            return StringIO("1.00 0.80 0.50 1/100 12345\n")
        if path == "/proc/meminfo":
            return StringIO("MemTotal: 2048000 kB\nMemAvailable: 1024000 kB\n")
        if path == "/proc/stat":
            return StringIO(next(proc_stat_samples))
        raise AssertionError(f"unexpected open path: {path}")

    statvfs_result = type(
        "FakeStatvfs",
        (),
        {"f_blocks": 1000, "f_frsize": 1024 * 1024, "f_bavail": 400},
    )()

    monkeypatch.setattr("builtins.open", _fake_open)
    monkeypatch.setattr("os.statvfs", lambda _path: statvfs_result)

    probe = SystemResourcesProbe()

    first = asyncio.run(probe.execute())
    second = asyncio.run(probe.execute())

    assert first.status == "ok"
    assert first.detail.get("cpu_used_pct") is None
    assert second.detail["cpu_used_pct"] == 62.5
    assert second.detail["mem_used_pct"] == 50.0


def test_system_template_shows_cpu_resource_slot():
    template_text = (
        Path(__file__).resolve().parents[1] / "templates" / "system.html"
    ).read_text()

    assert "System Resources" in template_text
    assert ">CPU<" in template_text
    assert "cpu_used_pct" in template_text


def test_direct_runtime_probe_matches_relative_runner_command(monkeypatch):
    async def _fake_exec(*args, **kwargs):
        if args[:3] == ("ps", "-eo", "pid=,args="):
            return _FakeProc(
                stdout="53387 ./venv/bin/python runner.py\n"
            )
        if args[:2] == ("systemctl", "is-active"):
            return _FakeProc(stdout="inactive\n", returncode=3)
        raise AssertionError(f"unexpected exec args: {args}")

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        _fake_exec,
    )

    probe = DirectRuntimeProbe(
        probe_name="proc_runner",
        script_path="/var/www/runner.py",
        label="runner.py",
        match_terms=["./venv/bin/python runner.py"],
        systemd_unit="opus_runner",
    )

    result = asyncio.run(probe.execute())

    assert result.success is True
    assert result.status == "ok"
    assert result.detail["pid"] == 53387
    assert result.detail["state"] == "running"
