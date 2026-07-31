"""Installation settings — `/api/v1/platform/settings/*`.

Gated at registration by ``get_platform_auth``: these are settings for
the installation as a whole, and a tenant administrator has no business
reading — let alone changing — the relay every company's mail goes out
through.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.api.deps import (
    deny_read_only_writes,
    enforce_platform_test_connection_rate_limit,
    get_db_session,
    get_platform_auth,
    get_platform_settings_service,
)
from blinkengage.api.schemas.platform_settings import (
    MailSettingsRequest,
    MailSettingsResponse,
    TestMailRequest,
    TestMailResponse,
)
from blinkengage.application.services.platform_settings_service import (
    PlatformSettingsService,
)
from blinkengage.core.auth_context import PlatformContext
from blinkengage.core.logging import get_logger
from blinkengage.domain.mail import MailConfig
from blinkengage.infrastructure.email.mailer import MailDeliveryError, send_with_config
from blinkengage.infrastructure.repositories.user_repository import UserRepository

logger = get_logger(__name__)

router = APIRouter(
    prefix="/platform/settings",
    tags=["platform-settings"],
    # Both gates at construction: platform authority, and — for anything
    # that is not a GET — an operator who may change things. A route added
    # to this router inherits both rather than shipping unguarded.
    dependencies=[Depends(get_platform_auth), Depends(deny_read_only_writes)],
)


async def _view(service: PlatformSettingsService) -> MailSettingsResponse:
    config, password_set, updated_by, updated_at = await service.mail_view()
    return MailSettingsResponse(
        host=config.host,
        port=config.port,
        security=config.security,
        from_address=config.from_address,
        from_name=config.from_name,
        username=config.username,
        password_set=password_set,
        timeout_seconds=config.timeout_seconds,
        customised=await service.is_customised(),
        updated_by_email=updated_by,
        updated_at=updated_at,
    )


@router.get("/mail", response_model=MailSettingsResponse)
async def get_mail_settings(
    service: Annotated[PlatformSettingsService, Depends(get_platform_settings_service)],
) -> MailSettingsResponse:
    """The relay the product sends from.

    Never includes the password — see ``password_set``.
    """
    return await _view(service)


@router.put("/mail", response_model=MailSettingsResponse)
async def update_mail_settings(
    payload: MailSettingsRequest,
    service: Annotated[PlatformSettingsService, Depends(get_platform_settings_service)],
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MailSettingsResponse:
    user = await UserRepository(session).get_by_id(platform.user_id)
    await service.save_mail_config(
        MailConfig(
            host=payload.host.strip(),
            port=payload.port,
            security=payload.security,
            from_address=str(payload.from_address),
            from_name=payload.from_name.strip(),
            username=payload.username.strip() if payload.username else None,
            password=payload.password,
            timeout_seconds=payload.timeout_seconds,
        ),
        actor_email=user.email if user else None,
    )
    return await _view(service)


@router.delete("/mail", response_model=MailSettingsResponse)
async def reset_mail_settings(
    service: Annotated[PlatformSettingsService, Depends(get_platform_settings_service)],
) -> MailSettingsResponse:
    """Drops the override and falls back to the environment.

    The way back for an operator who has misconfigured the relay from
    this form — a safer instruction than "guess what the environment
    variables were".
    """
    await service.reset_mail_config()
    return await _view(service)


@router.post(
    "/mail/test",
    response_model=TestMailResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(enforce_platform_test_connection_rate_limit)],
)
async def test_mail_settings(
    payload: TestMailRequest,
    request: Request,
    service: Annotated[PlatformSettingsService, Depends(get_platform_settings_service)],
) -> TestMailResponse:
    """Sends a real message using the configuration currently in force.

    Deliberately a real send rather than a connection check: a relay
    that accepts a TCP connection and authenticates can still reject the
    envelope sender, and "connected successfully" followed by silent
    non-delivery is worse than no test at all.

    Rate-limited, like the channel and ERP connection tests: this makes
    the server originate an outbound connection to an operator-chosen
    host and port.

    Returns 200 with ``delivered: false`` on failure rather than raising.
    The relay's refusal is the *answer* to this request, not an error in
    serving it, and the operator needs the message the relay gave.
    """
    config = await service.mail_config()
    try:
        await send_with_config(
            config,
            to_address=str(payload.to_address),
            subject="Blink Engage — test message",
            body=(
                "This is a test message from your Blink Engage installation.\n\n"
                f"Relay: {config.host}:{config.port} ({config.security.value})\n"
                f"Sent as: {config.from_name} <{config.from_address}>\n\n"
                "If you received this, outbound mail is working."
            ),
        )
    except MailDeliveryError as exc:
        logger.warning("platform_mail_test_failed", host=config.host, error=str(exc))
        return TestMailResponse(delivered=False, detail=str(exc))
    return TestMailResponse(delivered=True)


__all__ = ["router"]
