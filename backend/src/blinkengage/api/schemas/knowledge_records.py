"""Request and response shapes for structured knowledge.

See ``docs/architecture/company-knowledge-and-voice.md``.

``subject_key`` is **never accepted from a caller.** It is derived from
``subject_label`` by ``domain.knowledge_records.canonical_subject_key``, and
letting a client supply one would mean two callers could write two keys for
the same product and silently fork its history. It is returned, because a
client needs it to build a resolve URL.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from blinkengage.domain.knowledge_records import (
    MAX_SUBJECT_LABEL_CHARS,
    KnowledgeAccessLevel,
    KnowledgeLifecycleState,
    KnowledgeRecordType,
)


class KnowledgeRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    record_type: KnowledgeRecordType
    subject_key: str
    subject_label: str
    attributes: dict[str, Any]
    attributes_schema_version: int
    effective_from: datetime
    effective_until: datetime | None
    version: int
    supersedes_id: UUID | None
    superseded_by_id: UUID | None
    lifecycle_state: KnowledgeLifecycleState
    access_level: KnowledgeAccessLevel
    created_from: str
    source_document_version_id: UUID | None
    source_reference: str | None
    approved_by_user_id: UUID | None
    approved_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class KnowledgeRecordCreateRequest(BaseModel):
    record_type: KnowledgeRecordType
    subject_label: str = Field(min_length=1, max_length=MAX_SUBJECT_LABEL_CHARS)
    attributes: dict[str, Any] = Field(default_factory=dict)
    effective_from: datetime
    effective_until: datetime | None = None
    access_level: KnowledgeAccessLevel = KnowledgeAccessLevel.PUBLIC_TO_AI
    source_reference: str | None = Field(default=None, max_length=2000)
    source_document_version_id: UUID | None = None


class KnowledgeRecordSupersedeRequest(BaseModel):
    """The replacement's content. The subject and type come from the record
    being superseded — a supersession that could change either would not be
    a new version of anything, it would be a different record wearing the
    old one's history."""

    attributes: dict[str, Any] = Field(default_factory=dict)
    effective_from: datetime
    effective_until: datetime | None = None
    access_level: KnowledgeAccessLevel | None = None
    source_reference: str | None = Field(default=None, max_length=2000)
    source_document_version_id: UUID | None = None


class KnowledgeRecordResolutionResponse(BaseModel):
    """The answer to "what is true about this subject right now".

    ``record`` is ``None`` when nothing is active, and that is a real
    answer rather than an error: the caller must say *we do not know*, and
    must not fall back to searching for something that looks similar.
    """

    subject_key: str
    resolved_at: datetime
    record: KnowledgeRecordResponse | None
