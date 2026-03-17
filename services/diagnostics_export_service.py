import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class DiagnosticsExportService:
    """Persist compact diagnostics exports with a small archive retention window."""

    def __init__(
        self,
        *,
        base_dir: str = "storage/exports",
        archive_retention: int = 50,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.archive_retention = max(int(archive_retention or 0), 1)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _parse_iso(value: Any) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        normalized = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _normalize_json_value(value: Any) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat()
        if isinstance(value, Path):
            return value.as_posix()
        if isinstance(value, dict):
            return {
                str(key): DiagnosticsExportService._normalize_json_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [DiagnosticsExportService._normalize_json_value(item) for item in value]
        if isinstance(value, set):
            return [
                DiagnosticsExportService._normalize_json_value(item)
                for item in sorted(value, key=lambda item: str(item))
            ]
        return value

    @staticmethod
    def _serialize(payload: Dict[str, Any]) -> str:
        return json.dumps(
            DiagnosticsExportService._normalize_json_value(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"

    def serialize_payload(self, payload: Dict[str, Any]) -> str:
        return self._serialize(payload)

    @staticmethod
    def _slugify_export_type(export_type: str) -> str:
        normalized = re.sub(r"[^a-z0-9_-]+", "_", str(export_type or "").strip().lower())
        return normalized.strip("_") or "diagnostics"

    @staticmethod
    def _archive_filename(generated_at: str) -> str:
        parsed = DiagnosticsExportService._parse_iso(generated_at)
        if parsed is None:
            parsed = datetime.now(timezone.utc)
        return parsed.strftime("%Y%m%dT%H%M%S_%fZ.json")

    def build_download_filename(
        self,
        export_type: str,
        *,
        generated_at: str | None = None,
        payload: Dict[str, Any] | None = None,
    ) -> str:
        normalized_type = self._slugify_export_type(export_type).replace("_", "-")
        parsed = self._parse_iso(generated_at or ((payload or {}).get("generated_at")))
        if parsed is None:
            parsed = datetime.now(timezone.utc)
        stamp = parsed.strftime("%Y%m%dT%H%M%SZ")
        parts = ["opus-trader", normalized_type]
        baseline = dict((payload or {}).get("performance_baseline") or {})
        effective = dict(baseline.get("effective") or {})
        scope = str(effective.get("scope") or "").strip().lower()
        epoch_id = str(effective.get("epoch_id") or "").strip().lower()
        if scope and scope != "legacy":
            parts.append(self._slugify_export_type(scope))
        if epoch_id:
            parts.append(self._slugify_export_type(epoch_id))
        parts.append(stamp)
        return f"{'-'.join(filter(None, parts))}.json"

    @staticmethod
    def _display_path(path: Path) -> str:
        try:
            return path.relative_to(Path.cwd()).as_posix()
        except ValueError:
            return path.as_posix()

    @staticmethod
    def _write_text_atomic(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(temp_path, path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    def _prune_archives(self, export_dir: Path) -> int:
        archive_files = sorted(
            (
                path
                for path in export_dir.glob("*.json")
                if path.name != "latest.json"
            ),
            key=lambda path: path.name,
            reverse=True,
        )
        for stale_path in archive_files[self.archive_retention :]:
            stale_path.unlink(missing_ok=True)
        return min(len(archive_files), self.archive_retention)

    def write_export(
        self,
        export_type: str,
        payload: Dict[str, Any],
        *,
        generated_at: str | None = None,
    ) -> Dict[str, Any]:
        normalized_type = self._slugify_export_type(export_type)
        export_dir = self.base_dir / normalized_type
        export_dir.mkdir(parents=True, exist_ok=True)

        final_generated_at = str(
            generated_at
            or payload.get("generated_at")
            or datetime.now(timezone.utc).isoformat()
        )
        archive_path = export_dir / self._archive_filename(final_generated_at)
        latest_path = export_dir / "latest.json"
        text = self._serialize(payload)

        self._write_text_atomic(archive_path, text)
        self._write_text_atomic(latest_path, text)
        retained_archive_count = self._prune_archives(export_dir)

        return {
            "export_type": normalized_type,
            "generated_at": final_generated_at,
            "latest_path": self._display_path(latest_path),
            "archive_path": self._display_path(archive_path),
            "bytes_written": len(text.encode("utf-8")),
            "retained_archive_count": retained_archive_count,
        }
