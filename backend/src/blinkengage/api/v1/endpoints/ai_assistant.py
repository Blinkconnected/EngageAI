"""Talking to the Company Admin assistant.

See ``docs/architecture/company-ai-brain.md`` (Phase 4G-2c).

Wiring, deliberately thin. Everything that decides anything already exists:
``AdminAssistant`` orchestrates, ``ToolExecutor`` authorises and parks,
``publication_gate`` decides authority. This module authenticates the
principal, hands the runtime a message, and shapes the reply.

**There is no confirmation here.** A publish request comes back as a parked
action id and stops. Approving it is a separate authenticated request to
``/ai/actions/{id}/confirm`` — the asymmetry ``ai_actions`` already exists to
express, and the reason a model cannot approve its own proposal. No flag on
this endpoint shortens that path, because no such flag exists.

**The client chooses nothing but the words.** Not the provider, not the
model, not the tools, and not who it is. Tool availability comes from
``registry.definitions_for(auth.permissions)`` inside the runtime; identity
comes from the token. The request body carries a message, a session and an
optional idempotency key, and ``extra="forbid"`` refuses everything else —
so an attempt to supply a ``company_id`` is a 422 rather than a field
somebody has to remember to ignore.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from blinkengage.api.deps import get_admin_assistant, get_tool_services, require_permission
from blinkengage.application.ai_tools import ToolServices
from blinkengage.application.assistant import (
    AdminAssistant,
    AssistantNotAuthorized,
    AssistantProviderError,
    AssistantUnavailable,
    MalformedAssistantResponse,
)
from blinkengage.core.auth_context import AuthContext
from blinkengage.core.correlation import get_correlation_id
from blinkengage.core.logging import get_logger
from blinkengage.domain.brain.retrieval_policy import CrossTenantAccessError

logger = get_logger(__name__)

router = APIRouter(prefix="/ai/assistant", tags=["ai"])


class AssistantMessageRequest(BaseModel):
    #: ``extra="forbid"`` is the tenant boundary at the HTTP edge. A body
    #: carrying ``company_id`` is refused outright rather than accepted and
    #: quietly overridden — a caller who believes they acted as another
    #: company should be told they did not.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=4000)
    #: Groups turns into one conversation. Client-chosen because the client
    #: knows which window this belongs to; it is scoped by company on read,
    #: so naming somebody else's session reveals nothing.
    session_id: UUID
    idempotency_key: str | None = Field(default=None, max_length=200)


class AssistantMessageResponse(BaseModel):
    turn_id: UUID
    session_id: UUID
    reply: str
    #: Record pointers the answer actually used. Never model-authored.
    citations: list[dict[str, Any]]
    #: Actions awaiting a human. Confirmed through ``/ai/actions/{id}/confirm``
    #: and nowhere else.
    pending_action_ids: list[str]
    model_identifier: str | None
    #: True when this came from a stored turn rather than the model, so a
    #: client can tell a replay from a fresh answer.
    replayed: bool


@router.post("/messages", response_model=AssistantMessageResponse)
async def send_message(
    payload: AssistantMessageRequest,
    auth: Annotated[AuthContext, Depends(require_permission("ai.use"))],
    assistant: Annotated[AdminAssistant, Depends(get_admin_assistant)],
    services: Annotated[ToolServices, Depends(get_tool_services)],
) -> AssistantMessageResponse:
    """One turn with the admin assistant.

    ``auth`` is the only source of identity. It is not merged with anything
    from the body, because there is nothing in the body to merge.
    """
    try:
        result = await assistant.respond(
            auth=auth,
            services=services,
            user_message=payload.message,
            session_id=payload.session_id,
            idempotency_key=payload.idempotency_key,
            correlation_id=get_correlation_id(),
        )
    except AssistantNotAuthorized as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AssistantUnavailable as exc:
        # Configuration, not a transient fault: no provider is set up for
        # this company or the platform.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI assistant is not configured for this workspace.",
        ) from exc
    except (AssistantProviderError, MalformedAssistantResponse) as exc:
        # The provider's own message may quote a prompt, a payload or a key.
        # It is logged, never returned.
        logger.warning("assistant_turn_failed", company_id=str(auth.company_id), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The AI assistant could not complete this request.",
        ) from exc
    except CrossTenantAccessError as exc:
        # A row from another company reached a boundary. Never an answer, and
        # never a message that confirms the other tenant's record exists.
        logger.error("assistant_cross_tenant_access", company_id=str(auth.company_id))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The request could not be completed.",
        ) from exc

    return AssistantMessageResponse(
        turn_id=result.turn_id,
        session_id=result.session_id,
        reply=result.reply,
        citations=list(result.citations),
        pending_action_ids=list(result.pending_action_ids),
        model_identifier=result.model_identifier,
        replayed=result.replayed,
    )
