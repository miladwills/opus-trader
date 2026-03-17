import copy
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.lock_service import file_lock

logger = logging.getLogger(__name__)


class AutoPilotCandidateCacheService:
    """Small in-memory candidate cache with optional JSON persistence."""

    def __init__(
        self,
        file_path: Optional[str] = None,
        persist_enabled: bool = False,
    ) -> None:
        self.persist_enabled = bool(persist_enabled and file_path)
        self.file_path = Path(file_path) if file_path else None
        self.lock_path = (
            Path(f"{self.file_path}.lock") if self.persist_enabled and self.file_path else None
        )
        self._snapshot: Dict[str, Any] = {
            "prepared_at": None,
            "prepared_ts": 0.0,
            "source": None,
            "candidate_count": 0,
            "scan_universe": 0,
            "candidates": [],
        }

        if self.persist_enabled and self.file_path:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            if self.lock_path and not self.lock_path.exists():
                self.lock_path.touch()
            self._load_snapshot()

    def _load_snapshot(self) -> None:
        if not self.persist_enabled or not self.file_path or not self.file_path.exists():
            return
        try:
            with file_lock(self.lock_path, exclusive=False):
                with open(self.file_path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
            if isinstance(payload, dict):
                self._snapshot = {
                    "prepared_at": payload.get("prepared_at"),
                    "prepared_ts": float(payload.get("prepared_ts") or 0.0),
                    "source": payload.get("source"),
                    "candidate_count": int(payload.get("candidate_count") or 0),
                    "scan_universe": int(payload.get("scan_universe") or 0),
                    "candidates": list(payload.get("candidates") or []),
                }
        except Exception as exc:
            logger.warning("[Auto-Pilot] Candidate cache load failed: %s", exc)

    def _write_snapshot(self) -> None:
        if not self.persist_enabled or not self.file_path:
            return
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=f"{self.file_path.name}.",
            suffix=".tmp",
            dir=str(self.file_path.parent),
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(self._snapshot, fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            with file_lock(self.lock_path, exclusive=True):
                os.replace(tmp_path, self.file_path)
        except Exception as exc:
            logger.warning("[Auto-Pilot] Candidate cache persist failed: %s", exc)
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def get_snapshot(self) -> Dict[str, Any]:
        return copy.deepcopy(self._snapshot)

    def get_fresh(
        self,
        max_age_seconds: float,
        *,
        now_ts: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        safe_now = float(now_ts if now_ts is not None else time.time())
        age_limit = max(0.0, float(max_age_seconds or 0.0))
        prepared_ts = float(self._snapshot.get("prepared_ts") or 0.0)
        if prepared_ts <= 0:
            return None
        age = safe_now - prepared_ts
        if age < 0 or age > age_limit:
            return None
        snapshot = self.get_snapshot()
        snapshot["age_seconds"] = age
        return snapshot

    def store(
        self,
        *,
        candidates: List[Dict[str, Any]],
        source: str,
        scan_universe: int,
        now_ts: Optional[float] = None,
        prepared_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        safe_now = float(now_ts if now_ts is not None else time.time())
        snapshot = {
            "prepared_at": prepared_at,
            "prepared_ts": safe_now,
            "source": str(source or "").strip() or "unknown",
            "candidate_count": len(candidates or []),
            "scan_universe": max(0, int(scan_universe or 0)),
            "candidates": copy.deepcopy(list(candidates or [])),
        }
        self._snapshot = snapshot
        self._write_snapshot()
        return self.get_snapshot()
