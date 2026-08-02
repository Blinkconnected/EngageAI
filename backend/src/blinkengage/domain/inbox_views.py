"""The work queues an agent moves between.

Not filters. A filter asks the agent to describe the data they want, which
requires knowing the data model before you can ask a question — the old Inbox
needed a mode toggle, a status tab and a switch whose meaning changed with the
mode, and most of the combinations meant nothing.

A view is an operational question with one answer. "What needs attention?" is
a thing an agent already wants to know; `status=waiting AND assigned_agent_id
IS NULL AND autopilot_active = false` is a thing they should never have to
assemble.

Each view is a **server-side query**. Computing them in the browser would
filter the page in hand rather than the Inbox, which is not filtering at all —
the same mistake the SLA ordering avoids by ranking in SQL.

Framework-free, like the rest of ``domain/``: this names the views and says
what each one means. The SQL that implements them lives in the repository, and
a test holds the two together — see ``test_inbox_views.py``, which checks that
every conversation a view returns really is in the operational state the view
claims. Two expressions of one rule drift apart otherwise, and that has
already happened once in this codebase, on the SLA bands.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class InboxView(StrEnum):
    """A work queue, named for the question it answers."""

    #: Everything unfinished. The denominator for "how busy am I".
    ACTIVE = "active"
    #: Somebody must act, and it is us. Excludes anything waiting on the
    #: customer or being handled by AI — a conversation waiting on a customer
    #: is not neglected, and an agent has to be able to skip it without
    #: wondering whether they should.
    NEEDS_ATTENTION = "needs_attention"
    #: In a queue with nobody on it, human or AI.
    WAITING_PICKUP = "waiting_pickup"
    #: Assigned to the agent asking.
    MINE = "mine"
    #: Autopilot has it, or is waiting out its pickup delay.
    AI_WORKING = "ai_working"
    #: The ball is with the customer.
    WAITING_CUSTOMER = "waiting_customer"
    #: Close enough to a target to need doing now.
    AT_RISK = "at_risk"
    #: A target was missed. Nothing here improves by waiting.
    BREACHED = "breached"
    #: Finished today — the one backward-looking view, because "what did we
    #: get done" is a question every morning starts with.
    RESOLVED_TODAY = "resolved_today"


#: The order they appear, which is the order an agent triages in: what is
#: broken, what nobody has, what is mine, what AI has, what we are waiting
#: on, and finally what is done.
VIEW_ORDER: Final[tuple[InboxView, ...]] = (
    InboxView.NEEDS_ATTENTION,
    InboxView.WAITING_PICKUP,
    InboxView.MINE,
    InboxView.AI_WORKING,
    InboxView.WAITING_CUSTOMER,
    InboxView.AT_RISK,
    InboxView.BREACHED,
    InboxView.RESOLVED_TODAY,
)

#: What each view is called, and what it means. The second half matters: a
#: work queue whose definition is guessable-but-not-stated is one people
#: mistrust the first time it surprises them.
VIEW_TEXT: Final[dict[InboxView, tuple[str, str]]] = {
    InboxView.ACTIVE: ("Active", "Everything not yet resolved or closed."),
    InboxView.NEEDS_ATTENTION: (
        "Needs attention",
        "Waiting on us, and either running out of time or sitting with nobody on it.",
    ),
    InboxView.WAITING_PICKUP: (
        "Waiting pickup",
        "In a queue with nobody working it — not an agent, not AI.",
    ),
    InboxView.MINE: ("Assigned to me", "Conversations assigned to you."),
    InboxView.AI_WORKING: (
        "AI working",
        "AI is answering, or waiting out its pickup delay before it does.",
    ),
    InboxView.WAITING_CUSTOMER: (
        "Waiting customer",
        "The ball is with the customer. Time here is not us being late.",
    ),
    InboxView.AT_RISK: ("At risk", "Close enough to a target that it needs doing now."),
    InboxView.BREACHED: ("Breached", "A target was missed. Waiting does not improve these."),
    InboxView.RESOLVED_TODAY: ("Resolved today", "Finished today."),
}

#: Views that need to know who is asking. Requesting one without an agent
#: identity is a question with no answer, not an empty result.
NEEDS_AN_AGENT: Final[frozenset[InboxView]] = frozenset({InboxView.MINE})


__all__ = ["NEEDS_AN_AGENT", "VIEW_ORDER", "VIEW_TEXT", "InboxView"]
