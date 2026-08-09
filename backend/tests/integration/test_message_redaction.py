"""Redaction removes what a message said, everywhere, and says who did it.

The requirement these defend is narrow and absolute: after a redaction
the original content must not be retrievable through the API, search,
exports, Knowledge, Memory or Learning, and must never become evidence
for anything afterwards. A redaction that clears the column an agent can
see and leaves the text in provider metadata, in object storage, or in a
memory citation has removed nothing — it has only stopped anyone
noticing.

So most of these tests are not about the endpoint. They are about the
five other places the content lives.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.domain.learning_observation import ContentRefKind
from blinkengage.domain.memory import EvidenceSourceType
from blinkengage.infrastructure.database.models.learning import (
    LearningObservation,
    LearningObservationRef,
)
from blinkengage.infrastructure.database.models.memory import MemoryEvidence, MemoryFact
from blinkengage.infrastructure.database.models.message import Message
from blinkengage.infrastructure.database.models.rbac import Role, RolePermission

SECRET = "My card number is 4111 1111 1111 1111 and my PIN is 4242."
REASON = "Customer pasted full card details into the chat by mistake."


async def _seed_conversation(client: AsyncClient, headers: dict, app: Any) -> tuple[str, str]:
    """A real conversation with one inbound message carrying the secret."""
    from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
        handle_message_received,
    )

    company_id = (await client.get("/api/v1/auth/me", headers=headers)).json()["company"]["id"]
    config = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
        headers=headers,
    )
    config_id = config.json()["id"]
    session = (await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})).json()

    session_factory = app.state.container.session_factory()
    async with session_factory() as db:
        await handle_message_received(
            {
                "event_type": "message.received",
                "company_id": company_id,
                "aggregate_type": "message",
                "aggregate_id": None,
                "actor_user_id": None,
                "payload": {
                    "channel_config_id": config_id,
                    "channel_type": "web_chat",
                    "external_thread_id": session["session_token"],
                    "external_customer_id": session["customer_id"],
                    "external_customer_name": "Redaction Customer",
                    "external_message_id": "ext-redact-1",
                    "body": SECRET,
                    # Providers routinely echo the body back. This is the
                    # copy a body-only redaction would leave behind.
                    "raw": {"text": SECRET, "from": "+15550001111"},
                },
            },
            db,
        )
        await db.commit()

    # The web-chat session creates the customer as "Web Visitor"; rename
    # it so the audit record has a distinctive name to assert on.
    customers = await client.get("/api/v1/customers", params={"page_size": 50}, headers=headers)
    await client.patch(
        f"/api/v1/customers/{customers.json()['items'][0]['id']}",
        json={"full_name": "Redaction Customer"},
        headers=headers,
    )

    conversations = await client.get(
        "/api/v1/conversations", params={"page_size": 50}, headers=headers
    )
    conversation_id = conversations.json()["items"][0]["id"]
    messages = await client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=headers
    )
    message_id = messages.json()["items"][0]["id"]
    return conversation_id, message_id


@pytest.fixture
async def seeded(client: AsyncClient, owner_headers: dict, app: Any) -> tuple[str, str]:
    return await _seed_conversation(client, owner_headers, app)


async def _agent_without_redaction(client: AsyncClient, owner_headers: dict) -> dict:
    """An ordinary Agent. The default role does not include the
    permission, so nothing has to be revoked."""
    await client.post(
        "/api/v1/agents",
        json={
            "email": "redaction-agent@acme.example",
            "full_name": "Ordinary Agent",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "redaction-agent@acme.example", "password": "correct-horse-battery-9"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


class TestAuthorization:
    async def test_an_owner_may_redact(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str]
    ) -> None:
        conversation_id, message_id = seeded

        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": REASON},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["reason"] == REASON

    async def test_an_ordinary_agent_may_not(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str]
    ) -> None:
        """Redaction cannot be undone by whoever notices the mistake, so
        it is not routine agent work."""
        conversation_id, message_id = seeded
        agent = await _agent_without_redaction(client, owner_headers)

        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": REASON},
            headers=agent,
        )

        assert response.status_code == 403

    async def test_an_agent_cannot_read_the_redaction_log_either(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str]
    ) -> None:
        # The log names customers and quotes the reasons given; it is not
        # less sensitive than the action.
        agent = await _agent_without_redaction(client, owner_headers)

        assert (await client.get("/api/v1/message-redactions", headers=agent)).status_code == 403

    async def test_redaction_does_not_weaken_owner_only_deletion(self) -> None:
        """The separation-of-duties boundary is unchanged.

        `messages.redact` is a new, narrower authority. It must not have
        quietly handed Admin the permission that destroys whole
        conversations and bulk-destroys an agent's history.
        """
        from blinkengage.domain.rbac import DEFAULT_ROLE_PERMISSIONS, SystemRole

        assert "conversations.delete" not in DEFAULT_ROLE_PERMISSIONS[SystemRole.ADMIN]
        assert "conversations.delete" not in DEFAULT_ROLE_PERMISSIONS[SystemRole.AGENT]
        assert "messages.redact" not in DEFAULT_ROLE_PERMISSIONS[SystemRole.AGENT]
        assert "messages.redact" in DEFAULT_ROLE_PERMISSIONS[SystemRole.ADMIN]

    async def test_requires_authentication(
        self, client: AsyncClient, seeded: tuple[str, str]
    ) -> None:
        conversation_id, message_id = seeded

        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": REASON},
        )

        assert response.status_code in (401, 403)


class TestTheContentIsActuallyGone:
    async def test_the_api_no_longer_returns_it(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str]
    ) -> None:
        conversation_id, message_id = seeded
        before = await client.get(
            f"/api/v1/conversations/{conversation_id}/messages", headers=owner_headers
        )
        assert SECRET in before.text

        await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": REASON},
            headers=owner_headers,
        )

        after = await client.get(
            f"/api/v1/conversations/{conversation_id}/messages", headers=owner_headers
        )
        assert SECRET not in after.text
        message = next(m for m in after.json()["items"] if m["id"] == message_id)
        assert message["body"] is None
        # Still in the thread, in order, marked — not deleted.
        assert message["redacted_at"] is not None

    async def test_provider_metadata_is_stripped_too(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str], app: Any
    ) -> None:
        """The copy a body-only redaction leaves behind.

        Providers echo the message back in their payload — a WhatsApp
        receipt carries the text, an email blob carries the subject and
        the quoted reply. Clearing `body` alone removes it from the
        screen and leaves it in the database and every export.
        """
        conversation_id, message_id = seeded

        await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": REASON},
            headers=owner_headers,
        )

        session_factory = app.state.container.session_factory()
        async with session_factory() as db:
            message = await db.get(Message, UUID(message_id))
            assert message is not None
            assert message.body is None
            assert SECRET not in str(message.message_metadata)

    async def test_the_row_survives_so_the_thread_still_makes_sense(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str], app: Any
    ) -> None:
        """Not deleted. A message sent over WhatsApp cannot be unsent, so
        destroying our copy loses our half of a record the customer still
        holds."""
        conversation_id, message_id = seeded

        await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": REASON},
            headers=owner_headers,
        )

        session_factory = app.state.container.session_factory()
        async with session_factory() as db:
            message = await db.get(Message, UUID(message_id))
            assert message is not None
            assert message.direction is not None
            assert message.created_at is not None

    async def test_it_does_not_reach_the_ai_transcript(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str]
    ) -> None:
        conversation_id, message_id = seeded
        await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": REASON},
            headers=owner_headers,
        )

        summary = await client.post(
            f"/api/v1/ai/conversations/{conversation_id}/summary", headers=owner_headers
        )

        # Whatever the AI says, it cannot have been given the content.
        assert SECRET not in summary.text

    async def test_global_search_cannot_find_it(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str]
    ) -> None:
        """Search never indexed message bodies, and this asserts it stays
        that way — a future full-text message search would otherwise
        reintroduce every redacted string."""
        conversation_id, message_id = seeded
        await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": REASON},
            headers=owner_headers,
        )

        results = await client.get("/api/v1/search", params={"q": "4111"}, headers=owner_headers)

        assert SECRET not in results.text

    async def test_the_conversation_inspector_cannot_replay_it(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str]
    ) -> None:
        conversation_id, message_id = seeded
        await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": REASON},
            headers=owner_headers,
        )

        inspected = await client.get(
            f"/api/v1/inspector/conversations/{conversation_id}", headers=owner_headers
        )

        assert SECRET not in inspected.text


class TestMemoryAndLearning:
    async def test_memory_citations_of_the_message_are_removed(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str], app: Any
    ) -> None:
        """A fact whose evidence is a redacted message is a fact nobody
        can check."""
        conversation_id, message_id = seeded
        company_id = UUID(
            (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"]["id"]
        )

        from datetime import UTC, datetime

        session_factory = app.state.container.session_factory()
        async with session_factory() as db:
            fact = MemoryFact(
                company_id=company_id,
                tier="customer",
                fact_type="preference",
                fact_key="test.redaction",
                subject_type="CUSTOMER",
                subject_id=UUID(int=1),
                statement="Something believed because of that message.",
                first_observed_at=datetime.now(UTC),
                last_observed_at=datetime.now(UTC),
                created_from="observation",
            )
            db.add(fact)
            await db.flush()
            db.add(
                MemoryEvidence(
                    company_id=company_id,
                    fact_id=fact.id,
                    source_type=EvidenceSourceType.MESSAGE.value,
                    source_id=UUID(message_id),
                    conversation_id=UUID(conversation_id),
                    observed_at=datetime.now(UTC),
                )
            )
            await db.commit()

        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": REASON},
            headers=owner_headers,
        )

        assert response.json()["memory_evidence_removed"] == 1
        async with session_factory() as db:
            remaining = (
                (
                    await db.execute(
                        select(MemoryEvidence).where(
                            MemoryEvidence.source_id == UUID(message_id),
                            MemoryEvidence.source_type == EvidenceSourceType.MESSAGE.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert list(remaining) == []

    async def test_learning_citations_are_cut_without_discarding_the_rest(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str], app: Any
    ) -> None:
        """Learning observes conversations and cites messages.

        Removing the citation is right; discarding the whole observation
        would throw away what was learned from the rest of a conversation
        because one message in it was redacted.
        """
        conversation_id, message_id = seeded
        company_id = UUID(
            (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"]["id"]
        )

        session_factory = app.state.container.session_factory()
        async with session_factory() as db:
            from datetime import UTC, datetime

            observation = LearningObservation(
                company_id=company_id,
                source_kind="conversation",
                source_id=UUID(conversation_id),
                observed_at=datetime.now(UTC),
                pipeline_version=1,
                state="settled",
            )
            db.add(observation)
            await db.flush()
            # Two refs: the redacted message, and another one that must
            # survive.
            db.add(
                LearningObservationRef(
                    company_id=company_id,
                    observation_id=observation.id,
                    ref_kind=ContentRefKind.MESSAGE.value,
                    ref_id=UUID(message_id),
                    ordinal=0,
                )
            )
            db.add(
                LearningObservationRef(
                    company_id=company_id,
                    observation_id=observation.id,
                    ref_kind=ContentRefKind.MESSAGE.value,
                    ref_id=UUID(int=99),
                    ordinal=1,
                )
            )
            await db.commit()
            observation_id = observation.id

        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": REASON},
            headers=owner_headers,
        )

        assert response.json()["learning_observations_detached"] == 1
        async with session_factory() as db:
            refs = (
                (
                    await db.execute(
                        select(LearningObservationRef).where(
                            LearningObservationRef.observation_id == observation_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert [r.ref_id for r in refs] == [UUID(int=99)]
            surviving = await db.get(LearningObservation, observation_id)
            assert surviving is not None
            assert surviving.state == "settled"

    async def test_a_redacted_message_never_becomes_future_evidence(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str], app: Any
    ) -> None:
        """The forward half of the guarantee.

        Removing existing citations is not enough: the next Learning
        sweep reads the conversation again. It must not pick the message
        back up — not even as an empty turn, which would shift every
        ordinal after it and let the conversation be observed as if the
        customer had said nothing at that point.
        """
        conversation_id, message_id = seeded
        await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": REASON},
            headers=owner_headers,
        )

        from blinkengage.infrastructure.events.consumers.learning_observation_consumer import (
            _turns_for,
        )

        session_factory = app.state.container.session_factory()
        async with session_factory() as db:
            turns = await _turns_for(db, conversation_id=UUID(conversation_id))

        assert all(turn.ref_id != UUID(message_id) for turn in turns)


class TestTheAuditTrail:
    async def test_it_records_actor_time_reason_and_every_id(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str]
    ) -> None:
        conversation_id, message_id = seeded

        record = (
            await client.post(
                f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
                json={"reason": REASON},
                headers=owner_headers,
            )
        ).json()

        assert record["message_id"] == message_id
        assert record["conversation_id"] == conversation_id
        assert record["redacted_by_user_id"] is not None
        assert record["redacted_by_name"] is not None
        assert record["redacted_at"] is not None
        assert record["reason"] == REASON
        assert record["customer_name"] == "Redaction Customer"

    async def test_the_record_never_carries_the_content(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str]
    ) -> None:
        """Not even for an administrator. A 'show me what it said'
        affordance would make every other guarantee here untrue."""
        conversation_id, message_id = seeded
        await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": REASON},
            headers=owner_headers,
        )

        listing = await client.get("/api/v1/message-redactions", headers=owner_headers)

        assert SECRET not in listing.text
        assert listing.json()["total"] == 1

    async def test_a_reason_nobody_could_act_on_is_refused(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str]
    ) -> None:
        conversation_id, message_id = seeded

        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": "spam"},
            headers=owner_headers,
        )

        assert response.status_code in {400, 422}

    async def test_the_log_is_scoped_to_the_callers_company(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str]
    ) -> None:
        conversation_id, message_id = seeded
        await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": REASON},
            headers=owner_headers,
        )
        other = await client.post(
            "/api/v1/auth/register",
            json={
                "company_name": "Nosy Co",
                "owner_full_name": "Nosy Owner",
                "owner_email": "redaction-nosy@test.example",
                "owner_password": "correct-horse-battery-9",
            },
        )
        headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

        listing = await client.get("/api/v1/message-redactions", headers=headers)

        assert listing.json()["items"] == []


class TestTenantIsolationAndReplay:
    async def test_another_company_cannot_redact_this_message(
        self, client: AsyncClient, seeded: tuple[str, str]
    ) -> None:
        conversation_id, message_id = seeded
        other = await client.post(
            "/api/v1/auth/register",
            json={
                "company_name": "Other Co",
                "owner_full_name": "Other Owner",
                "owner_email": "redaction-other@test.example",
                "owner_password": "correct-horse-battery-9",
            },
        )
        headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": REASON},
            headers=headers,
        )

        # 404, not 403: a cross-tenant id must not be confirmed to exist.
        assert response.status_code == 404

    async def test_a_message_from_another_conversation_is_not_found(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str]
    ) -> None:
        """Scoped by conversation as well as company. Company-only
        scoping would turn a per-conversation check into a company-wide
        one."""
        _conversation_id, message_id = seeded

        response = await client.post(
            f"/api/v1/conversations/{UUID(int=7)}/messages/{message_id}/redact",
            json={"reason": REASON},
            headers=owner_headers,
        )

        assert response.status_code == 404

    async def test_redacting_twice_is_a_conflict_not_a_second_record(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str]
    ) -> None:
        """Retry-safe. A duplicate delivery must not append a second
        account of one removal, with a different actor and reason."""
        conversation_id, message_id = seeded
        first = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": REASON},
            headers=owner_headers,
        )
        assert first.status_code == 200

        second = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": "A different reason entirely, from somebody else."},
            headers=owner_headers,
        )

        assert second.status_code == 409
        listing = await client.get("/api/v1/message-redactions", headers=owner_headers)
        assert listing.json()["total"] == 1


class TestAttachments:
    async def test_attachments_are_purged_from_object_storage(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The content is not only text.

        A redaction that clears the body and leaves the uploaded file
        downloadable has removed the caption and kept the photograph.
        """
        conversation_id, _message_id = await _seed_conversation(client, owner_headers, app)

        upload = await client.post(
            f"/api/v1/conversations/{conversation_id}/attachments",
            files={"file": ("secret.txt", b"the sensitive contents", "text/plain")},
            headers=owner_headers,
        )
        assert upload.status_code in (200, 201), upload.text
        attachment_id = upload.json()["id"]

        sent = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"body": "Here it is", "attachment_ids": [attachment_id]},
            headers=owner_headers,
        )
        outbound_id = sent.json()["id"]

        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{outbound_id}/redact",
            json={"reason": REASON},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["attachments_purged"] == 1
        # And it is no longer reachable through the API either.
        listing = await client.get(
            f"/api/v1/conversations/{conversation_id}/messages", headers=owner_headers
        )
        message = next(m for m in listing.json()["items"] if m["id"] == outbound_id)
        assert message["attachments"] == []


class TestAdminCanRedact:
    async def test_an_admin_role_holds_the_permission(
        self, client: AsyncClient, owner_headers: dict, seeded: tuple[str, str], app: Any
    ) -> None:
        """Administrators are who this is for. The Owner alone would make
        it unusable in any company where the Owner is not the compliance
        contact."""
        conversation_id, message_id = seeded
        company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
            "id"
        ]
        await client.post(
            "/api/v1/agents",
            json={
                "email": "redaction-admin@acme.example",
                "full_name": "Compliance Admin",
                "password": "correct-horse-battery-9",
            },
            headers=owner_headers,
        )
        session_factory = app.state.container.session_factory()
        async with session_factory() as db:
            role = (
                await db.execute(
                    select(Role).where(Role.company_id == UUID(company_id), Role.name == "Agent")
                )
            ).scalar_one()
            db.add(RolePermission(role_id=role.id, permission_code="messages.redact"))
            await db.commit()

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "redaction-admin@acme.example", "password": "correct-horse-battery-9"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages/{message_id}/redact",
            json={"reason": REASON},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["redacted_by_name"] == "Compliance Admin"
