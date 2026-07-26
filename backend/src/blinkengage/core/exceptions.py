"""Translation of domain exceptions to HTTP responses.

Keeps FastAPI/HTTP concerns out of the domain layer: domain code raises
``DomainError`` subclasses, and this module maps them to status codes at
the API boundary.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from blinkengage.domain.exceptions import (
    AgentMissingRequiredSkillError,
    AiNotConfiguredError,
    AuthenticationError,
    AuthorizationError,
    ConversationAlreadyClaimedError,
    DomainError,
    EntityAlreadyExistsError,
    EntityNotFoundError,
    ErpNotConfiguredError,
)

_STATUS_MAP: dict[type[Exception], int] = {
    EntityNotFoundError: status.HTTP_404_NOT_FOUND,
    EntityAlreadyExistsError: status.HTTP_409_CONFLICT,
    AuthenticationError: status.HTTP_401_UNAUTHORIZED,
    AuthorizationError: status.HTTP_403_FORBIDDEN,
    AiNotConfiguredError: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErpNotConfiguredError: status.HTTP_503_SERVICE_UNAVAILABLE,
    ConversationAlreadyClaimedError: status.HTTP_409_CONFLICT,
    AgentMissingRequiredSkillError: status.HTTP_403_FORBIDDEN,
}


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    status_code = _STATUS_MAP.get(type(exc), status.HTTP_400_BAD_REQUEST)
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
