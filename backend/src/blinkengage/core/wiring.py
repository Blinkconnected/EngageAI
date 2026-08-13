"""Refuses to boot with a critical collaborator missing.

Four defects in this codebase have had the identical shape: a service that
works correctly on its own, reached through an **optional** dependency that
production never passed. ``SlaLifecycle(None)`` returns quietly from every
method. ``ownership=None`` skips the write. Neither raises, neither logs, and
nothing fails — the platform simply stops doing one of the things it promises
while every test that builds the service directly keeps passing.

What that cost, before this existed:

- Every AI reply settled no SLA clock, so a conversation answered in seconds
  was reported as a missed first response until it breached.
- Picking up, releasing and transferring a conversation wrote no ownership
  row, so the timeline showed the platform's automatic decisions and none of
  the human ones.

Both ran in production. Neither was reported by a customer, because the
symptom is a *number in a report* rather than an error anybody sees.

The dependencies stay optional — roughly thirty tests construct these
services directly and have no business supplying a full object graph — so the
guard is not a type change. It is a boot-time assertion that the *production*
wiring is complete, which turns "somebody forgot" from a wrong figure six
months later into a container that will not start.

Adding a service here is deliberately cheap. Adding a collaborator to a
service without adding it here is the failure this module exists to catch, so
``test_wiring.py`` also checks that every optional collaborator on a listed
service is named below.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class WiringError(RuntimeError):
    """A critical service was built without something it needs.

    Raised at startup, never at request time. The message names the service,
    the missing collaborator and what stops working without it, because the
    person reading it at 3am did not write the wiring.
    """


@dataclass(frozen=True, slots=True)
class Collaborator:
    """One dependency whose absence is silent."""

    #: Dotted path from the built service, e.g. ``_sla._engine``.
    path: str
    #: A name a person recognises.
    name: str
    #: What silently stops happening. Goes into the boot failure message.
    consequence: str


@dataclass(frozen=True, slots=True)
class CriticalService:
    """A service the platform must never run half-wired."""

    name: str
    #: Builds it exactly as production does — the *same* factory, never a
    #: reimplementation. A guard that constructed its own copy would pass
    #: while the real one stayed broken.
    build: Callable[[AsyncSession], Any]
    collaborators: tuple[Collaborator, ...]


def _resolve(target: Any, path: str) -> Any:
    for part in path.split("."):
        target = getattr(target, part, None)
        if target is None:
            return None
    return target


def critical_services() -> tuple[CriticalService, ...]:
    """The services, and what each of them must have been given.

    Imported lazily: this module is loaded during application start-up, and
    importing the whole service layer at module scope would make a cycle out
    of anything that later wants to raise ``WiringError``.
    """
    from blinkengage.api.deps import build_conversation_service
    from blinkengage.core.config import get_settings
    from blinkengage.infrastructure.autopilot_factory import build_autopilot_service

    settings = get_settings()

    return (
        CriticalService(
            name="Conversation lifecycle",
            build=lambda session: build_conversation_service(session=session, settings=settings),
            collaborators=(
                Collaborator(
                    path="_sla._engine",
                    name="SLA engine",
                    consequence=(
                        "replies would settle no SLA clock, so answered conversations "
                        "would still be reported as missed targets"
                    ),
                ),
                Collaborator(
                    path="_ownership",
                    name="Ownership service",
                    consequence=(
                        "picking up, releasing and transferring a conversation would "
                        "write no ownership transition, so the timeline would record "
                        "none of what people actually did"
                    ),
                ),
                Collaborator(
                    path="_sla._engine._decisions",
                    name="Routing decision log",
                    consequence=(
                        "SLA movements would happen with nothing recording why, and "
                        "no conversation could be explained afterwards"
                    ),
                ),
            ),
        ),
        CriticalService(
            name="AI queue worker",
            build=lambda session: build_autopilot_service(session=session, settings=settings),
            collaborators=(
                Collaborator(
                    path="_ownership",
                    name="Ownership service",
                    consequence=(
                        "AI would take conversations and never record giving them "
                        "back, leaving it named as the owner of work it had handed off"
                    ),
                ),
                Collaborator(
                    path="_decisions",
                    name="Routing decision recorder",
                    consequence=(
                        "AI's hand-off would leave no explanation — the Story would "
                        "say it gave the conversation back and never why"
                    ),
                ),
                Collaborator(
                    path="_service_contexts",
                    name="Service context resolver",
                    consequence=(
                        "the confidence threshold on the Services screen would be "
                        "ignored in favour of the company-wide one"
                    ),
                ),
                Collaborator(
                    path="_conversation_service._sla._engine",
                    name="SLA engine",
                    consequence=(
                        "every AI reply would settle no SLA clock — the defect this "
                        "guard was written for"
                    ),
                ),
                # Grounding. Both are optional on the constructor because a
                # test double legitimately does without them, and
                # ``_grounding`` degrades to ``None`` when *retrieval fails*
                # — an embedding provider being down must not take Autopilot
                # down with it.
                #
                # Never being wired at all is a different thing wearing the
                # same shape. It is silent, permanent, and indistinguishable
                # from a company that has published nothing: Autopilot keeps
                # answering, unreviewed, with none of the company's approved
                # wording behind it. That is precisely the failure this guard
                # exists to make loud.
                Collaborator(
                    path="_knowledge",
                    name="Knowledge retrieval",
                    consequence=(
                        "AI would answer customers without the company's own "
                        "published articles behind it, and would look exactly like "
                        "a company that had published none"
                    ),
                ),
                Collaborator(
                    path="_faqs",
                    name="FAQ retrieval",
                    consequence=(
                        "AI would answer without the approved answers written for "
                        "these exact questions, reaching for its own wording where "
                        "the company had already decided on some"
                    ),
                ),
                # The structured half. The two above return prose matched by
                # resemblance; this returns the value a human approved,
                # matched by identity — and its absence is the quietest of
                # the three, because the other two still produce a fluent
                # answer about the right product with the wrong number in it.
                Collaborator(
                    path="_brain",
                    name="Company AI Brain",
                    consequence=(
                        "AI would answer pricing and SLA questions from article "
                        "prose alone, so a published price change would change "
                        "nothing about what customers were told — and no absence "
                        "signal would reach the model when nothing is on record"
                    ),
                ),
            ),
        ),
    )


def verify_wiring(session_factory: Callable[[], AsyncSession]) -> None:
    """Builds every critical service and refuses to continue if one is short.

    Constructing a session does no I/O — SQLAlchemy connects lazily — so this
    runs before the database is necessarily reachable and costs a few object
    allocations. It is a wiring check, not a health check.

    Every problem is collected before raising. An operator fixing one missing
    collaborator, restarting, and discovering a second is an operator who
    learns to distrust the message.
    """
    problems: list[str] = []
    session = session_factory()
    for service in critical_services():
        try:
            built = service.build(session)
        except Exception as error:  # noqa: BLE001 — reported, not swallowed.
            problems.append(f"{service.name}: could not be built at all ({error!r})")
            continue
        for collaborator in service.collaborators:
            if _resolve(built, collaborator.path) is None:
                problems.append(
                    f"{service.name} was built without its {collaborator.name} "
                    f"({collaborator.path}) — {collaborator.consequence}"
                )

    if problems:
        raise WiringError(
            "The application refused to start because critical services are "
            "missing collaborators they need. These are optional constructor "
            "arguments, so nothing would have failed at run time — the "
            "behaviour below would simply not have happened:\n  - " + "\n  - ".join(problems)
        )


__all__ = ["Collaborator", "CriticalService", "WiringError", "critical_services", "verify_wiring"]
