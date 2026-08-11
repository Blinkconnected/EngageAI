"""Confirming (or refusing) what the AI proposed.

See ``docs/architecture/ai-tool-calling.md``.

There is no endpoint here for *running* a tool. Tools run inside a model
turn, through ``ToolExecutor``; the only thing exposed to a client is the
human decision on an action the executor refused to perform on its own.
That asymmetry is the point — a confirmation is the one step a model must
not be able to take, so it is the one step that has its own authenticated
request.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from blinkengage.api.deps import get_tool_context, get_tool_executor, require_permission
from blinkengage.application.ai_tools import (
    DEFAULT_REGISTRY,
    AiInvocation,
    ToolContext,
    ToolExecutionError,
    ToolExecutor,
)
from blinkengage.core.auth_context import AuthContext
from blinkengage.core.correlation import get_correlation_id

router = APIRouter(prefix="/ai", tags=["ai"])

#: Why a confirmation could not proceed, and what that means over HTTP.
#: ``not_found`` covers both "no such action" and "somebody else's
#: action" deliberately: telling a caller that an id exists but is not
#: theirs is itself a disclosure.
_REASON_STATUS: dict[str, int] = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "consumed": status.HTTP_409_CONFLICT,
    "rejected": status.HTTP_409_CONFLICT,
    "expired": status.HTTP_410_GONE,
    "stale": status.HTTP_409_CONFLICT,
    "permission_denied": status.HTTP_403_FORBIDDEN,
    "unknown_tool": status.HTTP_409_CONFLICT,
}


class ToolSummary(BaseModel):
    name: str
    description: str
    mutating: bool
    requires_confirmation: bool


class ToolListResponse(BaseModel):
    items: list[ToolSummary]


class ConfirmedActionResponse(BaseModel):
    status: str
    tool: str
    content: dict[str, Any]


@router.get("/tools", response_model=ToolListResponse)
async def list_tools(
    auth: Annotated[AuthContext, Depends(require_permission("ai.use"))],
) -> ToolListResponse:
    """The tools this caller may use.

    Filtered by the caller's permissions — a courtesy so a client can
    render capabilities honestly, not a security control. The executor
    re-checks every permission on every call regardless.
    """
    return ToolListResponse(
        items=[
            ToolSummary(
                name=spec.name,
                description=spec.description,
                mutating=spec.mutating,
                requires_confirmation=spec.confirmation.value == "required",
            )
            for spec in DEFAULT_REGISTRY.visible_to(auth.permissions)
        ]
    )


@router.post("/actions/{pending_action_id}/confirm", response_model=ConfirmedActionResponse)
async def confirm_action(
    pending_action_id: UUID,
    ctx: Annotated[ToolContext, Depends(get_tool_context)],
    executor: Annotated[ToolExecutor, Depends(get_tool_executor)],
    _: Annotated[AuthContext, Depends(require_permission("ai.use"))],
) -> ConfirmedActionResponse:
    """Perform a parked high-impact action, exactly once.

    Every check made when the action was proposed is made again — the
    caller's permissions may have changed, and so may the entity. See
    ``ToolExecutor.confirm``.
    """
    try:
        result = await executor.confirm(
            pending_action_id,
            ctx=ctx,
            invocation=AiInvocation(correlation_id=get_correlation_id()),
        )
    except ToolExecutionError as exc:
        raise HTTPException(
            status_code=_REASON_STATUS.get(exc.reason, status.HTTP_400_BAD_REQUEST),
            detail=str(exc),
        ) from exc
    return ConfirmedActionResponse(
        status=result.status.value, tool=result.name, content=result.content
    )


@router.post("/actions/{pending_action_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_action(
    pending_action_id: UUID,
    ctx: Annotated[ToolContext, Depends(get_tool_context)],
    executor: Annotated[ToolExecutor, Depends(get_tool_executor)],
    _: Annotated[AuthContext, Depends(require_permission("ai.use"))],
) -> None:
    try:
        await executor.reject(pending_action_id, ctx=ctx)
    except ToolExecutionError as exc:
        raise HTTPException(
            status_code=_REASON_STATUS.get(exc.reason, status.HTTP_400_BAD_REQUEST),
            detail=str(exc),
        ) from exc
