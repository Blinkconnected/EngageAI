"""Public, unauthenticated ERPNext webhook ingress. See
``docs/architecture/erp-integration.md``.

ERPNext's own Webhook doctype lets an administrator configure one
webhook per document event, POSTing the raw document JSON to a URL of
their choosing — there's no standardized request-signature scheme the
way WhatsApp/Messenger/Twilio have, so this project's own shared secret
is verified via a custom request header (``X-Webhook-Secret``) the
ERPNext admin configures alongside the URL. The route stays thin — all
orchestration (config lookup, secret verification, upsert) lives in
``ErpSyncService.record_webhook_payload``, the same shape
``WebhookIngestService.ingest`` already establishes for channel webhooks.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from blinkengage.api.deps import get_erp_sync_service
from blinkengage.application.services.erp_sync_service import ErpSyncService

router = APIRouter(prefix="/webhooks/erpnext", tags=["erp"])


@router.post("/{erp_config_id}/{doctype}", status_code=status.HTTP_204_NO_CONTENT)
async def receive_erpnext_webhook(
    erp_config_id: UUID,
    doctype: str,
    request: Request,
    service: Annotated[ErpSyncService, Depends(get_erp_sync_service)],
    x_webhook_secret: Annotated[str | None, Header()] = None,
) -> None:
    payload: dict[str, Any] = await request.json()
    await service.record_webhook_payload(
        erp_config_id=erp_config_id,
        doctype=doctype,
        payload=payload,
        webhook_secret=x_webhook_secret,
    )
