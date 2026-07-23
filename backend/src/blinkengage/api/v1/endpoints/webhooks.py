"""Generic, channel-agnostic webhook ingress — one route for every
provider. See ``docs/architecture/channels.md``: the route stays thin,
all orchestration (config lookup, provider construction, signature
verification, parsing, event publishing) lives in
``WebhookIngestService``.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from blinkengage.api.deps import get_webhook_ingest_service
from blinkengage.application.services.webhook_ingest_service import WebhookIngestService
from blinkengage.domain.channels import WebhookRequest

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/{channel_config_id}")
async def receive_webhook(
    channel_config_id: UUID,
    request: Request,
    service: Annotated[WebhookIngestService, Depends(get_webhook_ingest_service)],
) -> Response:
    body = await request.body()
    ack = await service.ingest(
        channel_config_id=channel_config_id,
        request=WebhookRequest(
            headers=dict(request.headers),
            body=body,
            query_params=dict(request.query_params),
        ),
    )
    return Response(status_code=ack.status_code, content=ack.body)
