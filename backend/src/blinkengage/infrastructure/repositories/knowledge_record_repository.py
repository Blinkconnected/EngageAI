"""Structured-knowledge persistence.

See ``docs/architecture/company-knowledge-and-voice.md``.

**Every method takes ``company_id`` and applies it.** Not as a convention —
as the tenant boundary. This layer sits below anything a model influences,
so a misrouted query cannot cross a company even if every layer above it
was talked into trying.

The resolution query is the reason this file exists rather than the service
issuing selects: "which record is authoritative for this subject at this
moment" is one question with one correct SQL shape, and having it in one
place is what stops the live lookup and the ``as_of`` history query drifting
into two different definitions of *active*.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.knowledge_records import (
    RESOLVABLE_STATES,
    KnowledgeLifecycleState,
    KnowledgeRecordType,
)
from blinkengage.infrastructure.database.models.knowledge_record import KnowledgeRecord

_RecordSelect = Select[tuple[KnowledgeRecord]]


def _covering(stmt: _RecordSelect, moment: datetime) -> _RecordSelect:
    """Narrows to records whose half-open period contains ``moment``.

    ``effective_from <= moment < effective_until``, with ``NULL`` until
    meaning open-ended. Half-open is what makes supersession exact: the old
    price stops being true at precisely the instant the new one starts, with
    no shared moment where both are active and no gap where neither is.
    """
    return stmt.where(
        KnowledgeRecord.effective_from <= moment,
        or_(
            KnowledgeRecord.effective_until.is_(None),
            KnowledgeRecord.effective_until > moment,
        ),
    )


class KnowledgeRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, record_id: UUID) -> KnowledgeRecord | None:
        result = await self._session.execute(
            select(KnowledgeRecord).where(
                KnowledgeRecord.id == record_id,
                KnowledgeRecord.company_id == company_id,
            )
        )
        return result.scalar_one_or_none()

    async def resolve(
        self,
        *,
        company_id: UUID,
        record_type: KnowledgeRecordType,
        subject_key: str,
        at: datetime,
    ) -> Sequence[KnowledgeRecord]:
        """Every ACTIVE record for this subject covering ``at``.

        Returns a sequence rather than one row **on purpose**. Two active
        records covering one instant is a contradiction the caller must
        surface, and a repository that returned ``.first()`` would hide it
        behind whichever row the planner happened to emit first — turning a
        data problem into a quotation.
        """
        stmt = _covering(
            select(KnowledgeRecord).where(
                KnowledgeRecord.company_id == company_id,
                KnowledgeRecord.record_type == record_type,
                KnowledgeRecord.subject_key == subject_key,
                # ACTIVE *and* SUPERSEDED — see ``RESOLVABLE_STATES``. A
                # price change scheduled for next month supersedes today's
                # record immediately, and resolving only ACTIVE would leave
                # the subject unpriced until the change lands.
                KnowledgeRecord.lifecycle_state.in_(sorted(RESOLVABLE_STATES)),
            ),
            at,
        ).order_by(KnowledgeRecord.version.desc())
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def find_overlapping_active(
        self,
        *,
        company_id: UUID,
        record_type: KnowledgeRecordType,
        subject_key: str,
        effective_from: datetime,
        effective_until: datetime | None,
        exclude_id: UUID | None = None,
    ) -> Sequence[KnowledgeRecord]:
        """ACTIVE records whose period intersects the given one.

        Two half-open periods overlap unless one ends at or before the other
        begins. Expressed as the negation of the two disjoint cases, which is
        one condition per bound rather than the four-way case analysis the
        positive form needs.
        """
        stmt = select(KnowledgeRecord).where(
            KnowledgeRecord.company_id == company_id,
            KnowledgeRecord.record_type == record_type,
            KnowledgeRecord.subject_key == subject_key,
            KnowledgeRecord.lifecycle_state == KnowledgeLifecycleState.ACTIVE,
        )
        if exclude_id is not None:
            stmt = stmt.where(KnowledgeRecord.id != exclude_id)

        # The existing record must not end before the new one starts.
        stmt = stmt.where(
            or_(
                KnowledgeRecord.effective_until.is_(None),
                KnowledgeRecord.effective_until > effective_from,
            )
        )
        # ...and the new one must not end before the existing one starts.
        if effective_until is not None:
            stmt = stmt.where(KnowledgeRecord.effective_from < effective_until)

        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def latest_version(
        self, *, company_id: UUID, record_type: KnowledgeRecordType, subject_key: str
    ) -> int:
        """The highest version number in this subject's chain, or 0.

        Counts **every** lifecycle state, archived and superseded included: a
        version number is an identity in the chain, and reusing one because
        its holder was archived would make two rows in the audit trail claim
        to be the same version.
        """
        result = await self._session.execute(
            select(KnowledgeRecord.version)
            .where(
                KnowledgeRecord.company_id == company_id,
                KnowledgeRecord.record_type == record_type,
                KnowledgeRecord.subject_key == subject_key,
            )
            .order_by(KnowledgeRecord.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none() or 0

    async def list_versions(
        self, *, company_id: UUID, record_type: KnowledgeRecordType, subject_key: str
    ) -> Sequence[KnowledgeRecord]:
        result = await self._session.execute(
            select(KnowledgeRecord)
            .where(
                KnowledgeRecord.company_id == company_id,
                KnowledgeRecord.record_type == record_type,
                KnowledgeRecord.subject_key == subject_key,
            )
            .order_by(KnowledgeRecord.version.desc())
        )
        return result.scalars().all()

    async def list_records(
        self,
        *,
        company_id: UUID,
        record_type: KnowledgeRecordType | None = None,
        subject_key: str | None = None,
        lifecycle_state: KnowledgeLifecycleState | None = None,
        at: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[KnowledgeRecord]:
        stmt = select(KnowledgeRecord).where(KnowledgeRecord.company_id == company_id)
        if record_type is not None:
            stmt = stmt.where(KnowledgeRecord.record_type == record_type)
        if subject_key is not None:
            stmt = stmt.where(KnowledgeRecord.subject_key == subject_key)
        if lifecycle_state is not None:
            stmt = stmt.where(KnowledgeRecord.lifecycle_state == lifecycle_state)
        if at is not None:
            stmt = _covering(stmt, at)

        stmt = (
            stmt.order_by(KnowledgeRecord.subject_key.asc(), KnowledgeRecord.version.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    def add(self, record: KnowledgeRecord) -> None:
        self._session.add(record)

    async def flush(self) -> None:
        await self._session.flush()
