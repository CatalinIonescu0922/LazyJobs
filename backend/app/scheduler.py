import asyncio
from datetime import timedelta

from .config import settings
from .logging import logger
from .routers.jobs import refresh_due_sources

CHECK_SECONDS = 30 * 60
STARTUP_DELAY_SECONDS = 60


async def run() -> None:
    logger.info("Scheduler started: active sources refresh every %s hours", settings.refresh_interval_hours)
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            await asyncio.to_thread(refresh_due_sources, timedelta(hours=settings.refresh_interval_hours))
        except Exception:
            logger.exception("Scheduled refresh failed")
        await asyncio.sleep(CHECK_SECONDS)
