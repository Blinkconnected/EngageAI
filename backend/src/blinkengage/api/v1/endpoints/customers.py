from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from blinkengage.api.deps import get_customer_service, require_permission
from blinkengage.api.schemas.customer import (
    CustomerCreateRequest,
    CustomerResponse,
    CustomerUpdateRequest,
)
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.application.services.customer_service import CustomerService
from blinkengage.core.auth_context import AuthContext
from blinkengage.infrastructure.database.models.customer import Customer

router = APIRouter(prefix="/customers", tags=["customers"])


def _to_response(customer: Customer) -> CustomerResponse:
    return CustomerResponse(
        id=customer.id,
        full_name=customer.full_name,
        email=customer.email,
        phone=customer.phone,
        notes=customer.notes,
        custom_fields=customer.custom_fields,
        tags=sorted(ct.tag.name for ct in customer.customer_tags),
        created_at=customer.created_at,
        updated_at=customer.updated_at,
    )


@router.get("", response_model=Page[CustomerResponse])
async def list_customers(
    auth: Annotated[AuthContext, Depends(require_permission("customers.read"))],
    service: Annotated[CustomerService, Depends(get_customer_service)],
    page_params: Annotated[PageParams, Depends()],
    search: Annotated[str | None, Query(max_length=255)] = None,
) -> Page[CustomerResponse]:
    items, total = await service.list_customers(
        company_id=auth.company_id,
        offset=page_params.offset,
        limit=page_params.page_size,
        search=search,
    )
    return Page(
        items=[_to_response(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("customers.manage"))],
    service: Annotated[CustomerService, Depends(get_customer_service)],
) -> CustomerResponse:
    customer = await service.create(
        company_id=auth.company_id,
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        notes=payload.notes,
        custom_fields=payload.custom_fields,
        tag_names=payload.tags,
    )
    return _to_response(customer)


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("customers.read"))],
    service: Annotated[CustomerService, Depends(get_customer_service)],
) -> CustomerResponse:
    customer = await service.get(company_id=auth.company_id, customer_id=customer_id)
    return _to_response(customer)


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: UUID,
    payload: CustomerUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("customers.manage"))],
    service: Annotated[CustomerService, Depends(get_customer_service)],
) -> CustomerResponse:
    customer = await service.update(
        company_id=auth.company_id,
        customer_id=customer_id,
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        notes=payload.notes,
        custom_fields=payload.custom_fields,
        tag_names=payload.tags,
    )
    return _to_response(customer)


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    customer_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("customers.manage"))],
    service: Annotated[CustomerService, Depends(get_customer_service)],
) -> None:
    await service.delete(company_id=auth.company_id, customer_id=customer_id)
