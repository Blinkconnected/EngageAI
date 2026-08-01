from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from blinkengage.api.deps import get_sla_policy_service, require_permission
from blinkengage.api.schemas.sla import (
    HolidayCreateRequest,
    HolidayResponse,
    HolidayUpdateRequest,
    SlaPolicyCreateRequest,
    SlaPolicyResponse,
    SlaPolicyUpdateRequest,
    SlaPreviewRequest,
    SlaPreviewResponse,
)
from blinkengage.application.services.sla_policy_service import SlaPolicyService
from blinkengage.core.auth_context import AuthContext
from blinkengage.infrastructure.database.models.sla import Holiday, SlaPolicy

router = APIRouter(tags=["sla"])


async def _to_policy_response(policy: SlaPolicy, service: SlaPolicyService) -> SlaPolicyResponse:
    assigned = await service.assigned_queue_count(policy.id)
    return SlaPolicyResponse(
        id=policy.id,
        name=policy.name,
        description=policy.description,
        first_response_target_minutes=policy.first_response_target_minutes,
        resolution_target_minutes=policy.resolution_target_minutes,
        warning_threshold_percent=policy.warning_threshold_percent,
        business_hours_aware=policy.business_hours_aware,
        escalation_rules=policy.escalation_rules,
        is_active=policy.is_active,
        assigned_queue_count=assigned,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


@router.get("/sla-policies", response_model=list[SlaPolicyResponse])
async def list_sla_policies(
    auth: Annotated[AuthContext, Depends(require_permission("sla_policies.read"))],
    service: Annotated[SlaPolicyService, Depends(get_sla_policy_service)],
) -> list[SlaPolicyResponse]:
    """Unpaginated, like Roles & Permissions and Routing Rules — a
    company's SLA policy count is small and meant to be seen as a
    whole."""
    policies = await service.list_policies(auth.company_id)
    return [await _to_policy_response(policy, service) for policy in policies]


@router.post("/sla-policies", response_model=SlaPolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_sla_policy(
    payload: SlaPolicyCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("sla_policies.manage"))],
    service: Annotated[SlaPolicyService, Depends(get_sla_policy_service)],
) -> SlaPolicyResponse:
    policy = await service.create(
        company_id=auth.company_id,
        name=payload.name,
        description=payload.description,
        first_response_target_minutes=payload.first_response_target_minutes,
        resolution_target_minutes=payload.resolution_target_minutes,
        warning_threshold_percent=payload.warning_threshold_percent,
        business_hours_aware=payload.business_hours_aware,
        escalation_rules=[rule.model_dump(mode="json") for rule in payload.escalation_rules],
        actor_user_id=auth.user_id,
    )
    return await _to_policy_response(policy, service)


@router.get("/sla-policies/{policy_id}", response_model=SlaPolicyResponse)
async def get_sla_policy(
    policy_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("sla_policies.read"))],
    service: Annotated[SlaPolicyService, Depends(get_sla_policy_service)],
) -> SlaPolicyResponse:
    policy = await service.get(company_id=auth.company_id, policy_id=policy_id)
    return await _to_policy_response(policy, service)


@router.patch("/sla-policies/{policy_id}", response_model=SlaPolicyResponse)
async def update_sla_policy(
    policy_id: UUID,
    payload: SlaPolicyUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("sla_policies.manage"))],
    service: Annotated[SlaPolicyService, Depends(get_sla_policy_service)],
) -> SlaPolicyResponse:
    policy = await service.update(
        company_id=auth.company_id,
        policy_id=policy_id,
        name=payload.name,
        description=payload.description,
        first_response_target_minutes=payload.first_response_target_minutes,
        resolution_target_minutes=payload.resolution_target_minutes,
        warning_threshold_percent=payload.warning_threshold_percent,
        business_hours_aware=payload.business_hours_aware,
        escalation_rules=(
            None
            if payload.escalation_rules is None
            else [rule.model_dump(mode="json") for rule in payload.escalation_rules]
        ),
        is_active=payload.is_active,
        actor_user_id=auth.user_id,
    )
    return await _to_policy_response(policy, service)


@router.delete("/sla-policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sla_policy(
    policy_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("sla_policies.manage"))],
    service: Annotated[SlaPolicyService, Depends(get_sla_policy_service)],
) -> None:
    await service.delete(
        company_id=auth.company_id, policy_id=policy_id, actor_user_id=auth.user_id
    )


@router.post("/sla-policies/preview", response_model=SlaPreviewResponse)
async def preview_sla_policy(
    payload: SlaPreviewRequest,
    auth: Annotated[AuthContext, Depends(require_permission("sla_policies.read"))],
    service: Annotated[SlaPolicyService, Depends(get_sla_policy_service)],
) -> SlaPreviewResponse:
    (
        first_response_warning_at,
        first_response_deadline,
        resolution_warning_at,
        resolution_deadline,
    ) = await service.preview(
        company_id=auth.company_id, policy_id=payload.policy_id, starts_at=payload.starts_at
    )
    return SlaPreviewResponse(
        first_response_warning_at=first_response_warning_at,
        first_response_deadline=first_response_deadline,
        resolution_warning_at=resolution_warning_at,
        resolution_deadline=resolution_deadline,
    )


def _to_holiday_response(holiday: Holiday) -> HolidayResponse:
    return HolidayResponse(
        id=holiday.id, name=holiday.name, date=holiday.date, recurs_annually=holiday.recurs_annually
    )


@router.get("/holidays", response_model=list[HolidayResponse])
async def list_holidays(
    auth: Annotated[AuthContext, Depends(require_permission("sla_policies.read"))],
    service: Annotated[SlaPolicyService, Depends(get_sla_policy_service)],
) -> list[HolidayResponse]:
    holidays = await service.list_holidays(auth.company_id)
    return [_to_holiday_response(holiday) for holiday in holidays]


@router.post("/holidays", response_model=HolidayResponse, status_code=status.HTTP_201_CREATED)
async def create_holiday(
    payload: HolidayCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("sla_policies.manage"))],
    service: Annotated[SlaPolicyService, Depends(get_sla_policy_service)],
) -> HolidayResponse:
    holiday = await service.create_holiday(
        company_id=auth.company_id,
        name=payload.name,
        on_date=payload.date,
        recurs_annually=payload.recurs_annually,
        actor_user_id=auth.user_id,
    )
    return _to_holiday_response(holiday)


@router.patch("/holidays/{holiday_id}", response_model=HolidayResponse)
async def update_holiday(
    holiday_id: UUID,
    payload: HolidayUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("sla_policies.manage"))],
    service: Annotated[SlaPolicyService, Depends(get_sla_policy_service)],
) -> HolidayResponse:
    holiday = await service.update_holiday(
        company_id=auth.company_id,
        holiday_id=holiday_id,
        name=payload.name,
        on_date=payload.date,
        recurs_annually=payload.recurs_annually,
        actor_user_id=auth.user_id,
    )
    return _to_holiday_response(holiday)


@router.delete("/holidays/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holiday(
    holiday_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("sla_policies.manage"))],
    service: Annotated[SlaPolicyService, Depends(get_sla_policy_service)],
) -> None:
    await service.delete_holiday(
        company_id=auth.company_id, holiday_id=holiday_id, actor_user_id=auth.user_id
    )
