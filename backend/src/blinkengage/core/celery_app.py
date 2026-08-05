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
        "blinkengage.infrastructure.tasks.ai_pickup_sweep_task",
        "blinkengage.infrastructure.tasks.billing_summary_sweep_task",
        "blinkengage.infrastructure.tasks.collections_sweep_task",
        "blinkengage.infrastructure.tasks.email_imap_poll_task",
        "blinkengage.infrastructure.tasks.notification_email_dispatch_task",
        "blinkengage.infrastructure.tasks.notification_push_dispatch_task",
        "blinkengage.infrastructure.tasks.channel_health_check_task",
        "blinkengage.infrastructure.tasks.knowledge_index_sweep_task",
        "blinkengage.infrastructure.tasks.memory_decay_sweep_task",
        "blinkengage.infrastructure.tasks.learning_settle_sweep_task",
        "blinkengage.infrastructure.tasks.learning_cluster_sweep_task",
        "blinkengage.infrastructure.tasks.learning_analysis_sweep_task",
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
        # Hands AI the conversations nobody picked up — see
        # docs/architecture/ai-engine.md. AI is a queue worker, not a first
        # responder: it waits out the service's pickup delay so an agent has
        # the first chance, and this is what happens when nobody takes it.
        #
        # Every ten seconds, matching the push dispatcher above rather than
        # the minute-long sweeps. The delay defaults to thirty seconds, and
        # a sweep coarser than the thing it is waiting for would turn that
        # into anything up to ninety — a different promise than the one an
        # administrator typed into the box. The query is the same shape and
        # cost as the outbox relay's: one indexed, limited SELECT against a
        # partial index, and a run with nothing due costs exactly that.
        "ai-pickup-waiting-conversations": {
            "task": "blinkengage.ai.pickup_waiting_conversations",
            "schedule": 10.0,
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
        # Keeps the semantic index caught up with the knowledge base — see
        # docs/architecture/company-intelligence-engine.md. Every minute
        # rather than every few seconds, because unlike the operational
        # sweeps this one calls a metered external embedding API, and a
        # knowledge article is not edited on a timescale where thirty
        # seconds of staleness is felt by anybody. A run with an empty
        # backlog — the overwhelmingly common case — costs one indexed
        # query against a partial index and stops.
        "reindex-pending-knowledge": {
            "task": "blinkengage.knowledge.reindex_pending",
            "schedule": 60.0,
        },
        # Ages memory — see docs/architecture/memory-platform.md. Hourly,
        # which is far more often than any fact's confidence meaningfully
        # moves (half-lives here are measured in months) but keeps the
        # backlog per run small and bounded. Decay is computed rather than
        # applied, so a missed run costs nothing but staleness in the
        # stored number; the next run is correct without needing to catch
        # up on the ones it missed.
        "age-memory": {
            "task": "blinkengage.memory.age_memory",
            "schedule": 3600.0,
        },
        # Promotes observations whose settle window has closed — see
        # docs/architecture/learning-platform.md. Every fifteen minutes:
        # the window is measured in days, so this only needs to be fine
        # enough that "settled" is not noticeably late, and a run with
        # nothing due costs one indexed query against a partial index.
        # Groups settled observations into clusters — see
        # docs/architecture/learning-platform-phase-2.md. Hourly, per the
        # charter's lag budget, and affordable at that cadence because the
        # pass is incremental: an observation already in a cluster is
        # never reconsidered.
        "cluster-learning-observations": {
            "task": "blinkengage.learning.cluster_observations",
            "schedule": float(settings.learning_cluster_interval_seconds),
        },
        # Trend and anomaly detection. Daily, and the cadence is a
        # statistical decision rather than a cost one: running the same
        # weekly-window tests hourly would give them twenty-four chances a
        # day to cross a threshold, which is multiple testing through the
        # back door.
        "analyse-learning-patterns": {
            "task": "blinkengage.learning.analyse_patterns",
            "schedule": float(settings.learning_analysis_interval_seconds),
        },
        "settle-learning-observations": {
            "task": "blinkengage.learning.settle_observations",
            # From the setting rather than a literal, because the sweep
            # truncates its run window to the same number. Two literals
            # that must agree eventually do not, and when they disagree
            # here the symptom is a health dashboard reporting no
            # failures because most runs were never recorded.
            "schedule": float(settings.learning_settle_interval_seconds),
        },
    },
)
