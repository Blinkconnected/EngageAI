"""Celery application factory.

Worker entrypoint: ``celery -A blinkengage.core.celery_app.celery_app worker``
Beat entrypoint: ``celery -A blinkengage.core.celery_app.celery_app beat``

Task modules are imported here (via ``include``) so the worker discovers
them without each domain module needing to know about Celery at import
time.
"""

from celery import Celery

from blinkengage.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "blinkengage",
    broker=settings.rabbitmq_url,
    backend=settings.celery_result_backend,
    include=["blinkengage.core.tasks", "blinkengage.infrastructure.events.relay"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        # Drains the transactional outbox to the RabbitMQ event exchange —
        # see docs/architecture/event-bus.md. Runs frequently since it's
        # cheap when the outbox is empty (one indexed, limited SELECT).
        "relay-event-outbox": {
            "task": "blinkengage.events.relay_outbox",
            "schedule": 5.0,
        },
    },
)
