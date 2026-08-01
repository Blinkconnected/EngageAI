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
    include=[
        "blinkengage.core.tasks",
        "blinkengage.infrastructure.events.relay",
        "blinkengage.infrastructure.tasks.sla_sweep_task",
        "blinkengage.infrastructure.tasks.billing_period_close_task",
        "blinkengage.infrastructure.tasks.invoice_run_task",
        "blinkengage.infrastructure.tasks.ownership_sweep_task",
        "blinkengage.infrastructure.tasks.sla_breach_sweep_task",
        "blinkengage.infrastructure.tasks.billing_summary_sweep_task",
        "blinkengage.infrastructure.tasks.collections_sweep_task",
        "blinkengage.infrastructure.tasks.email_imap_poll_task",
        "blinkengage.infrastructure.tasks.notification_email_dispatch_task",
        "blinkengage.infrastructure.tasks.notification_push_dispatch_task",
        "blinkengage.infrastructure.tasks.channel_health_check_task",
    ],
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
    # Emits the task lifecycle events (sent/started/succeeded/failed/
    # runtime) the celery-exporter service (M27, see
    # docs/architecture/observability.md) listens for on the broker —
    # without these, Celery never publishes them and Prometheus would
    # scrape an always-empty /metrics from the exporter.
    worker_send_task_events=True,
    task_send_sent_event=True,
    beat_schedule={
        # Drains the transactional outbox to the RabbitMQ event exchange —
        # see docs/architecture/event-bus.md. Runs frequently since it's
        # cheap when the outbox is empty (one indexed, limited SELECT).
        "relay-event-outbox": {
            "task": "blinkengage.events.relay_outbox",
            "schedule": 5.0,
        },
        # See docs/architecture/queues-routing.md decision #4 — a single
        # periodic sweep rather than a per-conversation timer.
        "check-sla-breaches": {
            "task": "blinkengage.queues.check_sla_breaches",
            "schedule": 60.0,
        },
        # Closes billing periods whose month has ended — see
        # docs/architecture/billing.md. Hourly rather than a
        # once-a-month cron: a monthly job that misses its window (a
        # deploy, an outage, a clock change) leaves every company's month
        # unclosed until somebody notices, while an hourly sweep that
        # finds nothing costs one indexed query and self-heals. Each
        # close is idempotent, so running it often is free.
        "close-due-billing-periods": {
            "task": "blinkengage.billing.close_due_periods",
            "schedule": 3600.0,
        },
        # Bills every closed period that has no invoice yet — the monthly
        # invoice run, see docs/architecture/billing.md. Closing a period
        # and invoicing it are separate acts and only the first used to be
        # scheduled, so a month would close by itself on the 1st and then
        # sit there correctly closed and never billed until somebody
        # pressed Generate for each company by hand.
        #
        # Runs after close-due-billing-periods in this dict for
        # readability only — Celery beat gives no ordering guarantee, and
        # none is needed: a period not yet closed simply is not picked up,
        # and the next sweep an hour later bills it. Hourly and idempotent
        # for the same reasons as the close itself.
        "generate-pending-invoices": {
            "task": "blinkengage.billing.generate_pending_invoices",
            "schedule": 3600.0,
        },
        # Rebuilds the daily billing aggregates and finalizes days that
        # have passed — see docs/architecture/billing.md. The dashboard
        # refreshes a company's own aggregates when somebody reads them,
        # so this is not what keeps the live figures current; it is what
        # closes yesterday and records the projection snapshot for the
        # companies nobody happened to look at. Hourly for the same
        # reason as the period close, and idempotent for the same reason.
        "refresh-billing-daily-summaries": {
            "task": "blinkengage.billing.refresh_daily_summaries",
            "schedule": 3600.0,
        },
        # Reconciles pending gateway payments, then runs the dunning
        # sequence — see docs/architecture/billing.md. Hourly, for the
        # same reason as the period close: a daily job that misses its
        # window delays every notice by a day, and a delayed final
        # notice means somebody is suspended with less warning than the
        # policy promises. Every step is idempotent, so the notices a
        # customer receives depend on the dates, not on how often this
        # runs.
        "collections-sweep": {
            "task": "blinkengage.billing.collections_sweep",
            "schedule": 3600.0,
        },
        # Marks SLA clocks that have run out of time — see
        # docs/architecture/sla-engine.md. Running out is the one thing
        # that is not an event: nothing happens, which is exactly the
        # problem, so something has to notice.
        #
        # Every minute, like the SLA sweep beside it. A target measured in
        # minutes deserves a sweep measured in minutes, and a breach
        # reported fifty seconds late is still reported.
        "breach-overdue-sla-clocks": {
            "task": "blinkengage.sla.breach_overdue_clocks",
            "schedule": 60.0,
        },
        # Releases ownership whose sticky window has run out — see
        # docs/architecture/queue-lifecycle.md. A lapsed hold does not
        # release itself: the timeline is append-only, so something has to
        # notice and write the next row.
        #
        # Every five minutes. A window measured in hours does not need a
        # tighter sweep, and a lapsed hold costing a customer a few extra
        # minutes in a queue is a far smaller problem than a sweep
        # hammering the table.
        "release-expired-ownership": {
            "task": "blinkengage.conversations.release_expired_ownership",
            "schedule": 300.0,
        },
        # See docs/architecture/email-channel.md — polls every active
        # email ChannelConfig's IMAP mailbox for UNSEEN messages.
        "poll-email-imap": {
            "task": "blinkengage.channels.poll_email_imap",
            "schedule": 60.0,
        },
        # See docs/architecture/notifications.md — dispatches emails for
        # Notification rows with no email_dispatched_at yet.
        "dispatch-notification-emails": {
            "task": "blinkengage.notifications.dispatch_pending_emails",
            "schedule": 30.0,
        },
        # See docs/architecture/notifications.md — pushes Notification rows
        # with no push_dispatched_at yet. Faster than the email sweep
        # above, and for a reason rather than by preference: an email that
        # lands half a minute late is still an email, while a push is an
        # interruption whose entire value is being current. The query is
        # the same shape and cost as the outbox relay's (one indexed,
        # limited SELECT against a partial index), which runs at 5s for
        # exactly this reason, and a run with nothing pending — the common
        # case — costs that one query and stops.
        "dispatch-notification-pushes": {
            "task": "blinkengage.notifications.dispatch_pending_pushes",
            "schedule": 10.0,
        },
        # See docs/architecture/channel-integration-spec.md (Phase 1:
        # Channel Experience) — a slower cadence than the operational
        # sweeps above since this calls out to real third-party APIs
        # (Meta Graph, Telegram, SMTP/IMAP) for every active channel
        # across every company on each tick.
        "check-channel-health": {
            "task": "blinkengage.channels.check_channel_health",
            "schedule": 300.0,
        },
    },
)
