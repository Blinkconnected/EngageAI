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
