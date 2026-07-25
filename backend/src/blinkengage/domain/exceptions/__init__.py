"""Domain-level exceptions.

These are raised by the domain/application layers and translated to HTTP
responses at the API boundary — the domain layer itself has no knowledge of
HTTP or FastAPI.
"""


class DomainError(Exception):
    """Base class for all domain-level errors."""


class EntityNotFoundError(DomainError):
    def __init__(self, entity_name: str, identifier: object) -> None:
        self.entity_name = entity_name
        self.identifier = identifier
        super().__init__(f"{entity_name} with id={identifier!r} was not found")


class EntityAlreadyExistsError(DomainError):
    def __init__(self, entity_name: str, field: str, value: object) -> None:
        self.entity_name = entity_name
        self.field = field
        self.value = value
        super().__init__(f"{entity_name} with {field}={value!r} already exists")


class AuthenticationError(DomainError):
    """Raised on invalid credentials or invalid/expired tokens."""


class AuthorizationError(DomainError):
    """Raised when an authenticated principal lacks a required permission."""


class InvalidChannelTypeError(DomainError):
    """Raised when a ``channel_type`` isn't registered in
    ``infrastructure.channels.registry.ChannelRegistry`` — an invalid
    client-supplied value, not a missing resource, so it falls through to
    the generic 400 in ``core/exceptions.py`` rather than 404."""

    def __init__(self, channel_type: str) -> None:
        self.channel_type = channel_type
        super().__init__(f"Unknown channel type: {channel_type!r}")


class InvalidChannelCredentialsError(DomainError):
    """Raised when a channel type has a known required-fields schema
    (``infrastructure.channels.credential_schemas``) and the supplied
    ``credentials`` dict doesn't satisfy it — a client-input validation
    failure, not a missing resource, so it falls through to the generic
    400 like ``InvalidChannelTypeError``. Channel types with no schema
    registered (not yet covered by Phase 1: Channel Experience) are left
    unvalidated at this layer, same as before."""

    def __init__(self, channel_type: str, detail: str) -> None:
        self.channel_type = channel_type
        self.detail = detail
        super().__init__(f"Invalid credentials for channel type {channel_type!r}: {detail}")


class InvalidSmsGatewayError(DomainError):
    """Raised when ``ChannelConfig.credentials["gateway"]`` isn't
    registered in ``infrastructure.channels.sms_gateway_registry.
    SmsGatewayRegistry`` — the inner plugin registry behind ``SmsProvider``
    (see ``docs/architecture/sms.md``). Same 400-by-default reasoning as
    ``InvalidChannelTypeError``."""

    def __init__(self, gateway_name: str) -> None:
        self.gateway_name = gateway_name
        super().__init__(f"Unknown SMS gateway: {gateway_name!r}")


class InvalidConversationStatusTransitionError(DomainError):
    """Raised on an illegal conversation status transition (e.g.
    ``closed`` -> ``pending`` directly, skipping ``open``) — see
    ``docs/architecture/conversations.md``."""

    def __init__(self, current: str, requested: str) -> None:
        self.current = current
        self.requested = requested
        super().__init__(f"Cannot transition conversation from {current!r} to {requested!r}")


class AttachmentValidationError(DomainError):
    """Raised when an uploaded attachment fails type/size validation."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)


class AttachmentNotLinkableError(DomainError):
    """Raised when a referenced attachment doesn't exist, belongs to a
    different conversation, or is already linked to another message."""

    def __init__(self, attachment_id: object) -> None:
        self.attachment_id = attachment_id
        super().__init__(f"Attachment {attachment_id!r} cannot be attached to this message")


class AiNotConfiguredError(DomainError):
    """Raised when an AI Engine feature is called but
    ``settings.ai_provider`` is ``"disabled"`` (the default) — a
    deployment/configuration state, not a missing resource, so it maps to
    503 rather than 404/400 in ``core/exceptions.py``. See
    ``docs/architecture/ai-engine.md``."""

    def __init__(self) -> None:
        super().__init__("AI features are not configured on this platform")


class ErpNotConfiguredError(DomainError):
    """Raised when an ERPNext-dependent action is requested for a company
    with no active ``ErpConfig`` — a deployment/configuration state, not
    a missing resource, so it maps to 503 like ``AiNotConfiguredError``.
    See ``docs/architecture/erp-integration.md``."""

    def __init__(self) -> None:
        super().__init__("ERPNext is not configured for this company")
