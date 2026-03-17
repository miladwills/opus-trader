import json
from pathlib import Path

from services.diagnostics_export_service import DiagnosticsExportService
from services.performance_baseline_service import PerformanceBaselineService


def test_global_reset_creates_archive_and_updates_baseline(tmp_path):
    export_service = DiagnosticsExportService(
        base_dir=str(tmp_path / "storage" / "exports"),
        archive_retention=5,
    )
    service = PerformanceBaselineService(
        file_path=str(tmp_path / "storage" / "performance_baselines.json"),
        diagnostics_export_service=export_service,
    )

    before = service.build_metadata()
    assert before["effective"]["scope"] == "legacy"
    assert before["effective"]["baseline_started_at"] is None

    response = service.reset(
        scope="global",
        note="phase 2 evaluation",
        snapshot={"summary": {"net_pnl": -42.5}},
    )

    assert response["ok"] is True
    assert response["scope"] == "global"
    assert response["archive_path"].endswith(".json")
    assert "performance_reset/" in response["archive_path"]
    assert response["archive_latest_path"].endswith("storage/exports/performance_reset/latest.json")
    assert response["baseline_started_at"]
    assert response["epoch_id"].startswith("global:")

    latest_path = tmp_path / "storage" / "exports" / "performance_reset" / "latest.json"
    assert latest_path.exists()
    archive_payload = json.loads(latest_path.read_text(encoding="utf-8"))
    assert archive_payload["data"]["scope"] == "global"
    assert archive_payload["data"]["note"] == "phase 2 evaluation"
    assert archive_payload["data"]["snapshot"]["summary"]["net_pnl"] == -42.5

    state = json.loads(
        Path(tmp_path / "storage" / "performance_baselines.json").read_text(encoding="utf-8")
    )
    assert state["global"]["baseline_started_at"] == response["baseline_started_at"]
    assert state["global"]["last_archive_path"] == response["archive_path"]
