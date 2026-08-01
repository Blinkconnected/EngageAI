"""The Service Directory — ``/api/v1/services``.

Gated on ``queues.read`` / ``queues.manage`` rather than a new permission
pair. Services *are* the routing configuration — that permission already
covers "queues, required skills, and routing rules" — and a new permission
would be denied to every company that has customised its roles, silently
locking their administrators out of a feature they can see in the navigation.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from blinkengage.api.deps import get_service_directory_service, require_permission
from blinkengage.api.schemas.service_directory import (
    ServiceCreateRequest,
    ServiceDetailResponse,
    ServiceResponse,
    ServiceSavedResponse,
    ServiceUpdateRequest,
    ServiceVersionResponse,
)
from blinkengage.application.services.service_directory_service import (
    ServiceDirectoryService,
    ServiceSaved,
)
from blinkengage.core.auth_context import AuthContext
from blinkengage.domain.runtime_queues import AiOverflowPolicy, OverflowStrategy
from blinkengage.domain.service_context import ServiceContext

router = APIRouter(prefix="/services", tags=["services"])


def _version_response(context: ServiceContext) -> ServiceVersionResponse:
    """A frozen configuration, as the console reads it.

    ``overflow_strategy`` and ``ai_overflow_policy`` fall back to their
    defaults when the service has no queue. They are stored on the version
    either way; the context only wraps them in a queue binding when there is
    a queue to bind to, and a service with none simply has nothing to
    overflow.
    """
    queue = context.queue
    return ServiceVersionResponse(
        id=context.service_version_id,
        version=context.version,
        name=context.name,
        logical_queue_id=queue.logical_queue_id if queue else None,
        logical_queue_name=queue.logical_queue_name if queue else None,
        overflow_strategy=queue.overflow_strategy if queue else OverflowStrategy.WAIT,
        ai_overflow_policy=queue.ai_overflow_policy if queue else AiOverflowPolicy.NEVER,
        sla_queue_minutes=context.sla.queue_minutes,
        sla_first_response_minutes=context.sla.first_response_minutes,
        sla_next_response_minutes=context.sla.next_response_minutes,
        sla_resolution_minutes=context.sla.resolution_minutes,
        ai_enabled=context.ai.enabled,
        ai_pickup_delay_seconds=context.ai.pickup_delay_seconds,
        ai_resume_delay_seconds=context.ai.resume_delay_seconds,
        ai_confidence_threshold=str(context.ai.confidence_threshold),
        extras=dict(context.extras),
    )


def _saved(result: ServiceSaved) -> ServiceSavedResponse:
    return ServiceSavedResponse(
        service=ServiceResponse.model_validate(result.service),
        current=_version_response(result.context),
        version_minted=result.version_minted,
    )


@router.get("", response_model=list[ServiceResponse])
async def list_services(
    auth: Annotated[AuthContext, Depends(require_permission("queues.read"))],
    service: Annotated[ServiceDirectoryService, Depends(get_service_directory_service)],
) -> list[ServiceResponse]:
    """The directory, in the order an operator arranged it.

    That order is what a customer is offered and what the fallback stage
    treats as a preference, so it is not alphabetical.
    """
    services = await service.list_for_company(auth.company_id)
    return [ServiceResponse.model_validate(item) for item in services]


@router.post("", response_model=ServiceSavedResponse, status_code=status.HTTP_201_CREATED)
async def create_service(
    payload: ServiceCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("queues.manage"))],
    service: Annotated[ServiceDirectoryService, Depends(get_service_directory_service)],
) -> ServiceSavedResponse:
    """Creates a service and its first version, together.

    A service without a version has no queue, no SLA and no AI policy to
    read, so it cannot be resolved into — creating one alone would put
    something unusable in the directory.
    """
    saved = await service.create(
        company_id=auth.company_id,
        code=payload.code,
        name=payload.name,
        description=payload.description,
        display_order=payload.display_order,
        actor_user_id=auth.user_id,
        logical_queue_id=payload.logical_queue_id,
        overflow_strategy=payload.overflow_strategy,
        ai_overflow_policy=payload.ai_overflow_policy,
        sla_queue_minutes=payload.sla.queue_minutes,
        sla_first_response_minutes=payload.sla.first_response_minutes,
        sla_next_response_minutes=payload.sla.next_response_minutes,
        sla_resolution_minutes=payload.sla.resolution_minutes,
        ai_enabled=payload.ai.enabled,
        ai_pickup_delay_seconds=payload.ai.pickup_delay_seconds,
        ai_resume_delay_seconds=payload.ai.resume_delay_seconds,
        ai_confidence_threshold=payload.ai.confidence_threshold,
        extras=payload.extras,
    )
    return _saved(saved)


@router.get("/{service_id}", response_model=ServiceDetailResponse)
async def read_service(
    service_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("queues.read"))],
    service: Annotated[ServiceDirectoryService, Depends(get_service_directory_service)],
) -> ServiceDetailResponse:
    saved = await service.get(company_id=auth.company_id, service_id=service_id)
    context = await service.context(company_id=auth.company_id, service_id=service_id)
    return _saved(ServiceSaved(service=saved, context=context, version_minted=False))


@router.get("/{service_id}/versions", response_model=list[ServiceVersionResponse])
async def read_service_versions(
    service_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("queues.read"))],
    service: Annotated[ServiceDirectoryService, Depends(get_service_directory_service)],
) -> list[ServiceVersionResponse]:
    """Newest first — every configuration this service has ever had.

    Conversations are still running on some of them, which is why they
    cannot be deleted and why this list is worth showing.
    """
    versions = await service.versions(company_id=auth.company_id, service_id=service_id)
    return [ServiceVersionResponse.model_validate(version) for version in versions]


@router.patch("/{service_id}", response_model=ServiceSavedResponse)
async def update_service(
    service_id: UUID,
    payload: ServiceUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("queues.manage"))],
    service: Annotated[ServiceDirectoryService, Depends(get_service_directory_service)],
) -> ServiceSavedResponse:
    """Applies an edit, minting a version only when one is needed.

    ``exclude_unset`` is load-bearing: a field the console did not send must
    mean *unchanged*, not *cleared*. Reading an absent SLA target as ``None``
    would silently stop measuring it, and the version recording that would
    look like somebody's decision.
    """
    sent = payload.model_dump(exclude_unset=True)
    change_note = sent.pop("change_note", None)

    changes: dict[str, object] = {
        key: value for key, value in sent.items() if key not in ("sla", "ai")
    }
    if "sla" in sent and payload.sla is not None:
        for field, value in payload.sla.model_dump().items():
            changes[f"sla_{field}"] = value
    if "ai" in sent and payload.ai is not None:
        for field, value in payload.ai.model_dump().items():
            changes[f"ai_{field}"] = value

    saved = await service.update(
        company_id=auth.company_id,
        service_id=service_id,
        changes=changes,
        change_note=change_note,
        actor_user_id=auth.user_id,
    )
    return _saved(saved)


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_service(
    service_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("queues.manage"))],
    service: Annotated[ServiceDirectoryService, Depends(get_service_directory_service)],
) -> None:
    """Removes a service from the directory.

    Its versions stay, and so do the conversations bound to them. A
    conversation that cannot say what it ran in is the failure this design
    exists to prevent, so nothing here is ever hard-deleted.
    """
    await service.archive(company_id=auth.company_id, service_id=service_id)


__all__ = ["router"]
