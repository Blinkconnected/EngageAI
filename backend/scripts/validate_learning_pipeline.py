"""Phase 1.5 — production validation of the observation pipeline.

Answers the seven questions that gate phase 2, against a real PostgreSQL:
volume, extraction latency, feature quality, replay behaviour, health,
resource usage and cost.

**Two kinds of number, and the difference matters.**

*Engineering* numbers — latency, throughput, bytes per observation, write
amplification — are properties of the code and the schema. A synthetic
corpus measures them exactly, and the answer does not change when real
traffic arrives.

*Empirical* numbers — the feedback ratio, the real language mix, how many
conversations are too short to learn from, how often an outcome actually
changes after assembly — are properties of a **population**. No corpus
can produce them. This script reads them from whatever the installation
has actually observed and reports the sample size next to them, so a
number computed from five conversations cannot be mistaken for a finding.

Feature *quality* sits between the two: accuracy needs labelled data, and
production text does not come labelled. It is measured here against a
hand-labelled corpus that mirrors this platform's traffic (Arabic,
English, code-switched, with known entities), and reported as what it is —
a benchmark, not a field measurement.

Run against the compose stack::

    DATABASE_URL=postgresql+asyncpg://blinkengage:...@postgres:5432/blinkengage \\
        python scripts/validate_learning_pipeline.py --corpus 5000

``--corpus 0`` skips the load phase and reports only what the installation
has really observed. Re-run it after production traffic accumulates and
diff the JSON: that comparison is the actual phase-2 gate.

Everything it writes is confined to one throwaway company, deleted on the
way out — a validation run must not leave observations that a later
measurement would count as traffic.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import resource
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from blinkengage.application.services.learning_observation_service import (
    LearningObservationService,
    TurnInput,
)
from blinkengage.domain.conversation_outcome import OutcomeInputs, ResolvedBy
from blinkengage.domain.learning_features import extract
from blinkengage.domain.learning_observation import (
    PIPELINE_VERSION,
    ObservationSource,
    Participants,
    SourceKind,
)
from blinkengage.infrastructure.repositories.learning_repository import (
    LearningObservationRepository,
)

LEARNING_TABLES = (
    "learning_observations",
    "learning_observation_features",
    "learning_observation_refs",
    "learning_runs",
    "learning_clusters",
    "learning_cluster_members",
    "learning_trends",
    "learning_anomalies",
)

#: Written to, then deleted. A fixed id so an interrupted run can be
#: cleaned up by hand without hunting for it.
VALIDATION_COMPANY = uuid.UUID("00000000-0000-4000-8000-0000000f1500")


# ---------------------------------------------------------------------------
# The labelled corpus
# ---------------------------------------------------------------------------
#
# Hand-labelled, and deliberately not generated from the extractor's own
# rules — a corpus built from the patterns being tested measures nothing
# but itself. Each entry carries the language a human would assign and the
# entities a human would pick out.


@dataclass(frozen=True)
class LabelledTurn:
    text: str
    language: str | None
    entities: tuple[str, ...]
    #: What the message is *about*, in the words a reader would use. Used
    #: for topic coverage, not for exact-match scoring: topic tokens are
    #: raw material for clustering, not an intent classification, and
    #: grading them against a fixed list would be grading the wrong thing.
    about: tuple[str, ...]


LABELLED: tuple[LabelledTurn, ...] = (
    LabelledTurn(
        "I ordered a phone case on Tuesday and the tracking has not moved since. "
        "Order ORD-88421. Can you check where the shipment is?",
        "en",
        ("ref:ORD-88421",),
        ("tracking", "shipment", "order"),
    ),
    LabelledTurn(
        "The refund of 45 JOD you promised last week still has not reached my account. "
        "I have called three times about this refund.",
        "en",
        ("money:45 JOD",),
        ("refund",),
    ),
    LabelledTurn(
        "مرحبا، لم يصلني الطلب حتى الآن ومر أسبوع كامل على الشحن. أرجو المتابعة بأسرع وقت.",
        "ar",
        (),
        ("الطلب", "الشحن"),
    ),
    LabelledTurn(
        "السلام عليكم، أريد استرجاع المبلغ للفاتورة رقم INV-30271 لأن المنتج وصل تالفا.",
        "ar",
        ("ref:INV-30271",),
        ("استرجاع", "المبلغ"),
    ),
    LabelledTurn(
        "مرحبا، I need to change the delivery address على الطلب ORD-11902 قبل الشحن.",
        "mixed",
        ("ref:ORD-11902",),
        ("delivery", "address"),
    ),
    LabelledTurn(
        "Hello, my invoice shows 120 USD but the plan page said 99 USD. "
        "Please send a corrected invoice to billing@example.com.",
        "en",
        ("money:120 USD", "money:99 USD", "email:billing@example.com"),
        ("invoice", "billing", "plan"),
    ),
    LabelledTurn(
        "الاشتراك تجدد تلقائيا بدون إشعار وأريد إلغاءه واسترجاع الرسوم.",
        "ar",
        (),
        ("الاشتراك", "الغاء"),
    ),
    LabelledTurn(
        "The app keeps logging me out every few minutes on Android since the update. "
        "It happens on the orders screen specifically.",
        "en",
        (),
        ("android", "update", "orders"),
    ),
    LabelledTurn(
        "هل يمكنني استبدال المنتج بمقاس أكبر؟ رقم الطلب ORD-77310 والمبلغ 25 JOD.",
        "ar",
        ("ref:ORD-77310", "money:25 JOD"),
        ("استبدال", "المنتج"),
    ),
    LabelledTurn(
        "Please escalate this to a supervisor, I have been waiting since 09:00 "
        "and nobody has answered my question about the warranty.",
        "en",
        (),
        ("escalate", "supervisor", "warranty"),
    ),
    LabelledTurn(
        "شكرا",
        "ar",
        (),
        (),
    ),
    LabelledTurn(
        "ok",
        "en",
        (),
        (),
    ),
)

AGENT_REPLIES: tuple[str, ...] = (
    "Thank you for reaching out. I can see the order and I am checking with the courier now.",
    "أهلا بك، تم تحويل الطلب إلى القسم المختص وسنوافيك بالتحديث خلال 24 ساعة.",
    "I have issued the refund; it should appear on your statement within three working days.",
    "تم تحديث العنوان بنجاح، وسيتم الشحن غدا.",
    "I understand the frustration. Escalating this to my supervisor now.",
)


# ---------------------------------------------------------------------------
# Result plumbing
# ---------------------------------------------------------------------------


@dataclass
class Report:
    sections: dict[str, Any] = field(default_factory=dict)

    def add(self, name: str, value: Any) -> None:
        self.sections[name] = value

    def dump(self) -> str:
        return json.dumps(self.sections, indent=2, default=str, ensure_ascii=False)


def percentiles(samples: list[float]) -> dict[str, float]:
    """p50/p95/p99 in milliseconds, plus the tail nobody quotes.

    ``max`` is included because a p99 measured over a few thousand samples
    hides exactly the pause — a GC, a lock, a cold index — that turns into
    a consumer-lag alarm at three in the morning.
    """
    if not samples:
        return {}
    ordered = sorted(samples)

    def at(fraction: float) -> float:
        index = min(len(ordered) - 1, int(len(ordered) * fraction))
        return round(ordered[index] * 1000, 4)

    return {
        "p50_ms": at(0.50),
        "p95_ms": at(0.95),
        "p99_ms": at(0.99),
        "max_ms": round(ordered[-1] * 1000, 4),
        "mean_ms": round(statistics.fmean(ordered) * 1000, 4),
        "samples": len(ordered),
    }


# ---------------------------------------------------------------------------
# 1. Volume — read from what the installation has actually observed
# ---------------------------------------------------------------------------


async def measure_volume(session: AsyncSession) -> dict[str, Any]:
    """Observations per hour, per day, per company — from real rows only.

    Every figure here is qualified by its sample size. On an installation
    that has just switched Learning on, the honest answer is a small
    integer and a note saying so, not a rate extrapolated from it.
    """
    totals = (
        await session.execute(
            text(
                """
                select
                    count(*)                                    as observations,
                    count(distinct company_id)                  as companies,
                    min(created_at)                             as first_seen,
                    max(created_at)                             as last_seen
                from learning_observations
                where company_id <> :validation
                """
            ),
            {"validation": VALIDATION_COMPANY},
        )
    ).one()

    observations, companies, first_seen, last_seen = totals
    window_hours = 0.0
    if first_seen is not None and last_seen is not None:
        window_hours = max((last_seen - first_seen).total_seconds() / 3600.0, 0.0)

    per_company = [
        {"company_id": str(row[0]), "observations": int(row[1])}
        for row in (
            await session.execute(
                text(
                    """
                    select company_id, count(*)
                    from learning_observations
                    where company_id <> :validation
                    group by company_id
                    order by 2 desc
                    limit 20
                    """
                ),
                {"validation": VALIDATION_COMPANY},
            )
        ).all()
    ]

    conversations = (
        await session.execute(
            text("select count(*) from conversations where status in ('RESOLVED','CLOSED')")
        )
    ).scalar_one()

    return {
        "observations_total": int(observations or 0),
        "companies_with_observations": int(companies or 0),
        "first_observed_at": first_seen,
        "last_observed_at": last_seen,
        "observation_window_hours": round(window_hours, 3),
        # Deliberately null rather than a division by a near-zero window.
        # A rate computed across four minutes of manual testing is not a
        # rate, and printing one invites somebody to plan capacity on it.
        "observations_per_hour": (
            round(observations / window_hours, 3) if window_hours >= 1 else None
        ),
        "observations_per_day": (
            round(observations / (window_hours / 24), 3) if window_hours >= 24 else None
        ),
        "observations_per_company": per_company,
        "finished_conversations_in_platform": int(conversations or 0),
        "coverage_of_finished_conversations": (
            round(observations / conversations, 4) if conversations else None
        ),
    }


# ---------------------------------------------------------------------------
# 2 + 3. Extraction latency and feature quality
# ---------------------------------------------------------------------------


def measure_extraction(corpus: int, seed: int) -> dict[str, Any]:
    """Time and grade tier-0/1 extraction over the labelled corpus.

    Latency is measured on the pure function, with no database and no
    broker in the way, because that is the number that scales: assembly
    cost is dominated by I/O, and mixing them produces a figure that says
    nothing about either.
    """
    rng = random.Random(seed)
    durations: list[float] = []

    language_correct = 0
    language_total = 0
    entities_expected = 0
    entities_found = 0
    entities_extracted = 0
    with_topics = 0
    empty = 0
    substantive = 0

    for index in range(corpus):
        turn = LABELLED[index % len(LABELLED)]
        # Real conversations are several turns; the extractor sees them
        # joined, which is what production does.
        others = rng.sample(LABELLED, k=min(2, len(LABELLED)))
        human_text = "\n".join([turn.text, *(other.text for other in others)])

        # The multi-turn timing: what the consumer actually pays, since a
        # real conversation is joined before extraction.
        started = time.perf_counter()
        extract(
            human_text=human_text,
            inbound_turns=1 + len(others),
            outbound_turns=rng.randint(1, 4),
        )
        durations.append(time.perf_counter() - started)

        # --- language: graded on the single-turn label only ------------
        started = time.perf_counter()
        single = extract(human_text=turn.text, inbound_turns=1, outbound_turns=1)
        durations.append(time.perf_counter() - started)
        if turn.language is not None:
            language_total += 1
            language_correct += int(single.language == turn.language)

        # --- entities: precision and recall against the label ----------
        expected = set(turn.entities)
        got = set(single.entities)
        entities_expected += len(expected)
        entities_found += len(expected & got)
        entities_extracted += len(got)

        # --- topics: coverage, on turns that have something to say -----
        if turn.about:
            substantive += 1
            with_topics += int(bool(single.topics))
        if not single.topics and not single.entities:
            empty += 1

    return {
        "latency": percentiles(durations),
        "quality": {
            "language_accuracy": (
                round(language_correct / language_total, 4) if language_total else None
            ),
            "language_samples": language_total,
            "topic_coverage": (round(with_topics / substantive, 4) if substantive else None),
            "topic_coverage_note": (
                "share of substantive turns yielding at least one topic token; "
                "turns labelled as having nothing to say are excluded, since "
                "extracting a topic from 'thanks' would be the defect"
            ),
            "entity_precision": (
                round(entities_found / entities_extracted, 4) if entities_extracted else None
            ),
            "entity_recall": (
                round(entities_found / entities_expected, 4) if entities_expected else None
            ),
            "empty_extraction_rate": round(empty / max(corpus, 1), 4),
            "empty_note": (
                "no topics and no entities. Non-zero by design — the corpus "
                "includes 'thanks' and 'ok', which are exactly the turns the "
                "too-short exclusion is for"
            ),
        },
    }


# ---------------------------------------------------------------------------
# 4 + 6. Assembly under load: throughput, writes, storage, replay
# ---------------------------------------------------------------------------


def _turns_for_source(source_id: uuid.UUID, *, seed: int) -> tuple[TurnInput, ...]:
    """The same conversation, every time this source is assembled.

    Derived from the source id rather than drawn from a shared generator,
    and that is the whole point of the replay measurement. A replay that
    fed *different* content to the same source would be measuring the
    unique constraint and nothing else; feeding identical content asks the
    question that matters — does re-observing an unchanged conversation
    write anything at all?
    """
    rng = random.Random(f"{seed}:{source_id}")
    count = rng.randint(2, 12)
    return _turns(rng, count, source_id=source_id)


def _turns(
    rng: random.Random, count: int, *, source_id: uuid.UUID | None = None
) -> tuple[TurnInput, ...]:
    turns: list[TurnInput] = []
    for ordinal in range(count):
        inbound = ordinal % 2 == 0
        # Stable per (source, ordinal): a message keeps its identity across
        # a replay, exactly as a real conversation's messages do.
        ref_id = uuid.uuid5(source_id, str(ordinal)) if source_id is not None else uuid.uuid4()
        if inbound:
            turns.append(
                TurnInput(
                    ref_id=ref_id,
                    ordinal=ordinal,
                    inbound=True,
                    text=rng.choice(LABELLED).text,
                )
            )
        else:
            # One reply in five is Autopilot's, which is roughly what an
            # installation with Autopilot switched on looks like — and it
            # is what makes the feedback ratio non-trivial to compute.
            ai = rng.random() < 0.2
            turns.append(
                TurnInput(
                    ref_id=ref_id,
                    ordinal=ordinal,
                    inbound=False,
                    text=rng.choice(AGENT_REPLIES),
                    is_ai_generated=ai,
                )
            )
    return tuple(turns)


async def _table_bytes(session: AsyncSession) -> dict[str, int]:
    rows = (
        await session.execute(
            text(
                "select relname, pg_total_relation_size(relid) "
                "from pg_catalog.pg_statio_user_tables where relname = any(:names)"
            ),
            {"names": list(LEARNING_TABLES)},
        )
    ).all()
    return {str(name): int(size) for name, size in rows}


async def _write_counts(session: AsyncSession) -> dict[str, int]:
    rows = (
        await session.execute(
            text(
                "select relname, n_tup_ins + n_tup_upd "
                "from pg_stat_user_tables where relname = any(:names)"
            ),
            {"names": list(LEARNING_TABLES)},
        )
    ).all()
    return {str(name): int(count or 0) for name, count in rows}


async def run_load(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    corpus: int,
    seed: int,
) -> dict[str, Any]:
    """Assemble ``corpus`` observations for real, then replay them.

    Against the real service and the real database, because the questions
    this section answers — write amplification, bytes on disk, whether a
    replay writes anything — are questions about what the storage layer
    does, and a fake would answer them wrongly and confidently.
    """
    now = datetime.now(UTC)

    # Compact first, or the measurement lies. PostgreSQL reuses pages
    # freed by a previous run's cleanup, so a size *delta* taken over
    # already-allocated extents undercounts — measured at 675 bytes per
    # observation against a warm table and 2037 against a cold one, a
    # three-fold error straight into the cost model. VACUUM FULL takes an
    # exclusive lock, which is acceptable on Learning's own tables in a
    # validation run and nowhere else.
    async with session_factory() as session:
        await session.execute(text("commit"))
        for table in LEARNING_TABLES:
            await session.execute(text(f"vacuum (full, analyze) {table}"))  # noqa: S608

    async with session_factory() as session:
        before_bytes = await _table_bytes(session)
        before_writes = await _write_counts(session)

    sources = [uuid.uuid4() for _ in range(corpus)]
    assemble_durations: list[float] = []
    created = 0

    rusage_before = resource.getrusage(resource.RUSAGE_SELF)
    wall_started = time.perf_counter()

    async def assemble_all(*, replay: bool) -> tuple[int, int, list[float]]:
        made = 0
        reused = 0
        durations: list[float] = []
        for index, source_id in enumerate(sources):
            async with session_factory() as session:
                service = LearningObservationService(
                    observations=LearningObservationRepository(session)
                )
                turns = _turns_for_source(source_id, seed=seed)
                started = time.perf_counter()
                result = await service.assemble(
                    company_id=VALIDATION_COMPANY,
                    source=ObservationSource(
                        kind=SourceKind.CONVERSATION,
                        source_id=source_id,
                        occurred_at=now - timedelta(minutes=index),
                        channel="whatsapp",
                    ),
                    participants=Participants(customer_id=uuid.uuid4()),
                    turns=turns,
                    outcome_inputs=OutcomeInputs(
                        status="resolved",
                        # Ended well outside the settle window, so these
                        # observations are READY. Phase 2 refuses to
                        # cluster anything still settling (charter I-7),
                        # so a corpus that ends an hour ago measures the
                        # eligibility gate and nothing else.
                        started_at=now - timedelta(days=5, hours=2),
                        ended_at=now - timedelta(days=5),
                        now=now,
                        resolved_by=ResolvedBy.HUMAN,
                        inbound_message_count=sum(1 for t in turns if t.inbound),
                        outbound_message_count=sum(1 for t in turns if not t.inbound),
                    ),
                    policy_allows=True,
                )
                durations.append(time.perf_counter() - started)
                await session.commit()
                if result.created:
                    made += 1
                else:
                    reused += 1
        _ = replay
        return made, reused, durations

    created, _reused, assemble_durations = await assemble_all(replay=False)
    load_seconds = time.perf_counter() - wall_started
    rusage_after = resource.getrusage(resource.RUSAGE_SELF)

    async with session_factory() as session:
        after_bytes = await _table_bytes(session)
        after_writes = await _write_counts(session)
        rows = (
            await session.execute(
                text(
                    "select count(*), count(distinct source_id) "
                    "from learning_observations where company_id = :c"
                ),
                {"c": VALIDATION_COMPANY},
            )
        ).one()

    # --- the replay: same sources, same pipeline version ---------------
    replay_started = time.perf_counter()
    replay_created, replay_reused, replay_durations = await assemble_all(replay=True)
    replay_seconds = time.perf_counter() - replay_started

    async with session_factory() as session:
        after_replay_writes = await _write_counts(session)
        after_replay_bytes = await _table_bytes(session)
        dead = {
            str(row[0]): int(row[1] or 0)
            for row in (
                await session.execute(
                    text(
                        "select relname, n_dead_tup from pg_stat_user_tables "
                        "where relname = any(:names)"
                    ),
                    {"names": list(LEARNING_TABLES)},
                )
            ).all()
        }
        after_replay_rows = (
            await session.execute(
                text(
                    "select count(*), count(distinct source_id) "
                    "from learning_observations where company_id = :c"
                ),
                {"c": VALIDATION_COMPANY},
            )
        ).one()
        refs = (
            await session.execute(
                text(
                    "select count(*) from learning_observation_refs r "
                    "join learning_observations o on o.id = r.observation_id "
                    "where o.company_id = :c"
                ),
                {"c": VALIDATION_COMPANY},
            )
        ).scalar_one()
        duplicate_refs = (
            await session.execute(
                text(
                    "select coalesce(sum(n - 1), 0) from ("
                    "  select count(*) as n from learning_observation_refs r"
                    "  join learning_observations o on o.id = r.observation_id"
                    "  where o.company_id = :c"
                    "  group by r.observation_id, r.ref_kind, r.ref_id"
                    ") d"
                ),
                {"c": VALIDATION_COMPANY},
            )
        ).scalar_one()

    total_bytes = sum(after_bytes.values()) - sum(before_bytes.values())
    writes = {
        table: after_writes.get(table, 0) - before_writes.get(table, 0) for table in LEARNING_TABLES
    }

    return {
        "corpus": corpus,
        "throughput": {
            "observations_assembled": created,
            "wall_seconds": round(load_seconds, 3),
            "observations_per_second": round(created / load_seconds, 2) if load_seconds else None,
            "observations_per_hour_single_worker": (
                round(created / load_seconds * 3600) if load_seconds else None
            ),
            "note": (
                "one worker, one connection, no broker. Consumers scale "
                "horizontally on their own queue, so this is a floor"
            ),
        },
        "assembly_latency": percentiles(assemble_durations),
        "replay": {
            "replay_latency": percentiles(replay_durations),
            "wall_seconds": round(replay_seconds, 3),
            "rows_before_replay": int(rows[0]),
            "distinct_sources_before_replay": int(rows[1]),
            "rows_after_replay": int(after_replay_rows[0]),
            "distinct_sources_after_replay": int(after_replay_rows[1]),
            "created_on_replay": replay_created,
            "suppressed_on_replay": replay_reused,
            "duplicate_suppression_rate": (round(replay_reused / corpus, 6) if corpus else None),
            "idempotency_success": bool(
                replay_created == 0
                and int(after_replay_rows[0]) == int(rows[0])
                and int(duplicate_refs) == 0
            ),
            "duplicate_observations": int(after_replay_rows[0]) - int(after_replay_rows[1]),
            "duplicate_content_refs": int(duplicate_refs),
            "content_refs": int(refs),
            "bytes_added_by_replay": sum(after_replay_bytes.values()) - sum(after_bytes.values()),
            "writes_during_replay": {
                table: after_replay_writes.get(table, 0) - after_writes.get(table, 0)
                for table in LEARNING_TABLES
            },
            "writes_per_replayed_observation": (
                round(
                    sum(
                        after_replay_writes.get(t, 0) - after_writes.get(t, 0)
                        for t in LEARNING_TABLES
                    )
                    / corpus,
                    2,
                )
                if corpus
                else None
            ),
            # MVCC: an UPDATE writes a new tuple and leaves the old one
            # dead until autovacuum. A replay that rewrites unchanged rows
            # costs disk twice over until then, which is why the write
            # count above matters more than it looks.
            "dead_tuples_after_replay": dead,
        },
        "storage": {
            "bytes_total": total_bytes,
            "bytes_per_observation": round(total_bytes / created) if created else None,
            "by_table": {
                table: after_bytes.get(table, 0) - before_bytes.get(table, 0)
                for table in LEARNING_TABLES
            },
        },
        "database_writes": {
            "by_table": writes,
            "writes_per_observation": (
                round(sum(writes.values()) / created, 2) if created else None
            ),
        },
        "process_resources": {
            "cpu_user_seconds": round(rusage_after.ru_utime - rusage_before.ru_utime, 3),
            "cpu_system_seconds": round(rusage_after.ru_stime - rusage_before.ru_stime, 3),
            "cpu_seconds_per_observation": (
                round(
                    (
                        (rusage_after.ru_utime - rusage_before.ru_utime)
                        + (rusage_after.ru_stime - rusage_before.ru_stime)
                    )
                    / created,
                    6,
                )
                if created
                else None
            ),
            "max_rss_mb": round(rusage_after.ru_maxrss / 1024, 1),
            "note": "this process, not the consumer container — see consumer_resources",
        },
    }


# ---------------------------------------------------------------------------
# 5. Health, as the dashboard reports it
# ---------------------------------------------------------------------------


async def measure_health(session: AsyncSession) -> dict[str, Any]:
    states = {
        str(row[0]): int(row[1])
        for row in (
            await session.execute(
                text(
                    "select state, count(*) from learning_observations "
                    "where company_id <> :c group by state"
                ),
                {"c": VALIDATION_COMPANY},
            )
        ).all()
    }
    exclusions = {
        str(row[0]): int(row[1])
        for row in (
            await session.execute(
                text(
                    "select exclusion_reason, count(*) from learning_observations "
                    "where company_id <> :c and exclusion_reason is not null "
                    "group by exclusion_reason"
                ),
                {"c": VALIDATION_COMPANY},
            )
        ).all()
    }
    replayed = (
        await session.execute(
            text(
                "select count(*) - count(distinct source_id) from learning_observations "
                "where company_id <> :c"
            ),
            {"c": VALIDATION_COMPANY},
        )
    ).scalar_one()
    runs = (
        await session.execute(
            text("select coalesce(sum(errors),0), count(*), max(started_at) from learning_runs")
        )
    ).one()
    erased = (
        await session.execute(
            text("select count(*) from audit_logs where action = 'memory.subject_erased'")
        )
    ).scalar_one()

    provenance = (
        await session.execute(
            text(
                "select coalesce(sum(ai_generated_count),0), coalesce(sum(ai_assisted_count),0), "
                "coalesce(sum(human_authored_count),0) from learning_observations "
                "where company_id <> :c"
            ),
            {"c": VALIDATION_COMPANY},
        )
    ).one()
    ai_total = int(provenance[0]) + int(provenance[1])
    all_total = ai_total + int(provenance[2])

    return {
        "pending": states.get("pending", 0),
        "settled": states.get("ready", 0),
        "excluded": states.get("excluded", 0),
        "exclusion_reasons": exclusions,
        "failed": int(runs[0] or 0),
        "replayed": int(replayed or 0),
        "erased": int(erased or 0),
        "runs_recorded": int(runs[1] or 0),
        "last_run_at": runs[2],
        "feedback_ratio": round(ai_total / all_total, 4) if all_total else None,
        "feedback_ratio_sample": all_total,
    }


# ---------------------------------------------------------------------------
# 7. Cost model
# ---------------------------------------------------------------------------


def cost_model(bytes_per_observation: int | None, *, per_day: int) -> dict[str, Any]:
    """Storage, projected. Nothing else — phase 1 buys no compute.

    ``per_day`` is the planning assumption, not a measurement, and is
    labelled as such: on an installation with no traffic there is nothing
    to extrapolate from, and a projection that hides its input is a guess
    wearing a table.
    """
    if bytes_per_observation is None:
        return {"unavailable": "no observations were assembled, so nothing to project"}

    gib = 1024**3
    per_million = bytes_per_observation * 1_000_000
    per_year = bytes_per_observation * per_day * 365

    return {
        "bytes_per_conversation_observed": bytes_per_observation,
        "kib_per_conversation_observed": round(bytes_per_observation / 1024, 2),
        "per_million_conversations_gib": round(per_million / gib, 3),
        "assumed_conversations_per_day": per_day,
        "after_one_year_gib": round(per_year / gib, 3),
        "note": (
            "includes indexes and the features and refs tables. Excludes "
            "message bodies, which Learning references and never copies — "
            "the reason this number is small"
        ),
    }


# ---------------------------------------------------------------------------


async def ensure_validation_company(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A real tenant row, because the schema insists on one.

    ``learning_observations.company_id`` has a foreign key, and that is
    not an obstacle to work around — it is the constraint that makes
    tenant isolation structural. So the benchmark gets a tenant of its
    own, suspended so nothing routes to it, and deleted on the way out.
    """
    async with session_factory() as session:
        await session.execute(
            text(
                """
                insert into companies (id, name, slug, status, settings)
                values (:id, 'Learning validation harness', :slug, 'SUSPENDED', '{}'::json)
                on conflict (id) do nothing
                """
            ),
            {"id": VALIDATION_COMPANY, "slug": f"learning-validation-{VALIDATION_COMPANY.hex[:8]}"},
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Phase 2 — clustering latency and throughput
# ---------------------------------------------------------------------------


async def measure_clustering(
    session_factory: async_sessionmaker[AsyncSession], *, now: datetime
) -> dict[str, Any]:
    """Cluster what the harness just wrote, and time it.

    Run against the validation tenant's own observations, so the numbers
    describe the algorithm rather than whatever the installation happens
    to hold. Latency is per *pass* rather than per observation: clustering
    compares each observation against every live centroid, so its cost is
    a function of how many clusters exist, and a per-observation figure
    would hide exactly that.
    """
    from blinkengage.application.services.learning_clustering_service import (
        LearningClusteringService,
    )
    from blinkengage.domain.learning_observation import PIPELINE_VERSION
    from blinkengage.infrastructure.repositories.learning_analysis_repository import (
        LearningClusterRepository,
    )

    started = time.perf_counter()
    async with session_factory() as session:
        repository = LearningClusterRepository(session)
        observations = await repository.observations_for_clustering(
            company_id=VALIDATION_COMPANY,
            pipeline_version=PIPELINE_VERSION,
            since=now - timedelta(days=3650),
            limit=100_000,
        )
        loaded = time.perf_counter() - started

        clustering_started = time.perf_counter()
        result = await LearningClusteringService(clusters=repository).cluster_company(
            company_id=VALIDATION_COMPANY,
            pipeline_version=PIPELINE_VERSION,
            observations=observations,
            now=now,
        )
        await session.commit()
        clustering = time.perf_counter() - clustering_started

    # The replay: same observations, nothing new to place.
    replay_started = time.perf_counter()
    async with session_factory() as session:
        repository = LearningClusterRepository(session)
        again = await repository.observations_for_clustering(
            company_id=VALIDATION_COMPANY,
            pipeline_version=PIPELINE_VERSION,
            since=now - timedelta(days=3650),
            limit=100_000,
        )
        replay = await LearningClusteringService(clusters=repository).cluster_company(
            company_id=VALIDATION_COMPANY,
            pipeline_version=PIPELINE_VERSION,
            observations=again,
            now=now,
        )
        await session.commit()
    replay_seconds = time.perf_counter() - replay_started

    async with session_factory() as session:
        sizes = (
            await session.execute(
                text(
                    "select count(*), coalesce(sum(size),0), "
                    "count(*) filter (where meets_floors) "
                    "from learning_clusters where company_id = :c"
                ),
                {"c": VALIDATION_COMPANY},
            )
        ).one()
        bytes_used = {
            str(name): int(size)
            for name, size in (
                await session.execute(
                    text(
                        "select relname, pg_total_relation_size(relid) "
                        "from pg_catalog.pg_statio_user_tables "
                        "where relname = any(:names)"
                    ),
                    {"names": ["learning_clusters", "learning_cluster_members"]},
                )
            ).all()
        }

    observations_seen = result.observations_considered
    return {
        "observations": observations_seen,
        "load_seconds": round(loaded, 4),
        "clustering_seconds": round(clustering, 4),
        "observations_per_second": (
            round(observations_seen / clustering, 2) if clustering else None
        ),
        "observations_per_hour": (
            round(observations_seen / clustering * 3600) if clustering else None
        ),
        "clusters_created": result.clusters_created,
        "clusters_merged": result.clusters_merged,
        "clusters_total": int(sizes[0]),
        "clusters_meeting_floors": int(sizes[2]),
        "mean_cluster_size": (round(int(sizes[1]) / int(sizes[0]), 2) if int(sizes[0]) else None),
        "replay": {
            "wall_seconds": round(replay_seconds, 4),
            "clusters_created": replay.clusters_created,
            "observations_placed": replay.observations_placed,
            "skipped_already_clustered": replay.observations_skipped_already_clustered,
            "duplicate_members_suppressed": replay.duplicate_members_suppressed,
            # The property the whole phase rests on: re-running creates
            # nothing.
            "replay_safe": replay.clusters_created == 0 and replay.observations_placed == 0,
        },
        "storage": {
            "bytes": sum(bytes_used.values()),
            "bytes_per_cluster": (
                round(sum(bytes_used.values()) / int(sizes[0])) if int(sizes[0]) else None
            ),
            "by_table": bytes_used,
        },
    }


async def cleanup(
    session_factory: async_sessionmaker[AsyncSession], *, drop_company: bool = False
) -> None:
    """A validation run leaves nothing behind.

    Not tidiness: these rows would be counted by the *next* run's volume
    and feedback-ratio measurements, which read from real tables. A
    benchmark that pollutes the thing it measures is worse than no
    benchmark.
    """
    async with session_factory() as session:
        # Phase 2's derived rows first: they reference the observations
        # below, and they are rebuildable, so removing them costs nothing
        # but the next sweep's work.
        await session.execute(
            text("delete from learning_cluster_members where company_id = :c"),
            {"c": VALIDATION_COMPANY},
        )
        for table in ("learning_anomalies", "learning_trends", "learning_clusters"):
            await session.execute(
                text(f"delete from {table} where company_id = :c"),  # noqa: S608
                {"c": VALIDATION_COMPANY},
            )
        for table in ("learning_observation_refs", "learning_observation_features"):
            await session.execute(
                text(
                    f"delete from {table} where observation_id in "  # noqa: S608
                    "(select id from learning_observations where company_id = :c)"
                ),
                {"c": VALIDATION_COMPANY},
            )
        await session.execute(
            text("delete from learning_observations where company_id = :c"),
            {"c": VALIDATION_COMPANY},
        )
        if drop_company:
            await session.execute(
                text("delete from companies where id = :c"), {"c": VALIDATION_COMPANY}
            )
        await session.commit()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260805)
    parser.add_argument(
        "--conversations-per-day",
        type=int,
        default=10_000,
        help="planning assumption for the storage projection",
    )
    parser.add_argument("--json", action="store_true", help="print JSON only")
    args = parser.parse_args()

    url = os.environ.get("DATABASE_URL", "")
    if "postgresql" not in url:
        print("DATABASE_URL must point at PostgreSQL — this measures the real storage layer")
        return 2

    engine = create_async_engine(url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    report = Report()
    report.add(
        "run",
        {
            "at": datetime.now(UTC),
            "pipeline_version": PIPELINE_VERSION,
            "corpus": args.corpus,
            "seed": args.seed,
        },
    )

    try:
        async with session_factory() as session:
            report.add("volume", await measure_volume(session))
            report.add("health", await measure_health(session))

        report.add("extraction", measure_extraction(max(args.corpus, len(LABELLED)), args.seed))

        if args.corpus > 0:
            await ensure_validation_company(session_factory)
            await cleanup(session_factory)
            load = await run_load(session_factory, corpus=args.corpus, seed=args.seed)
            report.add("load", load)
            report.add(
                "cost",
                cost_model(
                    load["storage"]["bytes_per_observation"],
                    per_day=args.conversations_per_day,
                ),
            )
            report.add(
                "clustering", await measure_clustering(session_factory, now=datetime.now(UTC))
            )
            await cleanup(session_factory, drop_company=True)
    finally:
        await engine.dispose()

    print(report.dump())
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
