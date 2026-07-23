"""Baseline Celery tasks.

Domain-specific tasks (notification dispatch, workflow execution, AI
processing, etc.) are added alongside their owning feature in later
milestones and imported via ``celery_app``'s ``include`` list.
"""

from blinkengage.core.celery_app import celery_app
from blinkengage.core.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(name="blinkengage.ping")  # type: ignore[misc]
def ping() -> str:
    """Trivial liveness task used to verify the worker/broker/backend wiring."""
    logger.info("celery_ping_task_executed")
    return "pong"
