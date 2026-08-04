"""The Conversation Black Box, read after a conversation has actually lived.

Built against a real lifecycle rather than fixtures, because the thing under
test is whether one screen can answer *what happened to this conversation* —
and a screen assembled from hand-made rows would answer it about a
conversation nobody had.

The point of the milestone: the platform had recorded all of this for several
milestones and none of it was readable. Ownership had an endpoint, SLA had an
endpoint, the decision log had none — so "every business decision is
explainable" was true of the database and of nothing a person could open.
"""

import uuid
from datetime import datetime
from typing import Any

import pytest
from httpx import AsyncClient

from tests.integration.test_ai_queue_worker import (
    _AUTOPILOT_ON,
    _claimed_by_a_human,
    _run,
    _sweep,
    _wind_back,
)

pytestmark = pytest.mark.asyncio


async def _inspect(client: AsyncClient, headers: dict, conversation_id: uuid.UUID) -> dict:
    response = await client.get(
        f"/api/v1/conversations/{conversation_id}/inspector", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _a_lived_conversation(
    client: AsyncClient,
    owner_headers: dict,
    registered_owner: dict,
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """One conversation that has been routed, deferred, answered by AI and
    then taken by a human — so every section has something real in it."""
    conversation, _ = await _run(
        client,
        owner_headers,
        registered_owner,
        app,
        settings=_AUTOPILOT_ON,
        ai_enabled=True,
        confidence_threshold="0.6",
        sla_queue_minutes=10,
    )
    await _wind_back(app, conversation.id)
    await _sweep(app, monkeypatch, confidence=70)
    await _claimed_by_a_human(client, owner_headers, app, conversation.id)
    return conversation


class TestTheBlackBoxAnswersTheQuestion:
    async def test_it_says_what_happened_from_the_first_second(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conversation = await _a_lived_conversation(
            client, owner_headers, registered_owner, app, monkeypatch
        )

        box = await _inspect(client, owner_headers, conversation.id)

        # 1. Summary — the facts somebody wants before reading anything.
        summary = box["summary"]
        assert summary["status"]
        assert summary["service_name"] == "Support"
        assert summary["owner_label"], "somebody is always answerable"
        assert summary["sla_health"] in {"healthy", "attention", "at_risk", "breached"}
        assert summary["age_seconds"] >= 0

        # 2. Timeline — the primary investigation view, in order.
        timeline = box["timeline"]
        assert timeline, "a conversation that has lived has a story"
        # Parsed, not string-compared: two timestamps in the same second
        # serialise as "…43+00:00" and "…43.358544+00:00", and "+" sorts
        # before a digit — so comparing the strings would fail on a timeline
        # that is perfectly ordered.
        times = [datetime.fromisoformat(entry["at"]) for entry in timeline]
        assert times == sorted(times), "chronological, or it is not a timeline"
        streams = {entry["stream"] for entry in timeline}
        assert {
            "routing",
            "ownership",
            "ai",
        } <= streams, "the three sources that each saw part of it are merged, not three lists"

        # 3. Routing decisions — readable by default, structured underneath.
        decisions = box["decisions"]
        assert decisions
        assert all(row["sentence"] for row in decisions), "every row reads as a sentence"
        assert all(
            row["kind"] and row["reason"] for row in decisions
        ), "and carries the codes a console filters on"

        # 4. Ownership — who had it, and for how long.
        ownership = box["ownership"]
        assert len(ownership) >= 2, "queue, then AI, then the agent who took it"
        assert all(span["reason_text"] for span in ownership)
        assert all(span["held_seconds"] >= 0 for span in ownership)
        assert ownership[-1]["previous_label"], "a hand-over names both sides"

        # 5. SLA — every clock, with the question it answers.
        clocks = box["clocks"]
        assert clocks
        assert all(
            clock["question"].endswith("?") for clock in clocks
        ), "every timer answers a business question, not a technical one"
        assert all(clock["responsible"] for clock in clocks)

        # 6. AI — why it did, or did not, answer.
        ai = box["ai"]
        assert ai["state"]
        assert ai["pickup_delay_seconds"] == 30
        assert ai["confidence_threshold"] == "0.6"
        assert (
            ai["threshold_source"] == "service"
        ), "which setting decided, so nobody hunts for the wrong one"
        assert ai["reasons"], "AI's own account of what it did"

        # 7. Policies — every business decision, allowed or denied.
        policies = box["policies"]
        assert policies
        assert all(
            policy["source"] for policy in policies
        ), "a denial names the screen to open, or it sends somebody hunting"

        # 8. Technical — what an engineer would open a database for.
        technical = box["technical"]
        assert technical["conversation_id"] == str(conversation.id)
        assert technical["service_version_id"], "the exact version this ran under"
        assert "routing_rules" in technical["unversioned"]

    async def test_it_never_invents_what_it_does_not_know(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The property that makes it a troubleshooting tool rather than a
        dashboard.

        A conversation with nothing recorded must say so. An empty section and
        an unrecorded one look identical otherwise, and they send an
        investigator to very different places.
        """
        conversation, _ = await _run(
            client, owner_headers, registered_owner, app, with_service=False
        )

        box = await _inspect(client, owner_headers, conversation.id)

        assert box["summary"]["runtime_queues_in_use"] is False, (
            "runtime lanes have storage and a domain model and nothing creates "
            "them — reported as not in use rather than shown as a blank field"
        )
        assert box["gaps"], "what is missing is said out loud"

    async def test_another_companys_conversation_is_not_readable(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The Inspector shows a conversation's whole history, which makes it
        exactly the endpoint a tenant boundary must hold on."""
        conversation = await _a_lived_conversation(
            client, owner_headers, registered_owner, app, monkeypatch
        )

        response = await client.get(
            f"/api/v1/conversations/{uuid.uuid4()}/inspector", headers=owner_headers
        )
        assert response.status_code == 404

        # And a real id still resolves for its own company, so the 404 above
        # is the boundary rather than the endpoint being broken.
        assert (
            await client.get(
                f"/api/v1/conversations/{conversation.id}/inspector", headers=owner_headers
            )
        ).status_code == 200

    async def test_the_timeline_and_the_decisions_agree(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The timeline is a *view* of what was recorded, not a second
        account of it.

        Every timeline entry that came from a decision carries that decision's
        id, and its text is that decision's own sentence — so the summary view
        and the advanced view can never tell different stories.
        """
        conversation = await _a_lived_conversation(
            client, owner_headers, registered_owner, app, monkeypatch
        )

        box = await _inspect(client, owner_headers, conversation.id)
        sentences = {row["id"]: row["sentence"] for row in box["decisions"]}

        linked = [entry for entry in box["timeline"] if entry["decision_id"]]
        assert linked, "the decisions reach the timeline"
        for entry in linked:
            assert entry["decision_id"] in sentences
            assert entry["detail"] == sentences[entry["decision_id"]]


class TestTheStoryReadsTheWayItHappened:
    """Events that share an instant still read causally.

    Not a rare case: ``created_at`` defaults to the database's ``now()``,
    and PostgreSQL scopes that to the *transaction* — so everything written
    in one unit of work carries the identical timestamp. Sorted on time
    alone, a conversation's first second arrives as an unordered heap.
    """

    def test_simultaneous_events_are_ordered_by_what_causes_what(self) -> None:
        from datetime import UTC, datetime

        from blinkengage.application.services.conversation_inspector import (
            _SEQUENCE_AI,
            _SEQUENCE_INBOUND,
            _SEQUENCE_OUTBOUND,
            _SEQUENCE_OWNERSHIP,
            _SEQUENCE_POLICY,
            _SEQUENCE_ROUTING,
            _SEQUENCE_SLA,
            TimelineEntry,
        )

        instant = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
        shuffled = [
            TimelineEntry(instant, "ai", "AI", "ai", "AI replied", "", sequence=_SEQUENCE_OUTBOUND),
            TimelineEntry(instant, "sla", "SLA", "sla", "started", "", sequence=_SEQUENCE_SLA),
            TimelineEntry(
                instant,
                "conversation",
                "Customer",
                "customer",
                "arrived",
                "",
                sequence=_SEQUENCE_INBOUND,
            ),
            TimelineEntry(
                instant,
                "ownership",
                "Queue",
                "queue",
                "responsible",
                "",
                sequence=_SEQUENCE_OWNERSHIP,
            ),
            TimelineEntry(
                instant,
                "routing",
                "Routing",
                "routing",
                "resolved",
                "",
                sequence=_SEQUENCE_ROUTING,
            ),
            TimelineEntry(
                instant, "policy", "Policy", "policy", "evaluated", "", sequence=_SEQUENCE_POLICY
            ),
            TimelineEntry(instant, "ai", "AI", "ai", "waited", "", sequence=_SEQUENCE_AI),
        ]

        ordered = sorted(shuffled, key=lambda entry: (entry.at, entry.sequence))

        assert [entry.title for entry in ordered] == [
            # The customer's message arrives, routing decides where it goes,
            # a policy is asked, AI acts, somebody becomes responsible, the
            # clocks react, and a reply goes out. Responsibility and clocks
            # come last because they are consequences: AI taking the
            # conversation is what meets the queue target, not the reverse.
            "arrived",
            "resolved",
            "evaluated",
            "waited",
            "responsible",
            "started",
            "AI replied",
        ]


class TestImpactIsNeverGuessed:
    """Every consequence a row states must come from that row.

    The first version of this inferred impact from neighbouring events —
    attaching whichever clocks moved next to whichever action came before
    them. It read beautifully and it lied: "AI replied" was credited with
    starting the queue SLA, which had begun before AI ever saw the
    conversation. The record holds no causal links, so adjacency was standing
    in for one.

    A plausible false attribution is worse here than a missing one. The whole
    value of the Story is that a support manager can trust it without going
    and checking, and a screen that is right most of the time buys nothing.
    """

    async def test_an_event_only_claims_consequences_it_can_prove(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conversation = await _a_lived_conversation(
            client, owner_headers, registered_owner, app, monkeypatch
        )

        box = await _inspect(client, owner_headers, conversation.id)
        by_code = {}
        for entry in box["timeline"]:
            by_code.setdefault(entry["code"], []).append(entry)

        # A message from AI says what a reply means, and claims nothing about
        # clocks it did not settle.
        ai_replies = [
            entry
            for entry in box["timeline"]
            if entry["actor_kind"] == "ai" and entry["title"] == "AI replied"
        ]
        assert ai_replies, (
            "an AI-written reply must still read as AI's even when the send "
            "failed — the provenance is a fact about who composed it, not "
            "about whether the channel accepted it"
        )
        for reply in ai_replies:
            assert reply["impact"] == [
                "The customer received a reply written by AI, not by a person."
            ]
            assert not any(
                "SLA" in line for line in reply["impact"]
            ), "a reply does not get to claim the clocks that were already running"

        # An SLA row describes its own clock and no other.
        for entry in box["timeline"]:
            if entry["stream"] != "sla":
                continue
            clock = dict(entry["facts"]).get("Clock", "")
            for line in entry["impact"]:
                assert clock in line, f"{line!r} is not about the {clock} clock"

    async def test_a_policy_evaluation_is_a_gate_not_an_action(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """It is recorded just before the thing it authorises.

        Crediting a permission slip with the act it permitted put "and
        therefore the SLA clocks started" under a routing policy evaluation.
        """
        conversation = await _a_lived_conversation(
            client, owner_headers, registered_owner, app, monkeypatch
        )

        box = await _inspect(client, owner_headers, conversation.id)
        policies = [entry for entry in box["timeline"] if entry["stream"] == "policy"]

        assert policies, "policy evaluations reach the story"
        for entry in policies:
            assert entry["why"], "a gate says what it decided"
            assert entry["impact"] == [], "and claims no consequences of its own"


class TestSeverityIsTheBackendsJudgement:
    """Severity is part of the event contract, not a console's reading.

    Web, mobile and any future integration must colour the same event the
    same way, and the only place that can be true is here — where the
    platform knows what it actually did. A client deriving "breach means
    red" would be forming a judgement the platform never recorded.
    """

    async def test_every_event_carries_one(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conversation = await _a_lived_conversation(
            client, owner_headers, registered_owner, app, monkeypatch
        )

        box = await _inspect(client, owner_headers, conversation.id)
        levels = {"info", "success", "warning", "error", "critical"}

        assert box["timeline"]
        for entry in box["timeline"]:
            assert entry["severity"] in levels, entry

    async def test_a_met_target_is_a_success_and_a_missed_one_is_an_error(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conversation = await _a_lived_conversation(
            client, owner_headers, registered_owner, app, monkeypatch
        )

        box = await _inspect(client, owner_headers, conversation.id)
        met = [e for e in box["timeline"] if e["code"] == "sla_achieved"]

        assert met, "this conversation met its targets"
        assert all(
            entry["severity"] == "success" for entry in met
        ), "keeping a promise to a customer is the one thing worth showing green"

    async def test_a_deliberate_refusal_is_not_an_error(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The one place this deviates from a literal "policy denied = error".

        A company that switched AI off is the platform obeying it. Marking
        that an error would paint red across every conversation at every
        company that made the choice — and red on healthy conversations is
        red that people stop reading, which costs the levels that matter.
        """
        conversation, _ = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings={"ai": {"enabled": False}},
            ai_enabled=True,
        )

        box = await _inspect(client, owner_headers, conversation.id)
        denials = [
            entry
            for entry in box["timeline"]
            if entry["stream"] == "policy" and "Denied" in entry["detail"]
        ]

        assert denials, "the refusal is recorded"
        assert all(entry["severity"] == "info" for entry in denials)

    async def test_a_conversation_nothing_could_route_is_critical(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Stranded: it reached no queue, so nothing will pick it up without
        somebody intervening. That is what this level is for."""
        conversation, _ = await _run(
            client, owner_headers, registered_owner, app, with_service=False, route=False
        )

        box = await _inspect(client, owner_headers, conversation.id)
        stranded = [entry for entry in box["timeline"] if entry["code"] == "left_unrouted"]

        assert stranded, "a conversation nothing routed says so"
        assert all(entry["severity"] == "critical" for entry in stranded)


class TestItNeverShowsAnIdentifierToAPerson:
    """The Story is read by people, so every name in it must be a name.

    Ownership rows copy the owner's name *by value*, so a timeline still
    reads correctly after somebody leaves the company. Two writers cannot
    afford the lookup and store ``NULL`` instead: ``pick()`` sits on the path
    an agent waits for, and an agent's name lives on a related ``User`` whose
    load would be a lazy fetch inside an async session.

    ``Owner.describe()`` then fell through to ``"human_agent 93b777f2-…"``.
    Found by reading a real conversation's Story on a live installation,
    where two of five ownership rows rendered as raw UUIDs — on the one
    screen whose entire purpose is explaining what happened.
    """

    async def test_an_owner_recorded_without_a_name_is_still_named(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        from blinkengage.application.services.ownership_service import (
            OwnershipService,
            agent_owner,
        )
        from blinkengage.domain.ownership import OwnershipReason
        from blinkengage.infrastructure.repositories.ownership_repository import (
            OwnershipRepository,
        )
        from tests.integration.test_routing_explainability import _agent

        conversation, _ = await _run(
            client, owner_headers, registered_owner, app, settings=_AUTOPILOT_ON, ai_enabled=True
        )
        agent_id = uuid.UUID(
            await _agent(
                client,
                owner_headers,
                email="grace.hopper@example.com",
                name="Grace Hopper",
                status="online",
            )
        )

        factory = app.state.container.session_factory()
        async with factory() as session:
            # Exactly what pick() writes: an owner, and no name.
            await OwnershipService(OwnershipRepository(session)).transfer(
                conversation_id=conversation.id,
                company_id=uuid.UUID(registered_owner["user"]["company"]["id"]),
                to=agent_owner(agent_id, None),
                reason=OwnershipReason.PICKED_BY_AGENT,
            )
            await session.commit()

        box = await _inspect(client, owner_headers, conversation.id)
        ownership = [entry for entry in box["timeline"] if entry["stream"] == "ownership"]

        assert ownership, "the transition is on the timeline"
        assert any(
            "Grace Hopper" in entry["detail"] for entry in ownership
        ), "the agent is named, rather than described by the id the row happened to store"
        assert box["summary"]["owner_label"] == "Grace Hopper"

    async def test_no_ownership_entry_ever_renders_a_raw_identifier(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The general property, not just the one case above.

        A UUID reaching a reader is the same defect as a raw translation key
        reaching one: the screen is technically correct and humanly useless.

        Deliberately built on a *nameless* transition — a queue handed over
        with no name copied, which is what ``_hand_off`` writes. Without one
        this sweeps a timeline whose rows all happen to carry names and would
        pass whether or not the resolver existed.
        """
        import re

        from blinkengage.application.services.ownership_service import (
            OwnershipService,
            agent_owner,
        )
        from blinkengage.domain.ownership import OwnershipReason
        from blinkengage.infrastructure.repositories.ownership_repository import (
            OwnershipRepository,
        )
        from tests.integration.test_routing_explainability import _agent

        conversation, _ = await _run(
            client, owner_headers, registered_owner, app, settings=_AUTOPILOT_ON, ai_enabled=True
        )
        agent_id = uuid.UUID(
            await _agent(
                client,
                owner_headers,
                email="ada.sweep@example.com",
                name="Ada Lovelace",
                status="online",
            )
        )

        factory = app.state.container.session_factory()
        async with factory() as session:
            await OwnershipService(OwnershipRepository(session)).transfer(
                conversation_id=conversation.id,
                company_id=uuid.UUID(registered_owner["user"]["company"]["id"]),
                to=agent_owner(agent_id, None),
                reason=OwnershipReason.PICKED_BY_AGENT,
            )
            await session.commit()

        box = await _inspect(client, owner_headers, conversation.id)
        uuid_shaped = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
        )
        offenders = [
            entry["detail"]
            for entry in box["timeline"]
            if entry["stream"] == "ownership" and uuid_shaped.search(entry["detail"])
        ]

        assert not offenders, f"identifiers shown to a reader: {offenders}"
