"""Background scheduler for periodic tasks."""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import async_session

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def expire_reservations_job():
    """Background job: expire pending reservations past timeout."""
    from app.services.reservation import expire_pending_reservations

    async with async_session() as db:
        try:
            count = await expire_pending_reservations(db)
            if count > 0:
                logger.info(f"Scheduler: expired {count} reservations")
        except Exception as e:
            logger.error(f"Scheduler error in expire_reservations: {e}")


def start_scheduler():
    """Start the background scheduler with all periodic jobs."""
    # Check for expired reservations every minute
    scheduler.add_job(
        expire_reservations_job,
        "interval",
        minutes=1,
        id="expire_reservations",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Background scheduler started")


def stop_scheduler():
    """Gracefully stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Background scheduler stopped")
