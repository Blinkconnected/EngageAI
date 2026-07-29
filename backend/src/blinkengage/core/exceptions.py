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
    AmbiguousPricingConfigurationError,
    AuthenticationError,
    AuthorizationError,
    ConversationAlreadyClaimedError,
    DomainError,
    EmailNotVerifiedError,
    EntityAlreadyExistsError,
    EntityNotFoundError,
    ErpNotConfiguredError,
    InvoiceNotPayableError,
    InvoiceStateError,
    MetricNotPriceableError,
    PaymentProcessingError,
    PricingConcurrentEditError,
    PricingNotConfiguredError,
    PricingRangeOverlapError,
    RateAlreadyEffectiveError,
    RefundNotPermittedError,
    SystemProfileNotPriceableError,
)
from blinkengage.domain.invoicing import InvalidInvoiceTransitionError

_STATUS_MAP: dict[type[Exception], int] = {
    EmailNotVerifiedError: status.HTTP_403_FORBIDDEN,
    EntityNotFoundError: status.HTTP_404_NOT_FOUND,
    EntityAlreadyExistsError: status.HTTP_409_CONFLICT,
    AuthenticationError: status.HTTP_401_UNAUTHORIZED,
    AuthorizationError: status.HTTP_403_FORBIDDEN,
    AiNotConfiguredError: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErpNotConfiguredError: status.HTTP_503_SERVICE_UNAVAILABLE,
    PricingNotConfiguredError: status.HTTP_503_SERVICE_UNAVAILABLE,
    AmbiguousPricingConfigurationError: status.HTTP_409_CONFLICT,
    MetricNotPriceableError: status.HTTP_409_CONFLICT,
    InvoiceStateError: status.HTTP_409_CONFLICT,
    InvalidInvoiceTransitionError: status.HTTP_409_CONFLICT,
    InvoiceNotPayableError: status.HTTP_409_CONFLICT,
    PaymentProcessingError: status.HTTP_409_CONFLICT,
    RefundNotPermittedError: status.HTTP_409_CONFLICT,
    PricingRangeOverlapError: status.HTTP_409_CONFLICT,
    PricingConcurrentEditError: status.HTTP_409_CONFLICT,
    RateAlreadyEffectiveError: status.HTTP_409_CONFLICT,
    SystemProfileNotPriceableError: status.HTTP_409_CONFLICT,
    ConversationAlreadyClaimedError: status.HTTP_409_CONFLICT,
    AgentMissingRequiredSkillError: status.HTTP_403_FORBIDDEN,
}


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Walks the MRO rather than looking up `type(exc)` exactly, so a
    # subclass inherits its parent's mapping. A specific error like
    # `CompanyNotActiveError(AuthenticationError)` otherwise fell through
    # to a generic 400 despite its parent mapping to 401 — the more
    # precise the exception, the more wrong the status code became.
    status_code = next(
        (_STATUS_MAP[klass] for klass in type(exc).__mro__ if klass in _STATUS_MAP),
        status.HTTP_400_BAD_REQUEST,
    )
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
