"""Opus Platform Watchdog - main FastAPI application."""

from __future__ import annotations
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config, db
from .probes.http_probes import BootstrapProbe, BridgeDiagnosticsProbe, ServicesStatusProbe
from .probes.file_probes import BridgeJsonProbe, RunnerLockProbe, LogFreshnessProbe
from .probes.process_probes import SystemdProbe, SystemResourcesProbe
from .probes.log_probes import LogScanProbe
from .classifiers.incident_classifier import IncidentClassifier
from .scoring.health_scorer import HealthScorer
from .scheduler.probe_scheduler import ProbeScheduler
from .storage.repo import Repository
from .ui.pages import router as pages_router
from .ui.api import router as api_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("watchdog")

_scheduler: ProbeScheduler | None = None
_health_task: asyncio.Task | None = None
_resolve_task: asyncio.Task | None = None
_purge_task: asyncio.Task | None = None


async def _health_loop(scorer: HealthScorer):
    while True:
        try:
            await scorer.compute()
        except Exception as e:
            logger.error("Health scoring error: %s", e)
        await asyncio.sleep(30)


async def _resolve_loop(classifier: IncidentClassifier):
    while True:
        try:
            await classifier.auto_resolve_stale()
        except Exception as e:
            logger.error("Auto-resolve error: %s", e)
        await asyncio.sleep(60)


async def _purge_loop(repo: Repository):
    while True:
        await asyncio.sleep(3600)
        try:
            await repo.purge_old_data()
            logger.info("Retention purge completed")
        except Exception as e:
            logger.error("Purge error: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler, _health_task, _resolve_task, _purge_task

    # Init DB
    conn = await db.init_db()
    repo = Repository(conn)
    logger.info("Database initialized at %s", config.DB_PATH)

    # Build classifier
    classifier = IncidentClassifier(repo)

    # Build probes
    log_runner = LogScanProbe(config.OPUS_RUNNER_LOG, "log_runner", "runner")
    log_runner.set_classifier(classifier)
    log_app = LogScanProbe(config.OPUS_APP_LOG, "log_app", "app")
    log_app.set_classifier(classifier)

    probes = [
        BootstrapProbe(),
        BridgeDiagnosticsProbe(),
        ServicesStatusProbe(),
        BridgeJsonProbe(),
        RunnerLockProbe(),
        LogFreshnessProbe(),
        SystemdProbe("opus_trader", "proc_trader"),
        SystemdProbe("opus_runner", "proc_runner"),
        SystemResourcesProbe(),
        log_runner,
        log_app,
    ]

    # Start scheduler
    _scheduler = ProbeScheduler(repo, probes)
    await _scheduler.start()

    # Start background tasks
    scorer = HealthScorer(repo)
    _health_task = asyncio.create_task(_health_loop(scorer), name="health_loop")
    _resolve_task = asyncio.create_task(_resolve_loop(classifier), name="resolve_loop")
    _purge_task = asyncio.create_task(_purge_loop(repo), name="purge_loop")

    logger.info("Watchdog started: %d probes, port %d", len(probes), config.WATCHDOG_PORT)

    yield

    # Shutdown
    if _health_task:
        _health_task.cancel()
    if _resolve_task:
        _resolve_task.cancel()
    if _purge_task:
        _purge_task.cancel()
    if _scheduler:
        await _scheduler.stop()
    await db.close_db()
    logger.info("Watchdog shut down")


# --- App creation ---

BASE_DIR = Path(__file__).parent

app = FastAPI(
    title="Opus Platform Watchdog",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.state.templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app.include_router(pages_router)
app.include_router(api_router)
