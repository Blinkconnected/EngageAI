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
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from blinkengage.api.deps import (
    get_channel_config_service,
    get_channel_connect_service,
    get_channel_diagnostics_service,
    get_connector_certification_service,
    require_permission,
)
from blinkengage.api.schemas.channel_connect import (
    AdvanceRequest,
    CapabilityStateResponse,
    CatalogResponse,
    CertificationReportResponse,
    CertificationResponse,
    CheckResponse,
    CompatibilityResponse,
    ConnectedChannelResponse,
    ConnectionTemplateResponse,
    ConnectorProfileResponse,
    ConnectResultResponse,
    DiagnosticReportResponse,
    DiagnosticResponse,
    DocumentationLinkResponse,
    FeatureSupportResponse,
    FieldResponse,
    ManifestResponse,
    RepairActionResponse,
    RepairResultResponse,
    ResourceResponse,
    ResourceSpecResponse,
    ScenarioResultResponse,
    SessionResponse,
    StartSessionRequest,
    StepResponse,
    VerificationSpecResponse,
    VersionInfoResponse,
)
from blinkengage.application.services.channel_config_service import ChannelConfigService
from blinkengage.application.services.channel_connect_service import (
    ChannelConnectService,
    ConnectSession,
)
from blinkengage.application.services.channel_diagnostics_service import (
    ChannelDiagnosticsService,
)
from blinkengage.application.services.connector_certification_service import (
    ConnectorCertificationService,
)
from blinkengage.core.auth_context import AuthContext
from blinkengage.domain.connection_templates import TEMPLATES
from blinkengage.domain.connector_manifest import ConnectorManifest
from blinkengage.domain.connectors import StepKind
from blinkengage.infrastructure.connectors.registry import ConnectorRegistry

router = APIRouter(prefix="/channel-connect", tags=["channels"])



def _manifest_response(manifest: ConnectorManifest) -> ManifestResponse:
    """A connector's own description, on the wire.

    A straight projection with no interpretation: anything this function
    decided rather than copied would be a decision the console could not see
    and a connector author could not change.
    """
    return ManifestResponse(
        channel_type=manifest.channel_type,
        name_key=manifest.name_key,
        description_key=manifest.description_key,
        category=manifest.category.value,
        icon=manifest.icon,
        capabilities=sorted(c.value for c in manifest.capabilities),
        auth_methods=[method.value for method in manifest.auth_methods],
        required_permissions=list(manifest.required_permissions),
        required_credentials=[
            FieldResponse(
                name=spec.name,
                kind=spec.kind,
                label_key=spec.label_key,
                required=spec.required,
                help_key=spec.help_key,
                placeholder=spec.placeholder,
                options=[list(option) for option in spec.options],
                copyable=spec.copyable,
            )
            for spec in manifest.required_credentials
        ],
        required_resources=[
            ResourceSpecResponse(
                key=spec.key,
                title_key=spec.title_key,
                empty_key=spec.empty_key,
                multiple=spec.multiple,
            )
            for spec in manifest.required_resources
        ],
        verification_steps=[
            VerificationSpecResponse(
                key=spec.key,
                title_key=spec.title_key,
                codes=[code.value for code in spec.codes],
            )
            for spec in manifest.verification_steps
        ],
        repair_actions=[
            RepairActionResponse(
                id=action.id,
                title_key=action.title_key,
                description_key=action.description_key,
                confirm=action.confirm,
                confirm_key=action.confirm_key,
                permission=action.permission,
                available_during_setup=action.available_during_setup,
            )
            for action in manifest.repair_actions
        ],
        supported_features=[
            FeatureSupportResponse(
                feature=support.feature.value,
                direction=support.direction.value,
                note_key=support.note_key,
            )
            for support in manifest.supported_features
        ],
        documentation=[
            DocumentationLinkResponse(key=link.key, url=link.url)
            for link in manifest.documentation
        ],
        maturity=manifest.maturity.value,
        versions=VersionInfoResponse(
            connector=manifest.versions.connector,
            api=manifest.versions.api,
            minimum_platform=manifest.versions.minimum_platform,
        ),
    )


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
                lifecycle=profile.lifecycle.value,
                warns=profile.warns,
                platform_supported=profile.platform_supported,
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
        manifests=[
            _manifest_response(connector.manifest)
            for connector in ConnectorRegistry.all()
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
                blocks=bool(check.get("blocks")),
                channel_type=check["channel_type"],
                params=check.get("params") or {},
                repair_action=check.get("repair_action"),
                instructions_key=check.get("instructions_key"),
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


@router.post(
    "/channels/{channel_config_id}/repair/{action_id}",
    response_model=RepairResultResponse,
)
async def repair_channel(
    channel_config_id: UUID,
    action_id: str,
    auth: Annotated[AuthContext, Depends(require_permission("channels.manage"))],
    service: Annotated[ChannelConnectService, Depends(get_channel_connect_service)],
    channels: Annotated[ChannelConfigService, Depends(get_channel_config_service)],
) -> RepairResultResponse:
    """Run a repair the connector declared.

    One endpoint for every repair on every channel, because the action is
    named by the manifest rather than by the route. A connector adding
    "refresh token" adds a ``RepairAction`` and a branch in its own
    ``repair``; the console grows a button and this file does not change —
    which is the difference between a repair framework and a list of repair
    endpoints.

    The action is checked against the manifest before anything runs. An
    undeclared action is refused rather than passed to the connector, so the
    set of things that can be invoked is exactly the set the manifest
    advertises.
    """
    config = await channels.get(company_id=auth.company_id, channel_config_id=channel_config_id)
    connector = ConnectorRegistry.get(config.channel_type)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{config.channel_type}' has no connector.",
        )
    declared = connector.manifest.repair(action_id)
    if declared is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{config.channel_type}' does not offer '{action_id}'.",
        )

    result = await connector.repair(
        action=action_id,
        credentials=dict(config.credentials),
        webhook_secret=config.webhook_secret,
        callback_url=channels.webhook_url_for(config.id),
        context=service.context,
    )
    if result.repaired:
        # Persisted before anything verifies against it. A secret the
        # provider has and the column does not means every inbound message
        # fails a signature check nobody can see failing.
        if result.webhook_secret:
            await channels.set_webhook_secret(
                company_id=auth.company_id,
                channel_config_id=config.id,
                webhook_secret=result.webhook_secret,
            )
        if result.credentials is not None:
            await channels.update(
                company_id=auth.company_id,
                channel_config_id=config.id,
                display_name=None,
                credentials=result.credentials,
                webhook_secret=None,
                is_active=None,
                actor_user_id=auth.user_id,
            )

    return RepairResultResponse(
        action_id=action_id,
        repaired=result.repaired,
        reason=result.reason,
    )


@router.get(
    "/channels/{channel_config_id}/diagnostics",
    response_model=DiagnosticReportResponse,
)
async def channel_diagnostics(
    channel_config_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("channels.read"))],
    channels: Annotated[ChannelConfigService, Depends(get_channel_config_service)],
    diagnostics: Annotated[
        ChannelDiagnosticsService, Depends(get_channel_diagnostics_service)
    ],
) -> DiagnosticReportResponse:
    """Everything known about one channel, in one call.

    Built for a support engineer with a customer on the phone: the answer to
    "why is this not working" without a database query, a log search and a
    guess. The connector asks the provider what only it can know; the
    platform contributes what it already recorded; anything nobody measured
    comes back ``unknown`` rather than absent, so the panel has the same rows
    for every channel.

    ``channels.read`` rather than ``manage``: diagnosing is looking, and a
    support engineer who can only look should still be able to answer the
    question.
    """
    channel = await channels.get(
        company_id=auth.company_id, channel_config_id=channel_config_id
    )
    report = await diagnostics.report(channel)
    return DiagnosticReportResponse(
        channel_type=report.channel_type,
        items=[
            DiagnosticResponse(
                key=item.key.value,
                status=item.status.value,
                value=item.value,
                detail_key=item.detail_key,
                params=item.params,
                measured_at=item.measured_at,
                repair_action=item.repair_action,
            )
            for item in report.items
        ],
        overall=report.worst.value,
    )


@router.post(
    "/channels/{channel_config_id}/certify",
    response_model=CertificationReportResponse,
)
async def certify_channel(
    channel_config_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("channels.manage"))],
    channels: Annotated[ChannelConfigService, Depends(get_channel_config_service)],
    certifier: Annotated[
        ConnectorCertificationService, Depends(get_connector_certification_service)
    ],
    target: str | None = None,
    include_mutating: bool = False,
) -> CertificationReportResponse:
    """Run the connector's scenarios against this channel and score them.

    ``channels.manage`` rather than ``read``, even though most of the run
    only observes: with a ``target`` it sends, and a permission that depended
    on a query parameter would be a permission nobody could reason about.

    **Nothing here messages a real customer.** Every scenario that would put
    something in front of a person is skipped unless ``target`` names where
    to send it — never guessed at, never aimed at the last person who wrote
    in. ``include_mutating`` is off by default for the mirror reason:
    disconnect, reconnect and token refresh change the channel's state with
    the provider, and a run that left a working channel in whatever state it
    finished in would be a diagnostic worse than the problem.

    The score is computed from what ran and cannot be supplied.
    """
    channel = await channels.get(
        company_id=auth.company_id, channel_config_id=channel_config_id
    )
    report = await certifier.run(
        channel, target=target, include_mutating=include_mutating
    )
    return CertificationReportResponse(
        channel_type=report.channel_type,
        results=[
            ScenarioResultResponse(
                kind=result.kind.value,
                outcome=result.outcome.value,
                duration_ms=result.duration_ms,
                detail_key=result.detail_key,
                params=result.params,
                diagnostics=result.diagnostics,
            )
            for result in report.results
        ],
        certification=CertificationResponse(
            score=report.certification.score,
            percent=report.certification.percent,
            grade=report.certification.grade.value,
            coverage=report.certification.coverage,
            passed=report.certification.passed,
            failed=report.certification.failed,
            warned=report.certification.warned,
            skipped=report.certification.skipped,
            not_supported=report.certification.not_supported,
        ),
        compatibility=CompatibilityResponse(
            platform_version=report.compatibility.platform_version,
            connector_version=report.compatibility.connector_version,
            provider_api_version=report.compatibility.provider_api_version,
            last_verified=report.compatibility.last_verified,
            supported_until=report.compatibility.supported_until,
        ),
        ran_at=report.ran_at,
        duration_ms=report.duration_ms,
    )


__all__ = ["router"]
