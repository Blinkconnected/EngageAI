from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from blinkengage.api.deps import get_routing_rule_service, require_permission
from blinkengage.api.schemas.queue import (
    RoutingRuleCreateRequest,
    RoutingRuleResponse,
    RoutingRuleUpdateRequest,
)
from blinkengage.application.services.routing_rule_service import RoutingRuleService
from blinkengage.core.auth_context import AuthContext

router = APIRouter(prefix="/routing-rules", tags=["routing-rules"])


@router.get("", response_model=list[RoutingRuleResponse])
async def list_routing_rules(
    auth: Annotated[AuthContext, Depends(require_permission("queues.read"))],
    service: Annotated[RoutingRuleService, Depends(get_routing_rule_service)],
) -> list[RoutingRuleResponse]:
    rules = await service.list_rules(company_id=auth.company_id)
    return [RoutingRuleResponse.model_validate(rule) for rule in rules]


@router.post("", response_model=RoutingRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_routing_rule(
    payload: RoutingRuleCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("queues.manage"))],
    service: Annotated[RoutingRuleService, Depends(get_routing_rule_service)],
) -> RoutingRuleResponse:
    rule = await service.create(
        company_id=auth.company_id,
        priority=payload.priority,
        conditions=payload.conditions,
        target_queue_id=payload.target_queue_id,
        actor_user_id=auth.user_id,
    )
    return RoutingRuleResponse.model_validate(rule)


@router.get("/{rule_id}", response_model=RoutingRuleResponse)
async def get_routing_rule(
    rule_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("queues.read"))],
    service: Annotated[RoutingRuleService, Depends(get_routing_rule_service)],
) -> RoutingRuleResponse:
    rule = await service.get(company_id=auth.company_id, rule_id=rule_id)
    return RoutingRuleResponse.model_validate(rule)


@router.patch("/{rule_id}", response_model=RoutingRuleResponse)
async def update_routing_rule(
    rule_id: UUID,
    payload: RoutingRuleUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("queues.manage"))],
    service: Annotated[RoutingRuleService, Depends(get_routing_rule_service)],
) -> RoutingRuleResponse:
    rule = await service.update(
        company_id=auth.company_id,
        rule_id=rule_id,
        priority=payload.priority,
        conditions=payload.conditions,
        target_queue_id=payload.target_queue_id,
        is_active=payload.is_active,
        actor_user_id=auth.user_id,
    )
    return RoutingRuleResponse.model_validate(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_routing_rule(
    rule_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("queues.manage"))],
    service: Annotated[RoutingRuleService, Depends(get_routing_rule_service)],
) -> None:
    await service.delete(company_id=auth.company_id, rule_id=rule_id, actor_user_id=auth.user_id)
