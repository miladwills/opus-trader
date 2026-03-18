"""Trading Watchdog v1 — Standalone trading-truth observer.

Shadow-mode read-only service.
Does not place orders, modify bot state, or write into trader storage.
"""

import logging
import threading
import time

from flask import Flask

from trading_watchdog.config import HOST, PORT, DEBUG, POLL_INTERVAL_SEC, SHADOW_MODE
from trading_watchdog.analyzers.orchestrator import AnalysisOrchestrator
from trading_watchdog.routes.api import api_bp, set_orchestrator
from trading_watchdog.routes.dashboard import dashboard_bp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tw.app")


def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/tw",
    )

    # Register routes
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp)

    return app


def _analysis_loop(orchestrator, interval):
    """Background analysis loop. Runs every POLL_INTERVAL_SEC."""
    log.info("Analysis loop started (interval=%ds, shadow=%s)", interval, SHADOW_MODE)
    while True:
        try:
            t0 = time.time()
            snap = orchestrator.run()
            elapsed = time.time() - t0
            log.info(
                "Analysis cycle: health=%d (%s), verdicts=%d, bots=%d/%d, %.1fs",
                snap.health_score,
                snap.health_label,
                len(snap.verdicts),
                snap.running_bots,
                snap.total_bots,
                elapsed,
            )
        except Exception as e:
            log.error("Analysis cycle failed: %s", e, exc_info=True)

        time.sleep(interval)


def main():
    log.info("Trading Watchdog v1 starting (port=%d, shadow=%s)", PORT, SHADOW_MODE)

    orchestrator = AnalysisOrchestrator()
    set_orchestrator(orchestrator)

    # Run first analysis synchronously
    try:
        orchestrator.run()
        log.info("Initial analysis complete")
    except Exception as e:
        log.error("Initial analysis failed: %s", e)

    # Start background analysis thread
    t = threading.Thread(
        target=_analysis_loop,
        args=(orchestrator, POLL_INTERVAL_SEC),
        daemon=True,
    )
    t.start()

    app = create_app()
    app.run(host=HOST, port=PORT, debug=DEBUG, use_reloader=False)


if __name__ == "__main__":
    main()
