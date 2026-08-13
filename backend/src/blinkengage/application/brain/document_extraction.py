"""Attachments to text, or to a stated refusal. Never to knowledge.

The destination in this phase is a ``knowledge_documents`` row. Nothing here
writes a ``KnowledgeRecord``, proposes one, or calls a model — 4D and 4E are
not authorized, and the structural tests fail the build if that changes.

Order is deliberate and cheap-first: hash, dedupe, size, sniff, resolve a
parser, *then* parse. Every step before the last costs microseconds and can
refuse; only the last one costs real work on attacker-chosen input.

Storage happens for documents that passed the size check, including ones a
parser then refused. A scanned price list nobody could read is exactly the file
an operator will want to open by hand, and a rejection that discarded the
evidence would make that impossible. Oversized files are the exception: they
are refused before storage, because storing them is the cost being avoided.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.core.logging import get_logger
from blinkengage.domain.brain.document_parser import DocumentParser, ExtractedDocument
from blinkengage.domain.brain.documents import (
    DocumentKind,
    DocumentRejected,
    DocumentRejection,
    check_size,
    sniff,
)
from blinkengage.infrastructure.database.models.knowledge_source import KnowledgeDocument
from blinkengage.infrastructure.document_extraction.parsers import resolve_parser

logger = get_logger(__name__)

STATUS_EXTRACTED = "EXTRACTED"
STATUS_REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class Attachment:
    """One part of a message, as bytes and a claimed name.

    ``declared_content_type`` is recorded and never trusted. It is the
    sender's word, kept only so the claim and the sniffed reality can be
    compared afterwards.
    """

    filename: str
    data: bytes
    declared_content_type: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentOutcome:
    document_id: UUID | None
    extracted: bool
    duplicate: bool = False
    rejection: DocumentRejection | None = None


class AttachmentStorage(Protocol):
    """The one method of ``AttachmentStore`` this service needs.

    Narrow on purpose, and structural so the real store satisfies it without
    knowing this exists. Upload only: a component that cannot read from object
    storage cannot be talked into reading another tenant's key.
    """

    async def upload(self, *, key: str, data: bytes, content_type: str) -> None: ...


class KnowledgeDocumentExtractor:
    """Reads attachments for one company, and refuses the rest."""

    def __init__(self, *, session: AsyncSession, storage: AttachmentStorage | None = None) -> None:
        self._session = session
        # Optional so the pipeline still records what arrived when object
        # storage is unavailable. The text is the point; the blob is evidence,
        # and losing the evidence must not lose the record of the attempt.
        self._storage = storage

    async def extract(
        self, *, company_id: UUID, source_message_id: UUID | None, attachment: Attachment
    ) -> DocumentOutcome:
        content_hash = hashlib.sha256(attachment.data).hexdigest()

        existing = await self._session.execute(
            select(KnowledgeDocument.id).where(
                KnowledgeDocument.company_id == company_id,
                KnowledgeDocument.content_hash == content_hash,
            )
        )
        found = existing.scalars().first()
        if found is not None:
            # Deterministic dedupe: identical bytes for this company are the
            # same document, whichever message carried them.
            return DocumentOutcome(document_id=found, extracted=False, duplicate=True)

        kind: DocumentKind | None = None
        rejection: DocumentRejection | None = None
        detail = ""
        result: ExtractedDocument | None = None

        try:
            # Cheapest refusal first. An oversized file is rejected before it
            # is hashed into storage or handed to a parser.
            check_size(attachment.data)

            kind = sniff(attachment.data, filename=attachment.filename)
            if kind is None:
                raise DocumentRejected(
                    DocumentRejection.UNSUPPORTED_TYPE,
                    "content does not match a supported document type",
                )

            parser = resolve_parser(kind)
            if parser is None:  # pragma: no cover - registry covers every kind
                raise DocumentRejected(DocumentRejection.UNSUPPORTED_TYPE, f"no parser for {kind}")

            result = _extract_with(parser, attachment.data)
        except DocumentRejected as refused:
            rejection = refused.reason
            detail = refused.detail
            logger.info(
                "knowledge_document_rejected",
                company_id=str(company_id),
                filename=attachment.filename,
                reason=refused.reason.value,
            )

        storage_key: str | None = None
        if rejection is not DocumentRejection.TOO_LARGE and self._storage is not None:
            # Company-prefixed, hash-named: the key cannot collide across
            # tenants and cannot be guessed from a filename.
            storage_key = f"knowledge/{company_id}/{content_hash}"
            try:
                await self._storage.upload(
                    key=storage_key,
                    data=attachment.data,
                    content_type=attachment.declared_content_type or "application/octet-stream",
                )
            except Exception:  # noqa: BLE001 - evidence is not the record
                logger.warning(
                    "knowledge_document_storage_failed",
                    company_id=str(company_id),
                    exc_info=True,
                )
                storage_key = None

        row = KnowledgeDocument(
            company_id=company_id,
            source_message_id=source_message_id,
            filename=attachment.filename[:500],
            detected_kind=kind.value if kind else None,
            declared_content_type=attachment.declared_content_type,
            size_bytes=len(attachment.data),
            content_hash=content_hash,
            storage_key=storage_key,
            status=STATUS_REJECTED if rejection else STATUS_EXTRACTED,
            rejection_reason=rejection.value if rejection else None,
            rejection_detail=detail or None,
            extracted_text=result.text if result else None,
            parser=result.parser if result else None,
            parser_version=result.parser_version if result else None,
            units_read=result.units_read if result else 0,
            truncated=result.truncated if result else False,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError:
            # Two workers reached the same new document at once. The
            # constraint decides, exactly as it does for source messages.
            await self._session.rollback()
            return DocumentOutcome(document_id=None, extracted=False, duplicate=True)

        return DocumentOutcome(document_id=row.id, extracted=rejection is None, rejection=rejection)


def _extract_with(parser: object, data: bytes) -> ExtractedDocument:
    """Run a resolved parser, treating any unexpected failure as corruption.

    A parser reading hostile input may fail in ways its library never
    documented. Every one of those is a refusal with a reason, never an
    exception escaping into the poll loop where it would cost the whole batch.
    """
    typed: DocumentParser = parser  # type: ignore[assignment]
    try:
        return typed.extract(data)
    except DocumentRejected:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DocumentRejected(DocumentRejection.CORRUPT, str(exc)) from exc


__all__ = [
    "STATUS_EXTRACTED",
    "STATUS_REJECTED",
    "Attachment",
    "AttachmentStorage",
    "DocumentOutcome",
    "KnowledgeDocumentExtractor",
]
