"""Opus AI Ops Service — main FastAPI application."""

from __future__ import annotations
import asyncio
import datetime
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config, db
from .collector import StaggeredCollector
from .triage import TriageEngine
from .repo import Repository
from .agents import AgentSupervisor
from .models import AuditEntry
from .routes_api import router as api_router, health_router
from .routes_pages import router as pages_router
from .routes_agents import router as agents_router
from .routes_proposals import router as proposals_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("aiops")

_collector: StaggeredCollector | None = None
_triage_engine: TriageEngine | None = None
_supervisor: AgentSupervisor | None = None
_purge_task: asyncio.Task | None = None

# Minimum interval between collection ticks (fastest lane cadence)
_COLLECT_TICK_SEC = 5.0


async def _purge_loop(repo: Repository):
    """Periodic retention purge."""
    while True:
        await asyncio.sleep(3600)
        try:
            await repo.purge_old_data()
            logger.info("Retention purge completed")
        except Exception as exc:
            logger.error("Purge error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _collector, _triage_engine, _supervisor, _purge_task

    # Init DB
    conn = await db.init_db()
    repo = Repository(conn)
    logger.info("Database initialized at %s", config.DB_PATH)

    # Init collector
    _collector = StaggeredCollector()
    await _collector.start()

    # Init triage engine
    _triage_engine = TriageEngine()

    # Init agent supervisor
    context = {
        "collector": _collector,
        "triage_engine": _triage_engine,
        "repo": repo,
    }
    _supervisor = AgentSupervisor(repo, context)
    await _supervisor.init_registry()
    await _supervisor.start_supervisor()

    # Start purge loop
    _purge_task = asyncio.create_task(_purge_loop(repo), name="purge_loop")

    # Audit service start
    seq = await repo.get_next_audit_seq()
    date_str = datetime.date.today().strftime("%Y%m%d")
    await repo.create_audit_entry(AuditEntry(
        entry_id=f"AUD-{date_str}-{seq:04d}",
        timestamp=time.time(),
        actor="system",
        action="service_started",
        target_type="service",
        target_id="aiops",
        detail={"port": config.AIOPS_PORT, "version": "v2"},
    ))

    logger.info("AI Ops V2 service started on port %d", config.AIOPS_PORT)
    logger.info(
        "Collection cadence: fast=%ds, medium=%ds, slow=%ds",
        config.FAST_LANE_INTERVAL, config.MEDIUM_LANE_INTERVAL, config.SLOW_LANE_INTERVAL,
    )

    yield

    # Shutdown
    if _supervisor:
        await _supervisor.stop_supervisor()
    if _purge_task:
        _purge_task.cancel()
    if _collector:
        await _collector.stop()
    await db.close_db()
    logger.info("AI Ops service shut down")


# --- App creation ---

BASE_DIR = Path(__file__).parent

app = FastAPI(
    title="Opus AI Ops",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.state.templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app.include_router(health_router)
app.include_router(api_router)
app.include_router(agents_router)
app.include_router(proposals_router)
app.include_router(pages_router)
