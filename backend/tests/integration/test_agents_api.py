from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.infrastructure.database.models.event_outbox import EventOutbox

AGENT_PAYLOAD = {
    "email": "agent1@acme.example",
    "full_name": "Test Agent",
    "password": "correct-horse-battery-9",
}


async def test_create_agent_creates_user_and_assigns_agent_role(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == AGENT_PAYLOAD["email"]
    assert body["full_name"] == AGENT_PAYLOAD["full_name"]
    assert body["status"] == "offline"

    # The new agent can log in with the password the Owner set.
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": AGENT_PAYLOAD["email"], "password": AGENT_PAYLOAD["password"]},
    )
    assert login_response.status_code == 200
    me_response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login_response.json()['access_token']}"},
    )
    assert "Agent" in me_response.json()["roles"]


async def test_create_agent_duplicate_email_conflicts(
    client: AsyncClient, owner_headers: dict
) -> None:
    await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    response = await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    assert response.status_code == 409


async def test_search_agents_by_name(client: AsyncClient, owner_headers: dict) -> None:
    await client.post(
        "/api/v1/agents",
        json={
            "email": "alice@acme.example",
            "full_name": "Alice Anderson",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )
    await client.post(
        "/api/v1/agents",
        json={
            "email": "bob@acme.example",
            "full_name": "Bob Baker",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )

    response = await client.get(
        "/api/v1/agents", params={"search": "alice"}, headers=owner_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["full_name"] == "Alice Anderson"


async def test_search_agents_by_title(client: AsyncClient, owner_headers: dict) -> None:
    create_response = await client.post(
        "/api/v1/agents",
        json={
            "email": "alice@acme.example",
            "full_name": "Alice Anderson",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )
    agent_id = create_response.json()["id"]
    await client.patch(
        f"/api/v1/agents/{agent_id}",
        json={"title": "Senior Support Specialist"},
        headers=owner_headers,
    )
    await client.post(
        "/api/v1/agents",
        json={
            "email": "bob@acme.example",
            "full_name": "Bob Baker",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )

    response = await client.get(
        "/api/v1/agents", params={"search": "Specialist"}, headers=owner_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["full_name"] == "Alice Anderson"


async def test_update_agent_status_and_title(client: AsyncClient, owner_headers: dict) -> None:
    create_response = await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    agent_id = create_response.json()["id"]

    update_response = await client.patch(
        f"/api/v1/agents/{agent_id}",
        json={"status": "online", "title": "Senior Agent"},
        headers=owner_headers,
    )
    assert update_response.status_code == 200
    body = update_response.json()
    assert body["status"] == "online"
    assert body["title"] == "Senior Agent"


async def test_update_agent_status_publishes_a_dedicated_event(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    create_response = await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    agent_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/agents/{agent_id}", json={"status": "online"}, headers=owner_headers
    )
    assert response.status_code == 200

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(EventOutbox).where(EventOutbox.event_type == "agent.status_changed")
        )
        events = list(result.scalars().all())
    assert len(events) == 1
    assert events[0].payload["agent_id"] == agent_id
    assert events[0].payload["previous_status"] == "offline"
    assert events[0].payload["status"] == "online"


async def test_update_agent_title_only_does_not_publish_status_changed(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    create_response = await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    agent_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/agents/{agent_id}", json={"title": "Senior Agent"}, headers=owner_headers
    )
    assert response.status_code == 200

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(EventOutbox).where(EventOutbox.event_type == "agent.status_changed")
        )
        events = list(result.scalars().all())
    assert len(events) == 0


class TestSelfServiceAvailability:
    """``PATCH /agents/me/status`` — no ``agents.manage`` permission
    required, unlike ``PATCH /agents/{agent_id}`` (see
    docs/architecture/queues-routing.md decision #10)."""

    async def _agent_headers(self, client: AsyncClient, owner_headers: dict) -> dict:
        await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": AGENT_PAYLOAD["email"], "password": AGENT_PAYLOAD["password"]},
        )
        return {"Authorization": f"Bearer {login_response.json()['access_token']}"}

    @pytest.mark.parametrize("status_value", ["online", "away", "busy"])
    async def test_updates_own_status_with_no_special_permission(
        self, client: AsyncClient, owner_headers: dict, status_value: str
    ) -> None:
        agent_headers = await self._agent_headers(client, owner_headers)

        response = await client.patch(
            "/api/v1/agents/me/status", json={"status": status_value}, headers=agent_headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == status_value

    async def test_rejects_offline_as_a_self_service_value(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        agent_headers = await self._agent_headers(client, owner_headers)

        response = await client.patch(
            "/api/v1/agents/me/status", json={"status": "offline"}, headers=agent_headers
        )
        assert response.status_code == 422

    async def test_404s_for_a_caller_with_no_agent_profile(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        # The Owner who registered the company never automatically became
        # an Agent — a real, common "no profile" case, not a contrived one.
        response = await client.patch(
            "/api/v1/agents/me/status", json={"status": "online"}, headers=owner_headers
        )
        assert response.status_code == 404

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.patch("/api/v1/agents/me/status", json={"status": "online"})
        assert response.status_code in (401, 403)


async def test_delete_agent_is_soft_delete(client: AsyncClient, owner_headers: dict) -> None:
    create_response = await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    agent_id = create_response.json()["id"]

    delete_response = await client.delete(f"/api/v1/agents/{agent_id}", headers=owner_headers)
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/v1/agents/{agent_id}", headers=owner_headers)
    assert get_response.status_code == 404


async def test_owner_can_reset_agent_password(client: AsyncClient, owner_headers: dict) -> None:
    create_response = await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    agent_id = create_response.json()["id"]

    reset_response = await client.post(
        f"/api/v1/agents/{agent_id}/password",
        json={"new_password": "a-reset-password-9"},
        headers=owner_headers,
    )
    assert reset_response.status_code == 204

    # The new password works...
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": AGENT_PAYLOAD["email"], "password": "a-reset-password-9"},
    )
    assert login_response.status_code == 200

    # ...and the old one no longer does.
    old_login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": AGENT_PAYLOAD["email"], "password": AGENT_PAYLOAD["password"]},
    )
    assert old_login_response.status_code == 401


async def test_reset_agent_password_revokes_existing_sessions(
    client: AsyncClient, owner_headers: dict
) -> None:
    create_response = await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    agent_id = create_response.json()["id"]

    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": AGENT_PAYLOAD["email"], "password": AGENT_PAYLOAD["password"]},
    )
    agent_refresh_token = login_response.json()["refresh_token"]

    reset_response = await client.post(
        f"/api/v1/agents/{agent_id}/password",
        json={"new_password": "a-reset-password-9"},
        headers=owner_headers,
    )
    assert reset_response.status_code == 204

    refresh_response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": agent_refresh_token}
    )
    assert refresh_response.status_code == 401


async def test_reset_agent_password_rejects_weak_password(
    client: AsyncClient, owner_headers: dict
) -> None:
    create_response = await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    agent_id = create_response.json()["id"]

    response = await client.post(
        f"/api/v1/agents/{agent_id}/password",
        json={"new_password": "short1"},
        headers=owner_headers,
    )
    assert response.status_code == 422


async def test_agent_cannot_reset_another_agents_password(
    client: AsyncClient, owner_headers: dict
) -> None:
    create_response = await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    agent_id = create_response.json()["id"]

    await client.post(
        "/api/v1/agents",
        json={
            "email": "agent2@acme.example",
            "full_name": "Another Agent",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": "agent2@acme.example", "password": "correct-horse-battery-9"},
    )
    agent_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

    response = await client.post(
        f"/api/v1/agents/{agent_id}/password",
        json={"new_password": "a-reset-password-9"},
        headers=agent_headers,
    )
    assert response.status_code == 403


async def test_agent_role_can_read_but_not_manage_other_agents(
    client: AsyncClient, owner_headers: dict
) -> None:
    await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": AGENT_PAYLOAD["email"], "password": AGENT_PAYLOAD["password"]},
    )
    agent_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

    read_response = await client.get("/api/v1/agents", headers=agent_headers)
    assert read_response.status_code == 200

    manage_response = await client.post(
        "/api/v1/agents",
        json={
            "email": "agent2@acme.example",
            "full_name": "Another Agent",
            "password": "correct-horse-battery-9",
        },
        headers=agent_headers,
    )
    assert manage_response.status_code == 403


class TestInviteByEmail:
    """Omitting ``password`` invites the agent instead: a random password
    is generated and emailed over the platform's SMTP relay. See
    ``docs/architecture/company-onboarding.md``."""

    async def test_omitting_password_creates_the_agent_and_sends_an_email(
        self, client: AsyncClient, owner_headers: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: list[dict[str, Any]] = []

        async def fake_send(message: Any, **kwargs: Any) -> tuple[Any, Any]:
            sent.append({"to": message["To"], "subject": message["Subject"]})
            return None, None

        monkeypatch.setattr("blinkengage.infrastructure.email.mailer.aiosmtplib.send", fake_send)

        response = await client.post(
            "/api/v1/agents",
            json={"email": "invited-agent@acme.example", "full_name": "Invited Agent"},
            headers=owner_headers,
        )
        assert response.status_code == 201, response.text
        assert response.json()["email"] == "invited-agent@acme.example"

        assert len(sent) == 1
        assert sent[0]["to"] == "invited-agent@acme.example"

    async def test_invited_agent_can_log_in_with_the_emailed_password(
        self, client: AsyncClient, owner_headers: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, str] = {}

        async def fake_send(message: Any, **kwargs: Any) -> tuple[Any, Any]:
            captured["body"] = message.get_content()
            return None, None

        monkeypatch.setattr("blinkengage.infrastructure.email.mailer.aiosmtplib.send", fake_send)

        response = await client.post(
            "/api/v1/agents",
            json={"email": "invited-agent2@acme.example", "full_name": "Invited Agent"},
            headers=owner_headers,
        )
        assert response.status_code == 201, response.text

        temp_password = next(
            line.split(": ", 1)[1].strip()
            for line in captured["body"].splitlines()
            if line.startswith("Temporary password: ")
        )

        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "invited-agent2@acme.example", "password": temp_password},
        )
        assert login_response.status_code == 200, login_response.text

    async def test_agent_creation_still_succeeds_when_smtp_send_fails(
        self, client: AsyncClient, owner_headers: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def failing_send(message: Any, **kwargs: Any) -> tuple[Any, Any]:
            raise ConnectionError("smtp unreachable")

        monkeypatch.setattr("blinkengage.infrastructure.email.mailer.aiosmtplib.send", failing_send)

        response = await client.post(
            "/api/v1/agents",
            json={"email": "invited-agent3@acme.example", "full_name": "Invited Agent"},
            headers=owner_headers,
        )
        assert response.status_code == 201, response.text


class TestCompanyMinimumPasswordLength:
    """A company can raise its own minimum password length above the
    platform floor (10). See ``docs/architecture/company-onboarding.md``.
    """

    async def test_agent_creation_with_explicit_password_below_company_minimum_is_rejected(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        settings_response = await client.patch(
            "/api/v1/company",
            json={"settings": {"security": {"min_password_length": 16}}},
            headers=owner_headers,
        )
        assert settings_response.status_code == 200, settings_response.text

        response = await client.post(
            "/api/v1/agents",
            json={
                "email": "short-pw-agent@acme.example",
                "full_name": "Agent",
                "password": "short-but-1",
            },
            headers=owner_headers,
        )
        assert response.status_code == 400

    async def test_password_reset_below_company_minimum_is_rejected(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        create_response = await client.post(
            "/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers
        )
        agent_id = create_response.json()["id"]

        await client.patch(
            "/api/v1/company",
            json={"settings": {"security": {"min_password_length": 16}}},
            headers=owner_headers,
        )

        response = await client.post(
            f"/api/v1/agents/{agent_id}/password",
            json={"new_password": "short-but-1"},
            headers=owner_headers,
        )
        assert response.status_code == 400
