"""Integration tests for the CSAT survey link + public response flow:
``POST /conversations/{id}/csat-survey-link`` (authenticated) and
``POST /csat/{id}/respond`` (public, token-gated). See
``docs/architecture/reports-analytics.md``.
"""

from typing import Any
from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)


async def _company_id(client: AsyncClient, owner_headers: dict) -> str:
    me = await client.get("/api/v1/auth/me", headers=owner_headers)
    return str(me.json()["company"]["id"])


async def _create_conversation(client: AsyncClient, owner_headers: dict, app: Any) -> str:
    company_id = await _company_id(client, owner_headers)
    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
        headers=owner_headers,
    )
    config_id = config_response.json()["id"]
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    session = session_response.json()

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
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
                    "external_message_id": "ext-1",
                    "body": "Hello",
                },
            },
            db_session,
        )
        await db_session.commit()
        conversation = (
            await db_session.execute(
                select(Conversation).where(Conversation.channel_config_id == config_id)
            )
        ).scalar_one()
    return str(conversation.id)


def _extract_token(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return query["token"][0]


async def test_generate_survey_link_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/conversations/00000000-0000-0000-0000-000000000000/csat-survey-link"
    )
    assert response.status_code in (401, 403)


async def test_generate_survey_link_404s_for_unknown_conversation(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/conversations/00000000-0000-0000-0000-000000000000/csat-survey-link",
        headers=owner_headers,
    )
    assert response.status_code == 404


class TestSurveyLinkAndSubmission:
    async def test_full_round_trip(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        conversation_id = await _create_conversation(client, owner_headers, app)

        link_response = await client.post(
            f"/api/v1/conversations/{conversation_id}/csat-survey-link", headers=owner_headers
        )
        assert link_response.status_code == 200, link_response.text
        url = link_response.json()["url"]
        assert f"/feedback/{conversation_id}" in url
        token = _extract_token(url)

        submit_response = await client.post(
            f"/api/v1/csat/{conversation_id}/respond",
            params={"token": token},
            json={"rating": 5, "comment": "Great support!"},
        )
        assert submit_response.status_code == 200, submit_response.text
        body = submit_response.json()
        assert body["conversation_id"] == conversation_id
        assert body["rating"] == 5
        assert body["comment"] == "Great support!"

    async def test_duplicate_submission_is_rejected(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        conversation_id = await _create_conversation(client, owner_headers, app)
        link_response = await client.post(
            f"/api/v1/conversations/{conversation_id}/csat-survey-link", headers=owner_headers
        )
        token = _extract_token(link_response.json()["url"])

        first = await client.post(
            f"/api/v1/csat/{conversation_id}/respond",
            params={"token": token},
            json={"rating": 4},
        )
        assert first.status_code == 200

        second = await client.post(
            f"/api/v1/csat/{conversation_id}/respond",
            params={"token": token},
            json={"rating": 2},
        )
        assert second.status_code == 409

    async def test_invalid_token_is_rejected(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        conversation_id = await _create_conversation(client, owner_headers, app)

        response = await client.post(
            f"/api/v1/csat/{conversation_id}/respond",
            params={"token": "not-a-real-token"},
            json={"rating": 3},
        )
        assert response.status_code == 401

    async def test_token_for_a_different_conversation_is_rejected(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        conversation_id = await _create_conversation(client, owner_headers, app)
        other_conversation_id = await _create_conversation(client, owner_headers, app)

        link_response = await client.post(
            f"/api/v1/conversations/{conversation_id}/csat-survey-link", headers=owner_headers
        )
        token = _extract_token(link_response.json()["url"])

        response = await client.post(
            f"/api/v1/csat/{other_conversation_id}/respond",
            params={"token": token},
            json={"rating": 3},
        )
        assert response.status_code == 401

    async def test_rating_out_of_range_is_rejected(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        conversation_id = await _create_conversation(client, owner_headers, app)
        link_response = await client.post(
            f"/api/v1/conversations/{conversation_id}/csat-survey-link", headers=owner_headers
        )
        token = _extract_token(link_response.json()["url"])

        response = await client.post(
            f"/api/v1/csat/{conversation_id}/respond",
            params={"token": token},
            json={"rating": 6},
        )
        assert response.status_code == 422


class TestCsatContext:
    async def test_needs_contact_info_when_customer_has_neither(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        conversation_id = await _create_conversation(client, owner_headers, app)
        link_response = await client.post(
            f"/api/v1/conversations/{conversation_id}/csat-survey-link", headers=owner_headers
        )
        token = _extract_token(link_response.json()["url"])

        response = await client.get(
            f"/api/v1/csat/{conversation_id}", params={"token": token}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["conversation_id"] == conversation_id
        assert body["already_responded"] is False
        assert body["needs_contact_info"] is True

    async def test_does_not_need_contact_info_once_provided(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        conversation_id = await _create_conversation(client, owner_headers, app)
        link_response = await client.post(
            f"/api/v1/conversations/{conversation_id}/csat-survey-link", headers=owner_headers
        )
        token = _extract_token(link_response.json()["url"])

        await client.post(
            f"/api/v1/csat/{conversation_id}/contact-info",
            params={"token": token},
            json={"email": "customer@example.com"},
        )

        response = await client.get(
            f"/api/v1/csat/{conversation_id}", params={"token": token}
        )
        assert response.json()["needs_contact_info"] is False

    async def test_already_responded_is_true_after_submitting(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        conversation_id = await _create_conversation(client, owner_headers, app)
        link_response = await client.post(
            f"/api/v1/conversations/{conversation_id}/csat-survey-link", headers=owner_headers
        )
        token = _extract_token(link_response.json()["url"])

        await client.post(
            f"/api/v1/csat/{conversation_id}/respond",
            params={"token": token},
            json={"rating": 5},
        )

        response = await client.get(
            f"/api/v1/csat/{conversation_id}", params={"token": token}
        )
        assert response.json()["already_responded"] is True

    async def test_invalid_token_is_rejected(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        conversation_id = await _create_conversation(client, owner_headers, app)
        response = await client.get(
            f"/api/v1/csat/{conversation_id}", params={"token": "not-a-real-token"}
        )
        assert response.status_code == 401


class TestCsatContactInfo:
    async def test_sets_email(self, client: AsyncClient, owner_headers: dict, app: Any) -> None:
        conversation_id = await _create_conversation(client, owner_headers, app)
        link_response = await client.post(
            f"/api/v1/conversations/{conversation_id}/csat-survey-link", headers=owner_headers
        )
        token = _extract_token(link_response.json()["url"])

        response = await client.post(
            f"/api/v1/csat/{conversation_id}/contact-info",
            params={"token": token},
            json={"email": "customer@example.com"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["email"] == "customer@example.com"

    async def test_sets_phone(self, client: AsyncClient, owner_headers: dict, app: Any) -> None:
        conversation_id = await _create_conversation(client, owner_headers, app)
        link_response = await client.post(
            f"/api/v1/conversations/{conversation_id}/csat-survey-link", headers=owner_headers
        )
        token = _extract_token(link_response.json()["url"])

        response = await client.post(
            f"/api/v1/csat/{conversation_id}/contact-info",
            params={"token": token},
            json={"phone": "+15551234567"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["phone"] == "+15551234567"

    async def test_rejects_neither_email_nor_phone(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        conversation_id = await _create_conversation(client, owner_headers, app)
        link_response = await client.post(
            f"/api/v1/conversations/{conversation_id}/csat-survey-link", headers=owner_headers
        )
        token = _extract_token(link_response.json()["url"])

        response = await client.post(
            f"/api/v1/csat/{conversation_id}/contact-info",
            params={"token": token},
            json={},
        )
        assert response.status_code == 422

    async def test_rejects_email_already_used_by_another_customer_in_company(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        await client.post(
            "/api/v1/customers",
            json={"full_name": "Existing Customer", "email": "taken@example.com"},
            headers=owner_headers,
        )
        conversation_id = await _create_conversation(client, owner_headers, app)
        link_response = await client.post(
            f"/api/v1/conversations/{conversation_id}/csat-survey-link", headers=owner_headers
        )
        token = _extract_token(link_response.json()["url"])

        response = await client.post(
            f"/api/v1/csat/{conversation_id}/contact-info",
            params={"token": token},
            json={"email": "taken@example.com"},
        )
        assert response.status_code == 409

    async def test_does_not_overwrite_an_already_set_email(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        conversation_id = await _create_conversation(client, owner_headers, app)
        link_response = await client.post(
            f"/api/v1/conversations/{conversation_id}/csat-survey-link", headers=owner_headers
        )
        token = _extract_token(link_response.json()["url"])

        await client.post(
            f"/api/v1/csat/{conversation_id}/contact-info",
            params={"token": token},
            json={"email": "first@example.com"},
        )
        response = await client.post(
            f"/api/v1/csat/{conversation_id}/contact-info",
            params={"token": token},
            json={"email": "second@example.com"},
        )
        assert response.json()["email"] == "first@example.com"

    async def test_invalid_token_is_rejected(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        conversation_id = await _create_conversation(client, owner_headers, app)
        response = await client.post(
            f"/api/v1/csat/{conversation_id}/contact-info",
            params={"token": "not-a-real-token"},
            json={"email": "customer@example.com"},
        )
        assert response.status_code == 401
