"""Structured knowledge: prices, SLA terms and product attributes.

See ``docs/architecture/company-knowledge-and-voice.md``.

**There is no DELETE route on this router, and that is structural.** A
price that was quoted must be reproducible in an audit two years later, so
withdrawal is ``POST /{id}/archive`` and replacement is
``POST /{id}/supersede``. Neither loses the row. A route that removed one
would make the audit trail depend on nobody having called it.

Permissions split by blast radius rather than by entity: reading a price is
what an agent does all day, drafting one changes nothing until approved, and
publishing is the platform committing to a number it will quote.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from blinkengage.api.deps import get_knowledge_record_service, require_permission
from blinkengage.api.schemas.knowledge_records import (
    KnowledgeRecordCreateRequest,
    KnowledgeRecordResolutionResponse,
    KnowledgeRecordResponse,
    KnowledgeRecordSupersedeRequest,
)
from blinkengage.application.services.knowledge_record_service import (
    KnowledgeRecordService,
)
from blinkengage.core.auth_context import AuthContext
from blinkengage.domain.knowledge_records import (
    KnowledgeLifecycleState,
    KnowledgeRecordType,
    canonical_subject_key,
)

router = APIRouter(prefix="/knowledge/records", tags=["knowledge"])


@router.get("", response_model=list[KnowledgeRecordResponse])
async def list_records(
    service: Annotated[KnowledgeRecordService, Depends(get_knowledge_record_service)],
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_records.read"))],
    record_type: KnowledgeRecordType | None = None,
    subject_label: str | None = None,
    lifecycle_state: KnowledgeLifecycleState | None = None,
    at: datetime | None = Query(
        default=None,
        description=(
            "Only records whose effective period covers this instant. "
            "Omit for every record regardless of period."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[KnowledgeRecordResponse]:
    records = await service.list_records(
        company_id=auth.company_id,
        record_type=record_type,
        subject_label=subject_label,
        lifecycle_state=lifecycle_state,
        at=at,
        limit=limit,
        offset=offset,
    )
    return [KnowledgeRecordResponse.model_validate(record) for record in records]


@router.get("/resolve", response_model=KnowledgeRecordResolutionResponse)
async def resolve_record(
    service: Annotated[KnowledgeRecordService, Depends(get_knowledge_record_service)],
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_records.read"))],
    record_type: KnowledgeRecordType,
    subject_label: str = Query(min_length=1),
    at: datetime | None = None,
) -> KnowledgeRecordResolutionResponse:
    """The one authoritative record for a subject at a moment.

    A ``record`` of ``null`` means *we do not know*, and callers must treat
    it that way rather than falling back to a similarity search — that
    fallback is how an expired price gets quoted a year later. Two active
    records covering the same instant is a contradiction and raises rather
    than picking one.
    """
    moment = at or datetime.now(UTC)
    record = await service.resolve(
        company_id=auth.company_id,
        record_type=record_type,
        subject_label=subject_label,
        at=moment,
    )
    return KnowledgeRecordResolutionResponse(
        subject_key=canonical_subject_key(subject_label),
        resolved_at=moment,
        record=(KnowledgeRecordResponse.model_validate(record) if record else None),
    )


@router.get("/{record_id}", response_model=KnowledgeRecordResponse)
async def get_record(
    record_id: UUID,
    service: Annotated[KnowledgeRecordService, Depends(get_knowledge_record_service)],
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_records.read"))],
) -> KnowledgeRecordResponse:
    record = await service.get(company_id=auth.company_id, record_id=record_id)
    return KnowledgeRecordResponse.model_validate(record)


@router.get("/{record_id}/versions", response_model=list[KnowledgeRecordResponse])
async def list_versions(
    record_id: UUID,
    service: Annotated[KnowledgeRecordService, Depends(get_knowledge_record_service)],
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_records.read"))],
) -> list[KnowledgeRecordResponse]:
    """Every version of this record's subject, newest first.

    Superseded and archived versions included — the chain is the audit
    trail, and a history that showed only the current version would not be
    one.
    """
    record = await service.get(company_id=auth.company_id, record_id=record_id)
    versions = await service.list_versions(
        company_id=auth.company_id,
        record_type=KnowledgeRecordType(record.record_type),
        subject_label=record.subject_label,
    )
    return [KnowledgeRecordResponse.model_validate(version) for version in versions]


@router.post("", response_model=KnowledgeRecordResponse, status_code=status.HTTP_201_CREATED)
async def create_record(
    payload: KnowledgeRecordCreateRequest,
    service: Annotated[KnowledgeRecordService, Depends(get_knowledge_record_service)],
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_records.propose"))],
) -> KnowledgeRecordResponse:
    """Creates a draft. Drafts are never authoritative and never retrieved.

    Provenance is not required here — a draft is somebody working. It is
    required to publish.
    """
    record = await service.create_draft(
        company_id=auth.company_id,
        record_type=payload.record_type,
        subject_label=payload.subject_label,
        attributes=payload.attributes,
        effective_from=payload.effective_from,
        effective_until=payload.effective_until,
        access_level=payload.access_level,
        source_document_version_id=payload.source_document_version_id,
        source_reference=payload.source_reference,
        actor_user_id=auth.user_id,
    )
    return KnowledgeRecordResponse.model_validate(record)


@router.post("/{record_id}/publish", response_model=KnowledgeRecordResponse)
async def publish_record(
    record_id: UUID,
    service: Annotated[KnowledgeRecordService, Depends(get_knowledge_record_service)],
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_records.publish"))],
) -> KnowledgeRecordResponse:
    record = await service.publish(
        company_id=auth.company_id, record_id=record_id, actor_user_id=auth.user_id
    )
    return KnowledgeRecordResponse.model_validate(record)


@router.post("/{record_id}/supersede", response_model=KnowledgeRecordResponse)
async def supersede_record(
    record_id: UUID,
    payload: KnowledgeRecordSupersedeRequest,
    service: Annotated[KnowledgeRecordService, Depends(get_knowledge_record_service)],
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_records.publish"))],
) -> KnowledgeRecordResponse:
    """Replaces an active record with a new version, in one transaction.

    Returns the replacement. The superseded record keeps its row, its
    period closed to the instant the new one starts.
    """
    record = await service.supersede(
        company_id=auth.company_id,
        record_id=record_id,
        attributes=payload.attributes,
        effective_from=payload.effective_from,
        effective_until=payload.effective_until,
        access_level=payload.access_level,
        source_document_version_id=payload.source_document_version_id,
        source_reference=payload.source_reference,
        actor_user_id=auth.user_id,
    )
    return KnowledgeRecordResponse.model_validate(record)


@router.post("/{record_id}/archive", response_model=KnowledgeRecordResponse)
async def archive_record(
    record_id: UUID,
    service: Annotated[KnowledgeRecordService, Depends(get_knowledge_record_service)],
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_records.publish"))],
) -> KnowledgeRecordResponse:
    """Withdraws a record. The row stays readable forever."""
    record = await service.archive(
        company_id=auth.company_id, record_id=record_id, actor_user_id=auth.user_id
    )
    return KnowledgeRecordResponse.model_validate(record)
