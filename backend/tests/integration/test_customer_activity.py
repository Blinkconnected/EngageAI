"""Customer Activity through the real message paths.

See ``docs/architecture/customer-activity.md``.

The unit tests prove the rules; these prove the platform actually *maintains*
them — that a real inbound message starts a wait, a real reply ends it, and a
send the provider rejected does not.

The last of those is the one with a customer on the other end of it. A failed
outbound reached nobody, so treating it as an answer would clear a wait that
is still running: the customer sits in silence while the Inbox shows them as
answered and AI considers them handled. That is a customer being silently
dropped, and it is the reason the wait settles on a message that was *sent*
rather than on one that was written.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.application.services.customer_activity_backfill import (
    CustomerActivityBackfill,
)
from blinkengage.infrastructure.database.models.conversation import Conversation
from tests.integration.test_routing_explainability import (
    _archive_every_service,
    _ingest,
    _web_chat_session,
)

pytestmark = pytest.mark.asyncio


async def _conversation(app: Any) -> Conversation:
    factory = app.state.container.session_factory()
    async with factory() as session:
        return (await session.execute(select(Conversation))).scalars().one()


class TestACustomerMessageStartsTheWait:
    async def test_an_inbound_message_records_who_is_waiting(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        chat = await _web_chat_session(client, owner_headers)
        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=registered_owner["user"]["company"]["id"], chat=chat)
            await session.commit()

        conversation = await _conversation(app)

        assert conversation.awaiting_reply_since is not None
        assert conversation.last_customer_message_id is not None
        assert conversation.unanswered_message_count == 1

    async def test_chasing_does_not_reset_the_wait(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Through the real ingest path, not the pure rule: a customer who
        writes twice has waited since the first message, and the Inbox's whole
        purpose is telling that customer apart from one who just arrived."""
        chat = await _web_chat_session(client, owner_headers)
        company_id = registered_owner["user"]["company"]["id"]
        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=company_id, chat=chat, external_id="ext-1")
            await session.commit()
            first = (await session.execute(select(Conversation))).scalars().one()
            started = first.awaiting_reply_since

            await _ingest(session, company_id=company_id, chat=chat, external_id="ext-2")
            await session.commit()

        conversation = await _conversation(app)
        assert conversation.awaiting_reply_since == started
        assert conversation.unanswered_message_count == 2

    async def test_the_two_timestamps_are_separate_facts(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """``awaiting_reply_since`` is the oldest unanswered message and
        ``last_customer_message_at`` is the newest. Never collapsed."""
        chat = await _web_chat_session(client, owner_headers)
        company_id = registered_owner["user"]["company"]["id"]
        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=company_id, chat=chat, external_id="ext-1")
            await _ingest(session, company_id=company_id, chat=chat, external_id="ext-2")
            await session.commit()

        conversation = await _conversation(app)
        assert conversation.awaiting_reply_since is not None
        assert conversation.last_customer_message_at is not None
        assert conversation.awaiting_reply_since <= conversation.last_customer_message_at


class TestTheProjectionMatchesTheMessages:
    """Invariant 2: the stored facts equal a fresh recomputation.

    This is what makes the whole design safe rather than merely convenient —
    the backfill is a recomputation, drift is detected by recomputing, and
    repair is the same operation as the backfill. A projection you cannot
    rebuild is a second source of truth wearing a cache's clothes.
    """

    async def test_a_live_conversation_has_no_drift(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        chat = await _web_chat_session(client, owner_headers)
        company_id = registered_owner["user"]["company"]["id"]
        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=company_id, chat=chat, external_id="ext-1")
            await _ingest(session, company_id=company_id, chat=chat, external_id="ext-2")
            await session.commit()

        report = await CustomerActivityBackfill(factory).run(repair=False)

        assert report.is_clean, [d.describe() for d in report.divergences]
        assert report.conversations >= 1

    async def test_the_backfill_repairs_what_it_finds(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Repair is the backfill. Proved by breaking the projection the way
        a rogue write would and watching the recomputation put it back."""
        chat = await _web_chat_session(client, owner_headers)
        company_id = registered_owner["user"]["company"]["id"]
        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()
            conversation = (await session.execute(select(Conversation))).scalars().one()
            correct = conversation.awaiting_reply_since
            # Exactly what a second writer would leave behind.
            conversation.awaiting_reply_since = None
            conversation.unanswered_message_count = 99
            await session.commit()

        found = await CustomerActivityBackfill(factory).run(repair=False)
        assert not found.is_clean

        repaired = await CustomerActivityBackfill(factory).run(repair=True)
        assert repaired.changed == 1

        conversation = await _conversation(app)
        assert conversation.awaiting_reply_since == correct
        assert conversation.unanswered_message_count == 1

    async def test_a_second_run_finds_nothing_left_to_do(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Idempotent, which is what makes an interrupted backfill safe to
        re-run rather than something to be careful about."""
        chat = await _web_chat_session(client, owner_headers)
        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=registered_owner["user"]["company"]["id"], chat=chat)
            await session.commit()

        await CustomerActivityBackfill(factory).run(repair=True)
        second = await CustomerActivityBackfill(factory).run(repair=True)

        assert second.changed == 0
        assert second.is_clean


class TestAReplyEndsTheWait:
    async def test_an_agent_reply_settles_it(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        await _archive_every_service(client, owner_headers)
        chat = await _web_chat_session(client, owner_headers)
        company_id = registered_owner["user"]["company"]["id"]
        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()
        conversation = await _conversation(app)

        response = await client.post(
            f"/api/v1/conversations/{conversation.id}/messages",
            json={"body": "We are on it."},
            headers=owner_headers,
        )
        assert response.status_code in (200, 201), response.text

        after = await _conversation(app)
        assert after.awaiting_reply_since is None
        assert after.unanswered_message_count == 0
        assert after.last_agent_message_id is not None
        assert after.last_wait_duration_seconds is not None

    async def test_the_projection_still_matches_after_a_reply(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        await _archive_every_service(client, owner_headers)
        chat = await _web_chat_session(client, owner_headers)
        company_id = registered_owner["user"]["company"]["id"]
        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()
        conversation = await _conversation(app)
        await client.post(
            f"/api/v1/conversations/{conversation.id}/messages",
            json={"body": "We are on it."},
            headers=owner_headers,
        )

        report = await CustomerActivityBackfill(factory).run(repair=False)

        assert report.is_clean, [d.describe() for d in report.divergences]


class TestAFailedSendDoesNotAnswerAnybody:
    """The case with a customer on the other end of it.

    A send the provider rejected reached nobody. Treating it as an answer
    would clear a wait that is still running: the customer sits in silence
    while the Inbox shows them answered and AI considers them handled. That is
    a customer being silently dropped — the reason the wait settles on a
    message that was *sent* rather than on one that was merely written.
    """

    async def test_a_failed_message_is_not_treated_as_reaching_anybody(self) -> None:
        from blinkengage.application.services.customer_activity_projector import (
            reached_the_customer,
        )
        from blinkengage.infrastructure.database.models.message import Message, MessageStatus

        assert not reached_the_customer(Message(status=MessageStatus.FAILED))
        assert not reached_the_customer(Message(status=MessageStatus.PENDING))
        assert reached_the_customer(Message(status=MessageStatus.SENT))

    async def test_the_wait_survives_a_failed_send(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Through the projector against a real waiting conversation, because
        the rule mattering is not the same as the rule being wired up."""
        from blinkengage.application.services.customer_activity_projector import (
            CustomerActivityProjector,
        )
        from blinkengage.infrastructure.database.models.message import (
            Message,
            MessageDirection,
            MessageStatus,
        )

        chat = await _web_chat_session(client, owner_headers)
        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=registered_owner["user"]["company"]["id"], chat=chat)
            await session.commit()
            conversation = (await session.execute(select(Conversation))).scalars().one()
            waiting_since = conversation.awaiting_reply_since

            CustomerActivityProjector().record_message(
                conversation,
                Message(
                    id=uuid.uuid4(),
                    conversation_id=conversation.id,
                    direction=MessageDirection.OUTBOUND,
                    status=MessageStatus.FAILED,
                    sent_at=datetime.now(UTC),
                ),
            )

        assert conversation.awaiting_reply_since == waiting_since
        assert conversation.unanswered_message_count == 1
        assert conversation.last_agent_message_id is None

    async def test_a_system_message_does_not_answer_either(self) -> None:
        """A CSAT invitation goes out successfully and still answers nothing.
        Counting it would tell the platform a waiting customer had been dealt
        with by the very message asking them to rate the silence."""
        from blinkengage.application.services.customer_activity_projector import author_of
        from blinkengage.domain.customer_activity import Author
        from blinkengage.infrastructure.database.models.message import (
            Message,
            MessageDirection,
            MessageStatus,
        )

        message = Message(
            direction=MessageDirection.OUTBOUND,
            status=MessageStatus.SENT,
            message_metadata={"is_system_generated": True},
        )

        assert author_of(message) is Author.SYSTEM


class TestFinishingClearsTheWait:
    async def test_resolving_ends_it_but_keeps_the_history(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Nobody waits on a finished conversation. What was said stays said —
        a report read afterwards is the main reason these facts exist."""
        await _archive_every_service(client, owner_headers)
        chat = await _web_chat_session(client, owner_headers)
        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=registered_owner["user"]["company"]["id"], chat=chat)
            await session.commit()
        conversation = await _conversation(app)

        response = await client.patch(
            f"/api/v1/conversations/{conversation.id}",
            json={"status": "resolved"},
            headers=owner_headers,
        )
        assert response.status_code == 200, response.text

        after = await _conversation(app)
        assert after.awaiting_reply_since is None
        assert after.unanswered_message_count == 0
        assert after.last_customer_message_id is not None
        assert after.last_customer_message_at is not None


class TestTheReplayOrderIsNotAnAccident:
    """Two messages can share a timestamp, and one tie changes the answer.

    SQLite truncates ``CURRENT_TIMESTAMP`` to the second and PostgreSQL's
    ``now()`` is transaction-scoped, so anything written in one transaction
    shares an instant. Replay a reply *before* the message it answers and the
    wait it should have closed stays open — the checker then reports a
    conversation as unanswered that was in fact answered, which is the way a
    drift checker earns being switched off.
    """

    async def test_inbound_sorts_before_outbound(self) -> None:
        """``_messages`` breaks the tie by causality, and relies on the stored
        enum *names* ordering that way. Asserted rather than assumed, because
        it is a coincidence of spelling holding up a correctness argument and
        a rename would invert it silently."""
        from blinkengage.infrastructure.database.models.message import MessageDirection

        assert MessageDirection.INBOUND.name < MessageDirection.OUTBOUND.name

    async def test_the_same_messages_in_any_order_give_the_same_facts(self) -> None:
        """The property that makes a recomputation trustworthy. Ties within
        one direction are settled inside the domain by oldest-wins /
        newest-wins rules rather than by whichever arrived first, so a tie
        broken differently is not reported as drift."""
        from blinkengage.domain.customer_activity import CustomerActivity, record_inbound

        same_instant = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
        first, second = uuid.uuid4(), uuid.uuid4()

        forwards = record_inbound(
            record_inbound(CustomerActivity(), message_id=first, at=same_instant),
            message_id=second,
            at=same_instant,
        )
        backwards = record_inbound(
            record_inbound(CustomerActivity(), message_id=second, at=same_instant),
            message_id=first,
            at=same_instant,
        )

        assert forwards == backwards


class TestTheBackfillIsSafeToRun:
    async def test_a_company_with_no_conversations_is_fine(self, app: Any) -> None:
        """Runs against an installation where nothing has happened yet, which
        is the state it will first be run in."""
        report = await CustomerActivityBackfill(app.state.container.session_factory()).run(
            repair=True
        )

        assert report.is_clean
        assert report.changed == 0

    async def test_a_missing_conversation_is_skipped_not_fatal(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The id list is collected up front, so a conversation deleted while
        the pass runs is a row that vanishes between chunks. One disappearing
        conversation must not end a run over the whole installation."""
        chat = await _web_chat_session(client, owner_headers)
        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=registered_owner["user"]["company"]["id"], chat=chat)
            await session.commit()

        backfill = CustomerActivityBackfill(factory)
        chunks = await backfill._chunks(limit=None)
        chunks[0].append(uuid.uuid4())

        report = await backfill.run(repair=True)

        assert report.conversations >= 1
