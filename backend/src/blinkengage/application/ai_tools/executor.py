"""The pipeline. Every AI-initiated effect passes through here.

See ``docs/architecture/ai-tool-calling.md``.

::

    tool call
      → registry allowlist        unknown name stops here
      → strict schema validation  extra="forbid", typed, bounded
      → authenticated AuthContext identity is never an argument
      → tenant scope              company_id injected, not supplied
      → permission check          an existing RBAC code
      → confirmation policy       high-impact parks, does not run
      → existing application service  business rules, events, outbox
      → audit                     before/after, request, model, result
      → structured ToolResult

Three properties are worth stating outright, because they are what make
this safe rather than merely careful.

**Refusals are data, not exceptions.** An unknown tool, a bad argument, a
missing permission — each becomes a ``ToolResult`` with status ``error``
that goes back to the model so it can correct itself. Raising would end
the turn and, worse, would take the refusal outside the path where it
gets audited. A model repeatedly trying something it may not do is a
signal somebody should be able to find later.

**Nothing is trusted twice.** Confirmation re-validates, re-authorises
and re-reads the world before executing, because everything it checked
the first time may have changed while a human was reading a dialog.

**The idempotency system is M1's.** ``IdempotencyStore`` is the same
primitive behind ``Idempotency-Key`` on message send; this reuses it with
a different scope rather than growing a second mechanism that would
inevitably behave differently under failure.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import orjson
from pydantic import BaseModel, ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.application.ai_tools.audit import serialize_arguments, serialize_state
from blinkengage.application.ai_tools.registry import ToolRegistry
from blinkengage.application.ai_tools.spec import ConfirmationPolicy, ToolContext, ToolSpec
from blinkengage.core.logging import get_logger
from blinkengage.domain.ai_tools import ToolCall, ToolResult, ToolResultStatus
from blinkengage.domain.exceptions import DomainError
from blinkengage.infrastructure.cache.idempotency import IdempotencyStore, Proceed, Replay
from blinkengage.infrastructure.cache.idempotency import fingerprint as fingerprint_of
from blinkengage.infrastructure.database.models.ai_action import AiActionLog, PendingAiAction

logger = get_logger(__name__)

#: How long a proposed action waits for a human. Long enough to read a
#: diff and think; short enough that an approval is about the workspace
#: as it is now rather than as it was this morning.
PENDING_ACTION_TTL = timedelta(minutes=10)

#: Any validated list argument longer than this escalates to requiring
#: confirmation, whatever the tool's own policy says. Generic on purpose:
#: "bulk changes need a human" should hold for the bulk tool nobody has
#: written yet, so it is a property of the executor rather than something
#: each tool author must remember to declare.
BULK_ESCALATION_THRESHOLD = 5


@dataclass(frozen=True, slots=True)
class AiInvocation:
    """Provenance for one model turn. Supplied by the caller, never by
    the model."""

    user_request: str | None = None
    model_identifier: str | None = None
    session_id: UUID | None = None
    turn_id: UUID | None = None
    correlation_id: str | None = None


class ToolExecutionError(DomainError):
    """Confirmation could not proceed. Carries a reason code the API maps
    to a status."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _error(call: ToolCall, message: str, **extra: Any) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status=ToolResultStatus.ERROR,
        content={"error": message, **extra},
    )


class ToolExecutor:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        session: AsyncSession,
        idempotency: IdempotencyStore,
    ) -> None:
        self._registry = registry
        self._session = session
        self._idempotency = idempotency

    # --- the main path ------------------------------------------------

    async def execute(
        self, call: ToolCall, *, ctx: ToolContext, invocation: AiInvocation
    ) -> ToolResult:
        spec = self._registry.get(call.name)
        if spec is None:
            # Not "permission denied" — the tool does not exist. Saying so
            # plainly stops the model retrying a name it invented, and
            # leaks nothing: the registry's contents are already visible
            # to this caller via GET /ai/tools.
            await self._record(
                ctx,
                invocation,
                tool_name=call.name,
                result="error",
                error="unknown_tool",
                validated_input={},
            )
            return _error(call, f"Unknown tool {call.name!r}", known=sorted(self._registry.names()))

        try:
            args = spec.args_model.model_validate(call.arguments)
        except ValidationError as exc:
            await self._record(
                ctx,
                invocation,
                tool_name=spec.name,
                result="error",
                error="invalid_arguments",
                validated_input={},
            )
            # The model is told *what* was wrong so it can fix it. Pydantic's
            # own messages name the field and the constraint, which is
            # exactly the feedback a model can act on.
            return _error(call, "Invalid arguments", details=_validation_details(exc))

        if spec.permission is not None and not ctx.auth.has_permission(spec.permission):
            await self._record(
                ctx,
                invocation,
                tool_name=spec.name,
                result="error",
                error="permission_denied",
                validated_input=serialize_arguments(args),
            )
            return _error(call, f"Missing required permission: {spec.permission}")

        if self._needs_confirmation(spec, args):
            return await self._park(call, spec, args, ctx=ctx, invocation=invocation)

        return await self._run(call, spec, args, ctx=ctx, invocation=invocation)

    # --- confirmation -------------------------------------------------

    @staticmethod
    def _needs_confirmation(spec: ToolSpec, args: BaseModel) -> bool:
        if spec.confirmation is ConfirmationPolicy.REQUIRED:
            return True
        if not spec.mutating:
            return False
        return any(
            isinstance(value, list | tuple | set) and len(value) > BULK_ESCALATION_THRESHOLD
            for value in args.model_dump().values()
        )

    async def _park(
        self,
        call: ToolCall,
        spec: ToolSpec,
        args: BaseModel,
        *,
        ctx: ToolContext,
        invocation: AiInvocation,
    ) -> ToolResult:
        before = await self._read_state(spec, ctx, args)
        pending = PendingAiAction(
            company_id=ctx.company_id,
            requested_by_user_id=ctx.actor_user_id,
            session_id=invocation.session_id,
            turn_id=invocation.turn_id,
            tool_name=spec.name,
            validated_input=serialize_arguments(args),
            before_state=serialize_state(before),
            summary=_summarize(spec, args),
            user_request=invocation.user_request,
            model_identifier=invocation.model_identifier,
            correlation_id=invocation.correlation_id,
            expires_at=datetime.now(UTC) + PENDING_ACTION_TTL,
        )
        self._session.add(pending)
        await self._session.flush()

        await self._record(
            ctx,
            invocation,
            tool_name=spec.name,
            result="confirmation_required",
            validated_input=serialize_arguments(args),
            before_state=serialize_state(before),
        )
        return ToolResult(
            call_id=call.id,
            name=spec.name,
            status=ToolResultStatus.CONFIRMATION_REQUIRED,
            content={
                "pending_action_id": str(pending.id),
                "summary": pending.summary,
                "expires_at": pending.expires_at.isoformat(),
                "message": (
                    "This action needs the user's explicit confirmation. Tell them what it "
                    "will do and wait — you cannot approve it yourself."
                ),
            },
        )

    async def confirm(
        self, pending_action_id: UUID, *, ctx: ToolContext, invocation: AiInvocation
    ) -> ToolResult:
        """Execute a parked action, exactly once.

        Everything checked at proposal time is checked again. The caller
        may hold a different role than they did ten minutes ago, and the
        entity may have been edited by somebody else in the meantime —
        approving a diff that no longer describes reality is precisely
        the failure a confirmation step exists to prevent.
        """
        pending = (
            await self._session.execute(
                select(PendingAiAction).where(
                    PendingAiAction.id == pending_action_id,
                    # Tenant scope from the token. A pending action from
                    # another company is not "forbidden", it is not found.
                    PendingAiAction.company_id == ctx.company_id,
                )
            )
        ).scalar_one_or_none()

        if pending is None:
            raise ToolExecutionError("not_found", "No such pending action")
        if pending.requested_by_user_id != ctx.actor_user_id:
            raise ToolExecutionError("not_found", "No such pending action")
        if pending.rejected_at is not None:
            raise ToolExecutionError("rejected", "This action was rejected")
        if pending.consumed_at is not None:
            raise ToolExecutionError("consumed", "This action has already been performed")
        if pending.expires_at <= datetime.now(UTC):
            raise ToolExecutionError("expired", "This action expired; ask again to re-propose it")

        spec = self._registry.get(pending.tool_name)
        if spec is None:
            raise ToolExecutionError("unknown_tool", "That tool no longer exists")
        if spec.permission is not None and not ctx.auth.has_permission(spec.permission):
            raise ToolExecutionError(
                "permission_denied", f"Missing required permission: {spec.permission}"
            )

        args = spec.args_model.model_validate(pending.validated_input)

        current = serialize_state(await self._read_state(spec, ctx, args))
        if current != pending.before_state:
            raise ToolExecutionError(
                "stale",
                "The workspace changed since this was proposed. Ask again so you can review "
                "what would happen now.",
            )

        # The claim. A conditional UPDATE, so two confirmations arriving
        # together cannot both find it unconsumed and both execute.
        claimed = await self._session.execute(
            update(PendingAiAction)
            .where(PendingAiAction.id == pending.id, PendingAiAction.consumed_at.is_(None))
            .values(consumed_at=datetime.now(UTC))
        )
        if claimed.rowcount != 1:
            raise ToolExecutionError("consumed", "This action has already been performed")

        call = ToolCall(id=str(pending.id), name=spec.name, arguments=pending.validated_input)
        return await self._run(
            call, spec, args, ctx=ctx, invocation=invocation, before_override=pending.before_state
        )

    async def reject(self, pending_action_id: UUID, *, ctx: ToolContext) -> None:
        result = await self._session.execute(
            update(PendingAiAction)
            .where(
                PendingAiAction.id == pending_action_id,
                PendingAiAction.company_id == ctx.company_id,
                PendingAiAction.requested_by_user_id == ctx.actor_user_id,
                PendingAiAction.consumed_at.is_(None),
                PendingAiAction.rejected_at.is_(None),
            )
            .values(rejected_at=datetime.now(UTC))
        )
        if result.rowcount != 1:
            raise ToolExecutionError("not_found", "No such pending action")

    # --- execution ----------------------------------------------------

    async def _run(
        self,
        call: ToolCall,
        spec: ToolSpec,
        args: BaseModel,
        *,
        ctx: ToolContext,
        invocation: AiInvocation,
        before_override: dict[str, Any] | None = None,
    ) -> ToolResult:
        scope = f"ai_tool:{ctx.company_id}:{ctx.actor_user_id}:{spec.name}"
        request_fingerprint = fingerprint_of(orjson.dumps(serialize_arguments(args)))

        reservation = await self._idempotency.reserve(
            scope=scope,
            idempotency_key=call.id,
            request_fingerprint=request_fingerprint,
            reservation_ttl=timedelta(seconds=60),
        )
        if isinstance(reservation, Replay):
            # A retried turn replays its original result rather than
            # creating a second department.
            return ToolResult(
                call_id=call.id,
                name=spec.name,
                status=ToolResultStatus(reservation.body.get("status", "ok")),
                content=reservation.body.get("content", {}),
            )
        if not isinstance(reservation, Proceed):
            return _error(call, "A call with this id is already in progress")

        before = (
            before_override
            if before_override is not None
            else serialize_state(await self._read_state(spec, ctx, args))
        )
        try:
            content = await spec.handler(ctx, args)
        except DomainError as exc:
            await self._idempotency.release(scope=scope, idempotency_key=call.id)
            await self._record(
                ctx,
                invocation,
                tool_name=spec.name,
                result="error",
                error=str(exc),
                validated_input=serialize_arguments(args),
                before_state=before,
            )
            # A business rule said no. That is a legitimate answer, handed
            # back for the model to explain rather than an exception that
            # ends the conversation.
            return _error(call, str(exc))
        except Exception:
            await self._idempotency.release(scope=scope, idempotency_key=call.id)
            raise

        after = serialize_state(await self._read_state(spec, ctx, args))
        await self._record(
            ctx,
            invocation,
            tool_name=spec.name,
            result="ok",
            validated_input=serialize_arguments(args),
            before_state=before,
            after_state=after,
        )

        result = ToolResult(
            call_id=call.id, name=spec.name, status=ToolResultStatus.OK, content=content
        )
        await self._idempotency.complete(
            scope=scope,
            idempotency_key=call.id,
            request_fingerprint=request_fingerprint,
            status_code=200,
            body={"status": result.status.value, "content": result.content},
            result_ttl=timedelta(hours=24),
        )
        return result

    async def _read_state(
        self, spec: ToolSpec, ctx: ToolContext, args: BaseModel
    ) -> dict[str, Any] | None:
        if spec.state_reader is None:
            return None
        try:
            return await spec.state_reader(ctx, args)
        except DomainError:
            # The entity does not exist yet (a creation) or no longer does.
            # Either way "no state" is the honest answer, not a failure.
            return None

    async def _record(
        self,
        ctx: ToolContext,
        invocation: AiInvocation,
        *,
        tool_name: str,
        result: str,
        validated_input: dict[str, Any],
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self._session.add(
            AiActionLog(
                company_id=ctx.company_id,
                actor_user_id=ctx.actor_user_id,
                session_id=invocation.session_id,
                turn_id=invocation.turn_id,
                tool_name=tool_name,
                validated_input=validated_input,
                before_state=before_state,
                after_state=after_state,
                user_request=invocation.user_request,
                model_identifier=invocation.model_identifier,
                correlation_id=invocation.correlation_id,
                result=result,
                error_detail=error,
            )
        )
        await self._session.flush()


def _validation_details(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {"field": ".".join(str(part) for part in error["loc"]), "problem": error["msg"]}
        for error in exc.errors()
    ]


def _summarize(spec: ToolSpec, args: BaseModel) -> str:
    """The sentence the user is asked to approve.

    Assembled from the validated arguments, deliberately not from
    anything the model wrote. If a model could author this text it could
    describe a change as something milder than it is, and the human would
    be approving the description rather than the action.
    """
    rendered = ", ".join(
        f"{name}={value!r}" for name, value in sorted(serialize_arguments(args).items())
    )
    return f"{spec.name}({rendered})"


def new_call_id() -> str:
    """For callers synthesising a tool call (tests, replays) rather than
    receiving one from a provider."""
    return str(uuid4())
