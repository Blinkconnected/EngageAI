"""Wire shapes for the connection wizard.

Everything here is channel-agnostic on purpose. The console renders a step
from ``kind`` and a capability list from ``states``; nothing it receives names
a channel except as an opaque identifier it passes back. That is what lets a
new connector appear in the wizard with no frontend change at all.

Copy travels as **keys**, never as sentences. A server that sends English
prose sends something that can never be Arabic, and this product ships both.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CapabilityStateResponse(BaseModel):
    capability: str
    available: bool
    #: A code the console translates — ``platform_app_not_configured`` and
    #: friends. Never a sentence.
    reason: str | None = None


class ConnectorProfileResponse(BaseModel):
    """One connectable channel, as this installation can offer it."""

    channel_type: str
    #: Everything the connector could ever do, so the console can show what a
    #: channel is capable of before anything is configured.
    declares: list[str]
    states: list[CapabilityStateResponse]
    #: False when neither consent nor a form is available here — the console
    #: shows it greyed with the reason rather than hiding it, since a channel
    #: that silently vanishes looks like one Blink Engage does not support.
    connectable: bool


class ConnectionTemplateResponse(BaseModel):
    key: str
    channel_types: list[str]
    title_key: str
    description_key: str
    recommended: bool


class CatalogResponse(BaseModel):
    connectors: list[ConnectorProfileResponse]
    templates: list[ConnectionTemplateResponse]


class FieldResponse(BaseModel):
    """One input the console renders without knowing what it means."""

    name: str
    kind: str
    label_key: str
    required: bool
    help_key: str | None = None
    placeholder: str | None = None
    options: list[list[str]] = Field(default_factory=list)
    #: Text to show with a copy button — a command to paste into a provider's
    #: bot, a URL to paste into a dashboard. Present exactly when the customer
    #: has to do something outside Blink Engage, which is the moment a wizard
    #: usually loses them.
    copyable: str | None = None


class ResourceResponse(BaseModel):
    id: str
    label: str
    group_key: str | None = None
    detail: dict[str, str] = Field(default_factory=dict)
    #: Set when it cannot be chosen. Sent rather than filtered out: a customer
    #: who cannot find their page assumes the product is broken.
    unavailable_reason: str | None = None


class FixResponse(BaseModel):
    kind: str
    action_id: str | None = None
    instructions_key: str | None = None


class CheckResponse(BaseModel):
    code: str
    #: ``ok`` | ``warn`` | ``fail``. Only ``fail`` blocks — a warning that
    #: blocked would train customers to click past the checklist.
    level: str
    channel_type: str
    params: dict[str, str] = Field(default_factory=dict)
    fix: FixResponse | None = None


class StepResponse(BaseModel):
    id: str
    #: How to render it. The console switches on this and never on the
    #: channel — six values cover every connector and every one planned.
    kind: str
    title_key: str
    automatic: bool
    state: str


class SessionResponse(BaseModel):
    """The whole wizard, as the console needs it.

    One response rather than a call per step: the console re-renders from
    this after every action, so a refresh mid-flow lands exactly where the
    customer left off.
    """

    session_id: str
    channel_types: list[str]
    template_key: str | None
    using_oauth: bool
    completed: bool
    steps: list[StepResponse]
    current_step: StepResponse
    #: Populated for a ``form`` step.
    fields: list[FieldResponse] = Field(default_factory=list)
    #: Populated for a ``resource_picker`` step, grouped by the connector's
    #: own group key so a template's three kinds read as three lists.
    resources: list[ResourceResponse] = Field(default_factory=list)
    #: Populated for a ``checklist`` step.
    checks: list[CheckResponse] = Field(default_factory=list)
    #: Where to send the customer to consent, for an ``oauth_redirect`` step.
    authorize_url: str | None = None


class StartSessionRequest(BaseModel):
    """Either a single channel or a template, never both."""

    channel_type: str | None = None
    template_key: str | None = None


class AdvanceRequest(BaseModel):
    """Whatever the live step asked for.

    Deliberately open: the step decides what an answer means, so typing this
    per step kind would put the flow's shape into the API surface, where
    changing a derivation becomes a breaking change.
    """

    payload: dict[str, Any] = Field(default_factory=dict)


class ConnectedChannelResponse(BaseModel):
    id: str
    channel_type: str
    display_name: str


class ConnectResultResponse(BaseModel):
    """What was created. Plural because a template makes several."""

    channels: list[ConnectedChannelResponse]


__all__ = [
    "AdvanceRequest",
    "CapabilityStateResponse",
    "CatalogResponse",
    "CheckResponse",
    "ConnectResultResponse",
    "ConnectedChannelResponse",
    "ConnectionTemplateResponse",
    "ConnectorProfileResponse",
    "FieldResponse",
    "FixResponse",
    "ResourceResponse",
    "SessionResponse",
    "StartSessionRequest",
    "StepResponse",
]
