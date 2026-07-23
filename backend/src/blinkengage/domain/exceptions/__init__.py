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
