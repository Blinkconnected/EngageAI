"""Structured knowledge: create, publish, supersede, archive.

See ``docs/architecture/company-knowledge-and-voice.md``.

The service owns three things the repository deliberately does not:

**The contract.** Everything in ``domain/knowledge_records.py`` runs before
anything reaches the session, so "every published record has provenance" and
"no two active records overlap" are properties of the store rather than
habits of its callers.

**The overlap rule.** Not a database constraint: PostgreSQL could express it
as an exclusion constraint over a ``tstzrange``, SQLite cannot, and this
suite runs on SQLite. A rule enforced in one dialect only holds in
production and not in the tests that claim to check it. Enforced here, in
the write transaction, where both dialects see the same code.

**Supersession as one transaction.** Closing the old period and opening the
new one are one change. A half-applied supersession leaves two active
records claiming the same instant — the exact contradiction the design
exists to prevent, arrived at by the mechanism meant to prevent it.

There is no ``delete``. Not on the service, not on the repository, not in
the API. Withdrawal is ``archive``; replacement is ``supersede``.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.domain.knowledge_records import (
    KnowledgeAccessLevel,
    KnowledgeLifecycleState,
    KnowledgeRecordType,
    OverlappingRecordError,
    canonical_subject_key,
    normalise_subject_label,
    validate_attributes,
    validate_effective_period,
    validate_publishable,
    validate_transition,
)
from blinkengage.domain.memory import CreatedFrom
from blinkengage.infrastructure.database.models.knowledge_record import KnowledgeRecord
from blinkengage.infrastructure.repositories.knowledge_record_repository import (
    KnowledgeRecordRepository,
)


class KnowledgeRecordService:
    def __init__(
        self,
        *,
        records: KnowledgeRecordRepository,
        events: DomainEventPublisher,
    ) -> None:
        self._records = records
        self._events = events

    # -- reads ------------------------------------------------------------

    async def get(self, *, company_id: UUID, record_id: UUID) -> KnowledgeRecord:
        record = await self._records.get_by_id(company_id=company_id, record_id=record_id)
        if record is None:
            raise EntityNotFoundError("KnowledgeRecord", record_id)
        return record

    async def resolve(
        self,
        *,
        company_id: UUID,
        record_type: KnowledgeRecordType,
        subject_label: str,
        at: datetime | None = None,
    ) -> KnowledgeRecord | None:
        """The one authoritative record for a subject at a moment.

        Three outcomes, all explicit:

        * **exactly one** — returned, and it is authoritative
        * **none** — ``None``. The caller must treat this as *we do not
          know*, never as a reason to fall back to semantic search. That
          fallback is precisely how an expired price gets quoted a year
          later.
        * **more than one** — ``OverlappingRecordError``. Never a pick.

        Takes the *label* rather than the key so callers cannot skip
        canonicalisation: a caller that normalised differently would look up
        a key that nothing wrote.
        """
        moment = at or datetime.now(UTC)
        subject_key = canonical_subject_key(subject_label)
        matches = await self._records.resolve(
            company_id=company_id,
            record_type=record_type,
            subject_key=subject_key,
            at=moment,
        )
        if not matches:
            return None
        if len(matches) > 1:
            raise OverlappingRecordError(subject_key, record_type.value)
        return matches[0]

    async def list_versions(
        self, *, company_id: UUID, record_type: KnowledgeRecordType, subject_label: str
    ) -> list[KnowledgeRecord]:
        return list(
            await self._records.list_versions(
                company_id=company_id,
                record_type=record_type,
                subject_key=canonical_subject_key(subject_label),
            )
        )

    async def list_records(
        self,
        *,
        company_id: UUID,
        record_type: KnowledgeRecordType | None = None,
        subject_label: str | None = None,
        lifecycle_state: KnowledgeLifecycleState | None = None,
        at: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[KnowledgeRecord]:
        return list(
            await self._records.list_records(
                company_id=company_id,
                record_type=record_type,
                subject_key=(canonical_subject_key(subject_label) if subject_label else None),
                lifecycle_state=lifecycle_state,
                at=at,
                limit=limit,
                offset=offset,
            )
        )

    # -- writes -----------------------------------------------------------

    async def create_draft(
        self,
        *,
        company_id: UUID,
        record_type: KnowledgeRecordType,
        subject_label: str,
        attributes: dict[str, Any],
        effective_from: datetime,
        effective_until: datetime | None = None,
        access_level: KnowledgeAccessLevel = KnowledgeAccessLevel.PUBLIC_TO_AI,
        created_from: CreatedFrom = CreatedFrom.AGENT,
        source_document_version_id: UUID | None = None,
        source_reference: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> KnowledgeRecord:
        """A record that is not yet authoritative.

        Drafts deliberately do **not** require provenance and do **not**
        check for overlap: a draft is somebody working, and demanding either
        before they have finished would push people toward inventing one.
        Both bite at ``publish``, which is where a record becomes something
        the platform will say out loud.
        """
        period = validate_effective_period(effective_from, effective_until)
        cleaned = validate_attributes(record_type, attributes)
        label = normalise_subject_label(subject_label)
        subject_key = canonical_subject_key(subject_label)

        version = (
            await self._records.latest_version(
                company_id=company_id, record_type=record_type, subject_key=subject_key
            )
            + 1
        )

        record = KnowledgeRecord(
            company_id=company_id,
            record_type=record_type,
            subject_key=subject_key,
            subject_label=label,
            attributes=cleaned,
            effective_from=period.effective_from,
            effective_until=period.effective_until,
            version=version,
            lifecycle_state=KnowledgeLifecycleState.DRAFT,
            access_level=access_level,
            created_from=created_from.value,
            source_document_version_id=source_document_version_id,
            source_reference=source_reference,
        )
        self._records.add(record)
        await self._records.flush()

        await self._publish("knowledge_record.drafted", record, actor_user_id=actor_user_id)
        return record

    async def publish(
        self,
        *,
        company_id: UUID,
        record_id: UUID,
        actor_user_id: UUID | None = None,
        now: datetime | None = None,
    ) -> KnowledgeRecord:
        """Makes a draft authoritative.

        Both gates live here. Provenance, because an approved price whose
        source nobody recorded is a number the platform cannot defend in the
        audit it exists for. Overlap, because publishing into a period
        another active record already covers is how a subject acquires two
        current prices.
        """
        record = await self.get(company_id=company_id, record_id=record_id)
        validate_transition(
            KnowledgeLifecycleState(record.lifecycle_state), KnowledgeLifecycleState.ACTIVE
        )
        validate_publishable(
            source_document_version_id=record.source_document_version_id,
            source_reference=record.source_reference,
        )
        await self._assert_no_overlap(record)

        record.lifecycle_state = KnowledgeLifecycleState.ACTIVE
        record.approved_by_user_id = actor_user_id
        record.approved_at = now or datetime.now(UTC)
        await self._records.flush()

        await self._publish("knowledge_record.published", record, actor_user_id=actor_user_id)
        return record

    async def supersede(
        self,
        *,
        company_id: UUID,
        record_id: UUID,
        attributes: dict[str, Any],
        effective_from: datetime,
        effective_until: datetime | None = None,
        access_level: KnowledgeAccessLevel | None = None,
        created_from: CreatedFrom = CreatedFrom.AGENT,
        source_document_version_id: UUID | None = None,
        source_reference: str | None = None,
        actor_user_id: UUID | None = None,
        now: datetime | None = None,
    ) -> KnowledgeRecord:
        """Replaces an active record with a new version, in one transaction.

        The old record's period is closed to the new one's start **if it was
        open or would otherwise overlap**. That is what makes the handover
        exact: the old price stops being true at precisely the instant the
        new one starts, with no shared moment and no gap.

        The new record is published immediately — supersession is an
        approval, and requiring a second publish step would leave a subject
        with no active record in between.
        """
        current = await self.get(company_id=company_id, record_id=record_id)
        validate_transition(
            KnowledgeLifecycleState(current.lifecycle_state),
            KnowledgeLifecycleState.SUPERSEDED,
        )
        period = validate_effective_period(effective_from, effective_until)
        record_type = KnowledgeRecordType(current.record_type)
        cleaned = validate_attributes(record_type, attributes)
        validate_publishable(
            source_document_version_id=source_document_version_id,
            source_reference=source_reference,
        )

        if period.effective_from < current.effective_from:
            raise OverlappingRecordError(current.subject_key, record_type.value)

        version = (
            await self._records.latest_version(
                company_id=company_id,
                record_type=record_type,
                subject_key=current.subject_key,
            )
            + 1
        )

        replacement = KnowledgeRecord(
            company_id=company_id,
            record_type=record_type,
            subject_key=current.subject_key,
            subject_label=current.subject_label,
            attributes=cleaned,
            effective_from=period.effective_from,
            effective_until=period.effective_until,
            version=version,
            supersedes_id=current.id,
            lifecycle_state=KnowledgeLifecycleState.ACTIVE,
            access_level=(
                access_level
                if access_level is not None
                else KnowledgeAccessLevel(current.access_level)
            ),
            created_from=created_from.value,
            source_document_version_id=source_document_version_id,
            source_reference=source_reference,
            approved_by_user_id=actor_user_id,
            approved_at=now or datetime.now(UTC),
        )
        self._records.add(replacement)
        await self._records.flush()

        # Close the outgoing period *before* checking overlap, so the check
        # sees the state the transaction will actually commit.
        if current.effective_until is None or current.effective_until > period.effective_from:
            current.effective_until = period.effective_from
        current.lifecycle_state = KnowledgeLifecycleState.SUPERSEDED
        current.superseded_by_id = replacement.id
        await self._records.flush()

        await self._assert_no_overlap(replacement)

        await self._publish(
            "knowledge_record.superseded",
            current,
            actor_user_id=actor_user_id,
            extra={"superseded_by": str(replacement.id)},
        )
        await self._publish("knowledge_record.published", replacement, actor_user_id=actor_user_id)
        return replacement

    async def archive(
        self,
        *,
        company_id: UUID,
        record_id: UUID,
        actor_user_id: UUID | None = None,
        now: datetime | None = None,
    ) -> KnowledgeRecord:
        """Withdraws a record without deleting it.

        The row stays readable forever. "We withdrew this on the 14th" is an
        answer; "there is no row" is not.
        """
        record = await self.get(company_id=company_id, record_id=record_id)
        validate_transition(
            KnowledgeLifecycleState(record.lifecycle_state),
            KnowledgeLifecycleState.ARCHIVED,
        )
        record.lifecycle_state = KnowledgeLifecycleState.ARCHIVED
        record.archived_at = now or datetime.now(UTC)
        await self._records.flush()

        await self._publish("knowledge_record.archived", record, actor_user_id=actor_user_id)
        return record

    # -- internals --------------------------------------------------------

    async def _assert_no_overlap(self, record: KnowledgeRecord) -> None:
        clashes = await self._records.find_overlapping_active(
            company_id=record.company_id,
            record_type=KnowledgeRecordType(record.record_type),
            subject_key=record.subject_key,
            effective_from=record.effective_from,
            effective_until=record.effective_until,
            exclude_id=record.id,
        )
        if clashes:
            raise OverlappingRecordError(record.subject_key, str(record.record_type))

    async def _publish(
        self,
        event_type: str,
        record: KnowledgeRecord,
        *,
        actor_user_id: UUID | None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        # The subject and its lifecycle travel; ``attributes`` does not. A
        # price is exactly the kind of value that should not be sprayed
        # across every consumer of the bus — anything that needs the number
        # can read the record it names, under the permission that read
        # requires.
        payload: dict[str, Any] = {
            "record_type": str(record.record_type),
            "subject_key": record.subject_key,
            "version": record.version,
            "lifecycle_state": str(record.lifecycle_state),
            "access_level": str(record.access_level),
        }
        if extra:
            payload.update(extra)

        await self._events.publish(
            DomainEvent(
                event_type=event_type,
                company_id=record.company_id,
                aggregate_type="knowledge_record",
                aggregate_id=record.id,
                actor_user_id=actor_user_id,
                payload=payload,
            )
        )
