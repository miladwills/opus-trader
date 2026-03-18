"""API routes for Trading Watchdog."""

from flask import Blueprint, jsonify

api_bp = Blueprint("api", __name__, url_prefix="/api")

# Orchestrator reference set by app.py
_orchestrator = None


def set_orchestrator(orch):
    global _orchestrator
    _orchestrator = orch


@api_bp.route("/snapshot")
def snapshot():
    """Full watchdog snapshot as JSON."""
    if _orchestrator is None or _orchestrator.last_snapshot is None:
        return jsonify({"status": "initializing", "message": "First analysis cycle pending"}), 503
    return jsonify(_orchestrator.last_snapshot.to_dict())


@api_bp.route("/health")
def health():
    """Quick health check."""
    snap = _orchestrator.last_snapshot if _orchestrator else None
    if snap is None:
        return jsonify({"status": "initializing"}), 503
    return jsonify({
        "status": "ok",
        "health_score": snap.health_score,
        "health_label": snap.health_label,
        "collected_at": snap.collected_at,
        "verdict_count": len(snap.verdicts),
        "bridge_fresh": snap.bridge_fresh,
    })


@api_bp.route("/verdicts")
def verdicts():
    """All current verdicts."""
    snap = _orchestrator.last_snapshot if _orchestrator else None
    if snap is None:
        return jsonify([])
    return jsonify([v.to_dict() for v in snap.verdicts])
