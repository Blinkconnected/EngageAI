"""Driving a customer through a connection, whatever they are connecting.

The wizard. It owns the session — what has been answered so far, which step is
live, what happens next — and it does that for every channel with one code
path, because the steps come from ``steps_for`` and the work comes from the
connector.

**There is no channel name in this file.** That is the property worth
protecting: the moment this module needs to know what WhatsApp is, adding
Slack stops being one file and starts being a week. Everything channel-shaped
is asked of the connector — what to render, what to discover, what to check,
what to write down.

Sessions live in Redis rather than in a table. A half-finished connection is
worth nothing an hour later: the OAuth state it holds has expired, the
discovered resources are stale, and the customer has moved on. Persisting them
would mean a cleanup job and a migration to store something whose entire value
is measured in minutes.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID

import orjson
from redis.asyncio import Redis

from blinkengage.domain.connection_templates import ConnectionTemplate, template_for
from blinkengage.domain.connector import Attempt, Connection, DeploymentContext, Resource
from blinkengage.domain.connectors import (
    Capability,
    CheckOutcome,
    Step,
    StepId,
    blocks_connection,
    steps_for,
)
from blinkengage.domain.exceptions import DomainError
from blinkengage.infrastructure.connectors.registry import ConnectorRegistry

#: How long a customer has to finish. Long enough to leave for a provider's
#: consent screen, read a permission list and come back; short enough that an
#: abandoned session's OAuth state is gone well before anyone could reuse it.
SESSION_TTL = timedelta(minutes=30)


def _key(session_id: str) -> str:
    return f"channel_connect:{session_id}"


class ConnectSessionError(DomainError):
    """The session cannot do what was asked of it."""


class ConnectSessionNotFound(DomainError):
    """No such session, or it expired.

    One error for both, deliberately: telling an unauthenticated caller which
    of the two it was would let them enumerate live sessions.
    """


@dataclass(slots=True)
class ConnectSession:
    """One customer's progress through one connection."""

    id: str
    company_id: UUID
    user_id: UUID
    #: Which connectors are being connected. More than one under a template.
    channel_types: tuple[str, ...]
    template_key: str | None = None
    #: Which of the derived steps is live.
    step_index: int = 0
    #: Chosen on a connector offering both paths; decides the flow.
    using_oauth: bool = False
    inputs: dict[str, Any] = field(default_factory=dict)
    grant: dict[str, Any] = field(default_factory=dict)
    #: Resource ids, per channel type — the customer's picks.
    selected: dict[str, list[str]] = field(default_factory=dict)
    display_name: str = ""
    #: Cached so the picker survives a page refresh without asking the
    #: provider again, which for a Meta grant is several Graph calls.
    discovered: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    checks: list[dict[str, Any]] = field(default_factory=list)
    #: Set once the connection has been made, so a double submit cannot make
    #: two channels out of one consent.
    completed: bool = False

    @property
    def primary(self) -> str:
        """The connector whose capabilities shape the flow.

        Under a template every channel shares one provider app and therefore
        one consent, so any of them derives the same steps; the first is as
        good an answer as exists and is stable.
        """
        return self.channel_types[0]


class ChannelConnectService:
    """Creates sessions and moves them forward."""

    def __init__(self, *, redis: Redis, context: DeploymentContext) -> None:
        self._redis = redis
        self._context = context

    @property
    def context(self) -> DeploymentContext:
        """What this installation holds.

        Exposed because the API layer builds an authorize URL and a webhook
        registration, both of which need it — and threading a second copy
        through would let the two drift.
        """
        return self._context

    # --- Catalog ------------------------------------------------------

    def catalog(self) -> tuple[Any, ...]:
        """What can be connected here, and how."""
        return ConnectorRegistry.catalog(self._context)

    # --- Session lifecycle --------------------------------------------

    async def start(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        channel_type: str | None = None,
        template_key: str | None = None,
    ) -> ConnectSession:
        template = self._template(template_key) if template_key else None
        channel_types = template.channel_types if template else (channel_type or "",)
        if not channel_types[0]:
            raise ConnectSessionError("Choose a channel or a template to connect.")

        for name in channel_types:
            connector = ConnectorRegistry.get(name)
            if connector is None:
                raise ConnectSessionError(f"'{name}' is not a channel this build supports.")
            profile = connector.resolve(self._context)
            if not profile.connectable:
                # Neither consent nor a form: offering it would be an
                # invitation to a dead end.
                raise ConnectSessionError(f"'{name}' cannot be connected on this installation.")

        session = ConnectSession(
            id=secrets.token_urlsafe(24),
            company_id=company_id,
            user_id=user_id,
            channel_types=tuple(channel_types),
            template_key=template.key if template else None,
            # Consent is the path worth defaulting to wherever it exists; a
            # customer who wants the form can still ask for it.
            using_oauth=self._profile(channel_types[0]).supports(Capability.OAUTH),
            # Selecting is what created the session, so it is already done.
            step_index=1,
        )
        await self._save(session)
        return session

    async def get(self, session_id: str, *, company_id: UUID) -> ConnectSession:
        raw = await self._redis.get(_key(session_id))
        if raw is None:
            raise ConnectSessionNotFound("That connection has expired. Start again.")
        session = self._decode(raw)
        # Tenancy from the session, never from the caller's parameters — and
        # checked here rather than trusted, since the session id is the only
        # thing an OAuth callback carries.
        if session.company_id != company_id:
            raise ConnectSessionNotFound("That connection has expired. Start again.")
        return session

    # --- The flow -----------------------------------------------------

    def steps(self, session: ConnectSession) -> tuple[Step, ...]:
        return steps_for(self._profile(session.primary), using_oauth=session.using_oauth)

    def current(self, session: ConnectSession) -> Step:
        flow = self.steps(session)
        return flow[min(session.step_index, len(flow) - 1)]

    async def advance(self, session: ConnectSession, payload: dict[str, Any]) -> ConnectSession:
        """Answer the live step and move to the next.

        One method for every step because the *step* decides what an answer
        means. The alternative — an endpoint per step kind — would put the
        flow's shape in the API surface, where changing it becomes a breaking
        change rather than a different derivation.
        """
        if session.completed:
            raise ConnectSessionError("That connection is already finished.")

        step = self.current(session)
        if step.id is StepId.AUTHENTICATE:
            await self._authenticate(session, payload)
        elif step.id is StepId.DISCOVER:
            self._select(session, payload)
        elif step.id is StepId.CONNECT:
            raise ConnectSessionError("Use the connect action to finish.")

        session.step_index = min(session.step_index + 1, len(self.steps(session)) - 1)

        # An automatic step runs on *arrival*, not when the customer tries to
        # leave it. Verify is the one that matters: running its checks on the
        # way out would show the customer an empty checklist, then move them
        # past it — so the step whose whole job is saying what is wrong would
        # be the one step that never said anything.
        if self.current(session).id is StepId.VERIFY:
            await self._verify(session)

        await self._save(session)
        return session

    async def _authenticate(self, session: ConnectSession, payload: dict[str, Any]) -> None:
        session.display_name = str(payload.get("display_name", session.display_name)).strip()
        if session.using_oauth:
            # The grant arrives from the callback, not from the browser — the
            # customer's own request never carries a token.
            if not session.grant:
                raise ConnectSessionError("Authorization has not finished yet.")
            return
        session.inputs = {
            key: value for key, value in payload.items() if key != "display_name"
        }
        # Discovery is skipped on the form path, so cache what was typed as
        # the whole answer and let verify read it.

    def _select(self, session: ConnectSession, payload: dict[str, Any]) -> None:
        chosen = payload.get("selected") or {}
        if not isinstance(chosen, dict) or not any(chosen.values()):
            raise ConnectSessionError("Choose at least one to connect.")
        session.selected = {
            name: [str(value) for value in ids] for name, ids in chosen.items()
        }

    async def _verify(self, session: ConnectSession) -> None:
        """Run every connector's checks, keeping each finding attributed.

        A template connects several channels from one consent, and "your
        Instagram account has messages turned off" is useless without the
        word Instagram in front of it — so the channel travels with the
        outcome rather than being inferred from position.
        """
        checks: list[dict[str, Any]] = []
        for name in session.channel_types:
            connector = ConnectorRegistry.get(name)
            if connector is None:  # pragma: no cover - start() already checked
                continue
            for outcome in await connector.check(self._attempt(session, name)):
                checks.append(
                    {
                        "code": outcome.code,
                        "level": outcome.level,
                        "params": outcome.params,
                        "channel_type": name,
                        "fix": (
                            {
                                "kind": outcome.fix.kind,
                                "action_id": outcome.fix.action_id,
                                "instructions_key": outcome.fix.instructions_key,
                            }
                            if outcome.fix
                            else None
                        ),
                    }
                )
        session.checks = checks

    async def discover(self, session: ConnectSession) -> dict[str, list[Resource]]:
        """What the customer owns, cached on the session.

        Cached because a page refresh must not cost several provider calls,
        and because the ids the customer picks have to mean the same thing
        when the connect step reads them back.
        """
        found: dict[str, list[Resource]] = {}
        for name in session.channel_types:
            connector = ConnectorRegistry.get(name)
            if connector is None:  # pragma: no cover
                continue
            resources = list(await connector.discover(grant=session.grant))
            found[name] = resources
            session.discovered[name] = [
                {
                    "id": r.id,
                    "label": r.label,
                    "group_key": r.group_key,
                    "detail": r.detail,
                    "unavailable_reason": r.unavailable_reason,
                    "context": r.context,
                }
                for r in resources
            ]
        await self._save(session)
        return found

    async def connect(self, session: ConnectSession) -> tuple[Connection, ...]:
        """Make it real.

        Refuses on a failing check rather than trusting the console to have
        stopped: the checklist is advice to a customer and a precondition to
        this method, and only one of those is enforceable.
        """
        if session.completed:
            raise ConnectSessionError("That connection is already finished.")
        if blocks_connection(
            tuple(
                CheckOutcome(code=c["code"], level=c["level"]) for c in session.checks
            )
        ):
            raise ConnectSessionError("Fix the problems listed before connecting.")

        made: list[Connection] = []
        for name in session.channel_types:
            connector = ConnectorRegistry.get(name)
            if connector is None:  # pragma: no cover
                continue
            # Per channel, committed per channel. If the second of three
            # fails, the first stays connected: rolling back a working
            # connection because a sibling failed is worse for the customer
            # than a partial success they can finish.
            made.extend(
                await connector.connect(
                    company_id=session.company_id, attempt=self._attempt(session, name)
                )
            )
        session.completed = True
        await self._save(session)
        return tuple(made)

    # --- Internals ----------------------------------------------------

    def _attempt(self, session: ConnectSession, channel_type: str) -> Attempt:
        cached = session.discovered.get(channel_type, [])
        picked = set(session.selected.get(channel_type, []))
        return Attempt(
            context=self._context,
            inputs=session.inputs,
            grant=session.grant,
            selection=tuple(
                Resource(
                    id=str(entry["id"]),
                    label=str(entry["label"]),
                    group_key=entry.get("group_key"),
                    detail=entry.get("detail") or {},
                    unavailable_reason=entry.get("unavailable_reason"),
                    context=entry.get("context") or {},
                )
                for entry in cached
                if str(entry["id"]) in picked
            ),
            display_name=session.display_name,
        )

    def _profile(self, channel_type: str) -> Any:
        connector = ConnectorRegistry.get(channel_type)
        if connector is None:
            raise ConnectSessionError(f"'{channel_type}' is not a channel this build supports.")
        return connector.resolve(self._context)

    def _template(self, key: str) -> ConnectionTemplate:
        template = template_for(key)
        if template is None:
            raise ConnectSessionError(f"'{key}' is not a connection template.")
        return template

    async def _save(self, session: ConnectSession) -> None:
        await self._redis.set(
            _key(session.id),
            orjson.dumps(
                {
                    "id": session.id,
                    "company_id": str(session.company_id),
                    "user_id": str(session.user_id),
                    "channel_types": list(session.channel_types),
                    "template_key": session.template_key,
                    "step_index": session.step_index,
                    "using_oauth": session.using_oauth,
                    "inputs": session.inputs,
                    "grant": session.grant,
                    "selected": session.selected,
                    "display_name": session.display_name,
                    "discovered": session.discovered,
                    "checks": session.checks,
                    "completed": session.completed,
                }
            ),
            ex=int(SESSION_TTL.total_seconds()),
        )

    @staticmethod
    def _decode(raw: bytes | str) -> ConnectSession:
        parsed = orjson.loads(raw)
        return ConnectSession(
            id=parsed["id"],
            company_id=UUID(parsed["company_id"]),
            user_id=UUID(parsed["user_id"]),
            channel_types=tuple(parsed["channel_types"]),
            template_key=parsed.get("template_key"),
            step_index=int(parsed.get("step_index", 0)),
            using_oauth=bool(parsed.get("using_oauth", False)),
            inputs=parsed.get("inputs") or {},
            grant=parsed.get("grant") or {},
            selected=parsed.get("selected") or {},
            display_name=parsed.get("display_name", ""),
            discovered=parsed.get("discovered") or {},
            checks=parsed.get("checks") or [],
            completed=bool(parsed.get("completed", False)),
        )


__all__ = [
    "SESSION_TTL",
    "ChannelConnectService",
    "ConnectSession",
    "ConnectSessionError",
    "ConnectSessionNotFound",
]
