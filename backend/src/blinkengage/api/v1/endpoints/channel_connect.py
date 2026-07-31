"""The connection wizard — `/api/v1/channel-connect/*`.

Five endpoints that connect any channel. **Not one of them names a channel**:
the catalog reports what connectors say about themselves, and a session is
advanced by answering whatever step the flow derived. Adding Slack changes
nothing in this file, which is the entire point of the connector framework
(see `docs/architecture/channel-connectors.md`).

Tenant-scoped, gated on `channels.manage` — a customer connects their own
channels. This is deliberately *not* platform territory: it is the tenant's
WhatsApp number and their Facebook Page, and requiring a platform operator to
connect them for every customer is the opposite of a two-minute setup.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from blinkengage.api.deps import (
    get_channel_config_service,
    get_channel_connect_service,
    require_permission,
)
from blinkengage.api.schemas.channel_connect import (
    AdvanceRequest,
    CapabilityStateResponse,
    CatalogResponse,
    CheckResponse,
    ConnectedChannelResponse,
    ConnectionTemplateResponse,
    ConnectorProfileResponse,
    ConnectResultResponse,
    FieldResponse,
    FixResponse,
    ResourceResponse,
    SessionResponse,
    StartSessionRequest,
    StepResponse,
)
from blinkengage.application.services.channel_config_service import ChannelConfigService
from blinkengage.application.services.channel_connect_service import (
    ChannelConnectService,
    ConnectSession,
)
from blinkengage.core.auth_context import AuthContext
from blinkengage.domain.connection_templates import TEMPLATES
from blinkengage.domain.connectors import StepKind
from blinkengage.infrastructure.connectors.registry import ConnectorRegistry

router = APIRouter(prefix="/channel-connect", tags=["channels"])


@router.get("/catalog", response_model=CatalogResponse)
async def catalog(
    _auth: Annotated[AuthContext, Depends(require_permission("channels.read"))],
    service: Annotated[ChannelConnectService, Depends(get_channel_connect_service)],
) -> CatalogResponse:
    """What can be connected here, and how.

    Capability negotiation rather than feature flags: an installation with no
    provider app reports OAuth unavailable with a reason, and the console
    renders the manual path as primary. Same response shape either way, so
    there is no second code path to keep in step.
    """
    return CatalogResponse(
        connectors=[
            ConnectorProfileResponse(
                channel_type=profile.channel_type,
                declares=sorted(c.value for c in profile.declares),
                states=[
                    CapabilityStateResponse(
                        capability=state.capability.value,
                        available=state.available,
                        reason=state.reason,
                    )
                    for state in profile.states
                ],
                connectable=profile.connectable,
            )
            for profile in service.catalog()
        ],
        templates=[
            ConnectionTemplateResponse(
                key=template.key,
                channel_types=list(template.channel_types),
                title_key=template.title_key,
                description_key=template.description_key,
                recommended=template.recommended,
            )
            for template in TEMPLATES
            # Hidden when nothing in the bundle can be connected here — a
            # template offering three channels that all need an app this
            # installation lacks is a dead end wearing a recommendation.
            if any(
                p.connectable
                for p in service.catalog()
                if p.channel_type in template.channel_types
            )
        ],
    )


async def _render(
    session: ConnectSession, service: ChannelConnectService
) -> SessionResponse:
    """The whole wizard state, after whatever just happened.

    Assembled here rather than in the service so the service stays free of
    wire concerns — and so the console can re-render from one response
    instead of stitching several together.
    """
    flow = service.steps(session)
    current = service.current(session)

    fields: list[FieldResponse] = []
    resources: list[ResourceResponse] = []
    authorize_url: str | None = None

    if current.kind is StepKind.FORM:
        connector = ConnectorRegistry.get(session.primary)
        if connector is not None:
            fields = [
                FieldResponse(
                    name=f.name,
                    kind=f.kind,
                    label_key=f.label_key,
                    required=f.required,
                    help_key=f.help_key,
                    placeholder=f.placeholder,
                    options=[list(option) for option in f.options],
                    copyable=f.copyable,
                )
                for f in connector.credential_fields()
            ]
    elif current.kind is StepKind.RESOURCE_PICKER:
        found = await service.discover(session)
        resources = [
            ResourceResponse(
                id=r.id,
                label=r.label,
                group_key=r.group_key,
                detail=r.detail,
                unavailable_reason=r.unavailable_reason,
            )
            for group in found.values()
            for r in group
        ]
    elif current.kind is StepKind.OAUTH_REDIRECT:
        connector = ConnectorRegistry.get(session.primary)
        if connector is not None:
            authorize_url = await connector.authorize_url(
                state=session.id, context=service.context
            )

    return SessionResponse(
        session_id=session.id,
        channel_types=list(session.channel_types),
        template_key=session.template_key,
        using_oauth=session.using_oauth,
        completed=session.completed,
        steps=[
            StepResponse(
                id=step.id.value,
                kind=step.kind.value,
                title_key=step.title_key,
                automatic=step.automatic,
                state=(
                    "complete"
                    if index < session.step_index
                    else "active"
                    if index == session.step_index
                    else "pending"
                ),
            )
            for index, step in enumerate(flow)
        ],
        current_step=StepResponse(
            id=current.id.value,
            kind=current.kind.value,
            title_key=current.title_key,
            automatic=current.automatic,
            state="active",
        ),
        fields=fields,
        resources=resources,
        checks=[
            CheckResponse(
                code=check["code"],
                level=check["level"],
                channel_type=check["channel_type"],
                params=check.get("params") or {},
                fix=FixResponse(**check["fix"]) if check.get("fix") else None,
            )
            for check in session.checks
        ],
        authorize_url=authorize_url,
    )


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def start_session(
    payload: StartSessionRequest,
    auth: Annotated[AuthContext, Depends(require_permission("channels.manage"))],
    service: Annotated[ChannelConnectService, Depends(get_channel_connect_service)],
) -> SessionResponse:
    session = await service.start(
        company_id=auth.company_id,
        user_id=auth.user_id,
        channel_type=payload.channel_type,
        template_key=payload.template_key,
    )
    return await _render(session, service)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    auth: Annotated[AuthContext, Depends(require_permission("channels.manage"))],
    service: Annotated[ChannelConnectService, Depends(get_channel_connect_service)],
) -> SessionResponse:
    """Re-read the flow.

    Exists so a refresh, or a return from a provider's consent screen, lands
    exactly where the customer left off rather than starting over.
    """
    session = await service.get(session_id, company_id=auth.company_id)
    return await _render(session, service)


@router.post("/sessions/{session_id}/advance", response_model=SessionResponse)
async def advance_session(
    session_id: str,
    payload: AdvanceRequest,
    auth: Annotated[AuthContext, Depends(require_permission("channels.manage"))],
    service: Annotated[ChannelConnectService, Depends(get_channel_connect_service)],
) -> SessionResponse:
    """Answer the live step.

    One endpoint for every step, because the step decides what an answer
    means. An endpoint per step kind would put the flow's shape into the API
    surface, where changing a derivation becomes a breaking change.
    """
    session = await service.get(session_id, company_id=auth.company_id)
    session = await service.advance(session, payload.payload)
    return await _render(session, service)


@router.post("/sessions/{session_id}/connect", response_model=ConnectResultResponse)
async def finish_session(
    session_id: str,
    auth: Annotated[AuthContext, Depends(require_permission("channels.manage"))],
    service: Annotated[ChannelConnectService, Depends(get_channel_connect_service)],
    channels: Annotated[ChannelConfigService, Depends(get_channel_config_service)],
) -> ConnectResultResponse:
    """Make it real, then register the webhook.

    In that order for a reason worth stating: the callback URL contains the
    channel's id, and the id does not exist until the row is written. A
    connector asked to register during ``connect`` could only invent one, and
    an invented id is a URL the provider delivers to until somebody notices
    it has been answering 404 for a month.
    """
    session = await service.get(session_id, company_id=auth.company_id)
    made = await service.connect(session)

    created: list[ConnectedChannelResponse] = []
    for connection in made:
        config = await channels.create(
            company_id=auth.company_id,
            channel_type=connection.channel_type,
            display_name=connection.display_name,
            credentials=connection.credentials,
            webhook_secret=connection.webhook_secret,
            actor_user_id=auth.user_id,
        )
        connector = ConnectorRegistry.get(connection.channel_type)
        if connector is not None:
            repair = await connector.register_webhook(
                callback_url=channels.webhook_url_for(config.id),
                credentials=connection.credentials,
                context=service.context,
            )
            # A registration that produced a secret must persist it *before*
            # anything verifies a signature against the column, or every
            # inbound message fails a check nobody can see failing.
            if repair.repaired and repair.webhook_secret:
                await channels.set_webhook_secret(
                    company_id=auth.company_id,
                    channel_config_id=config.id,
                    webhook_secret=repair.webhook_secret,
                )
        created.append(
            ConnectedChannelResponse(
                id=str(config.id),
                channel_type=config.channel_type,
                display_name=config.display_name,
            )
        )

    return ConnectResultResponse(channels=created)


__all__ = ["router"]
