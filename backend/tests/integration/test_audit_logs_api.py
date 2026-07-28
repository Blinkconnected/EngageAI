import io
from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from PIL import Image as PILImage

from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)


def _fake_png_bytes() -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", (120, 40), color="blue").save(buffer, format="PNG")
    return buffer.getvalue()


async def _create_agent(client: AsyncClient, owner_headers: dict, email: str) -> dict:
    response = await client.post(
        "/api/v1/agents",
        json={
            "email": email,
            "full_name": "Test Agent",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_registration_and_login_are_audited(
    client: AsyncClient,
    registered_owner: dict,
    owner_headers: dict,
    drain_outbox: Callable[[], Awaitable[int]],
) -> None:
    owner_id = registered_owner["user"]["id"]

    await client.post(
        "/api/v1/auth/login",
        json={"email": "ada@acme.example", "password": "correct-horse-battery-9"},
    )
    await drain_outbox()

    response = await client.get("/api/v1/audit-logs", headers=owner_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    actions = [item["action"] for item in body["items"]]
    assert "company.registered" in actions
    assert actions.count("user.login") == 1  # only the explicit /login call, not /register

    registration_entry = next(
        item for item in body["items"] if item["action"] == "company.registered"
    )
    assert registration_entry["actor_user_id"] == owner_id
    assert registration_entry["entity_type"] == "company"


async def test_department_lifecycle_is_audited(
    client: AsyncClient,
    owner_headers: dict,
    registered_owner: dict,
    drain_outbox: Callable[[], Awaitable[int]],
) -> None:
    owner_id = registered_owner["user"]["id"]

    create_response = await client.post(
        "/api/v1/departments", json={"name": "Support"}, headers=owner_headers
    )
    department_id = create_response.json()["id"]

    await client.patch(
        f"/api/v1/departments/{department_id}",
        json={"is_active": False},
        headers=owner_headers,
    )
    await client.delete(f"/api/v1/departments/{department_id}", headers=owner_headers)
    await drain_outbox()

    response = await client.get(
        "/api/v1/audit-logs",
        params={"entity_type": "department", "entity_id": department_id},
        headers=owner_headers,
    )
    assert response.status_code == 200
    body = response.json()
    actions = [item["action"] for item in body["items"]]
    assert actions == ["department.deleted", "department.updated", "department.created"]
    for item in body["items"]:
        assert item["actor_user_id"] == owner_id
        assert item["entity_id"] == department_id


async def test_team_membership_changes_are_audited(
    client: AsyncClient, owner_headers: dict, drain_outbox: Callable[[], Awaitable[int]]
) -> None:
    team_response = await client.post(
        "/api/v1/teams", json={"name": "Tier 1"}, headers=owner_headers
    )
    team_id = team_response.json()["id"]
    agent = await _create_agent(client, owner_headers, "agent1@acme.example")

    await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"agent_id": agent["id"], "is_lead": False},
        headers=owner_headers,
    )
    await client.delete(f"/api/v1/teams/{team_id}/members/{agent['id']}", headers=owner_headers)
    await drain_outbox()

    response = await client.get(
        "/api/v1/audit-logs",
        params={"action": "team_membership.added"},
        headers=owner_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["details"]["agent_id"] == agent["id"]

    response = await client.get(
        "/api/v1/audit-logs",
        params={"action": "team_membership.removed"},
        headers=owner_headers,
    )
    assert response.json()["total"] == 1


async def test_password_management_is_audited(
    client: AsyncClient,
    owner_headers: dict,
    registered_owner: dict,
    drain_outbox: Callable[[], Awaitable[int]],
) -> None:
    agent = await _create_agent(client, owner_headers, "agent1@acme.example")

    owner_access_token = registered_owner["tokens"]["access_token"]
    await client.post(
        "/api/v1/auth/me/password",
        json={
            "current_password": "correct-horse-battery-9",
            "new_password": "a-brand-new-password-9",
        },
        headers={"Authorization": f"Bearer {owner_access_token}"},
    )
    await client.post(
        f"/api/v1/agents/{agent['id']}/password",
        json={"new_password": "a-reset-password-9"},
        headers=owner_headers,
    )
    await drain_outbox()

    changed_response = await client.get(
        "/api/v1/audit-logs",
        params={"action": "user.password_changed"},
        headers=owner_headers,
    )
    assert changed_response.json()["total"] == 1

    reset_response = await client.get(
        "/api/v1/audit-logs",
        params={"action": "agent.password_reset"},
        headers=owner_headers,
    )
    reset_body = reset_response.json()
    assert reset_body["total"] == 1
    assert reset_body["items"][0]["entity_id"] == agent["id"]
    assert reset_body["items"][0]["actor_user_id"] == registered_owner["user"]["id"]


async def test_audit_logs_are_paginated(
    client: AsyncClient, owner_headers: dict, drain_outbox: Callable[[], Awaitable[int]]
) -> None:
    for name in ("Support", "Sales", "Billing"):
        await client.post("/api/v1/departments", json={"name": name}, headers=owner_headers)
    await drain_outbox()

    response = await client.get(
        "/api/v1/audit-logs",
        params={"action": "department.created", "page": 1, "page_size": 2},
        headers=owner_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["page"] == 1
    assert body["page_size"] == 2


async def test_inbound_message_body_is_redacted_in_the_audit_log(
    client: AsyncClient,
    owner_headers: dict,
    registered_owner: dict,
    app,
    drain_outbox: Callable[[], Awaitable[int]],
) -> None:
    """AuditLog has different retention semantics than Conversation — it
    is never touched by conversation delete or agent removal, and is
    reachable through audit_logs.read alone, bypassing conversations.read
    entirely. A customer's raw message must never be duplicated into it
    verbatim just because every event is audited unconditionally."""
    company_id = registered_owner["user"]["company"]["id"]
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
                    "body": "My SSN is 123-45-6789, please help",
                },
            },
            db_session,
        )
        await db_session.commit()
    await drain_outbox()

    response = await client.get(
        "/api/v1/audit-logs",
        params={"action": "message.persisted"},
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 1
    for item in body["items"]:
        assert "123-45-6789" not in str(item["details"])
        assert item["details"]["body"] == "[redacted]"


async def test_audit_logs_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/audit-logs")
    assert response.status_code in (401, 403)


async def test_audit_logs_are_scoped_to_company(
    client: AsyncClient, drain_outbox: Callable[[], Awaitable[int]]
) -> None:
    first = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Acme Corp",
            "owner_full_name": "Ada Owner",
            "owner_email": "ada@acme.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    first_headers = {"Authorization": f"Bearer {first.json()['tokens']['access_token']}"}
    await client.post("/api/v1/departments", json={"name": "Support"}, headers=first_headers)

    second = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Other Corp",
            "owner_full_name": "Bea Owner",
            "owner_email": "bea@other.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    second_headers = {"Authorization": f"Bearer {second.json()['tokens']['access_token']}"}
    await drain_outbox()

    response = await client.get(
        "/api/v1/audit-logs",
        params={"action": "department.created"},
        headers=second_headers,
    )
    assert response.json()["total"] == 0


class TestExport:
    async def test_pdf_export_returns_a_pdf_file(
        self, client: AsyncClient, owner_headers: dict, drain_outbox: Callable[[], Awaitable[int]]
    ) -> None:
        await drain_outbox()

        response = await client.get(
            "/api/v1/audit-logs", params={"export": "pdf"}, headers=owner_headers
        )

        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")

    async def test_xlsx_export_returns_a_spreadsheet_file(
        self, client: AsyncClient, owner_headers: dict, drain_outbox: Callable[[], Awaitable[int]]
    ) -> None:
        await drain_outbox()

        response = await client.get(
            "/api/v1/audit-logs", params={"export": "xlsx"}, headers=owner_headers
        )

        assert response.status_code == 200, response.text
        assert (
            response.headers["content-type"]
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert response.content.startswith(b"PK")

    async def test_pdf_export_includes_the_company_logo_once_uploaded(
        self, client: AsyncClient, owner_headers: dict, drain_outbox: Callable[[], Awaitable[int]]
    ) -> None:
        await drain_outbox()
        without_logo = await client.get(
            "/api/v1/audit-logs", params={"export": "pdf"}, headers=owner_headers
        )

        upload_response = await client.post(
            "/api/v1/company/logo",
            files={"file": ("logo.png", _fake_png_bytes(), "image/png")},
            headers=owner_headers,
        )
        assert upload_response.status_code == 200, upload_response.text

        with_logo = await client.get(
            "/api/v1/audit-logs", params={"export": "pdf"}, headers=owner_headers
        )

        assert with_logo.status_code == 200, with_logo.text
        assert with_logo.content.startswith(b"%PDF")
        assert len(with_logo.content) > len(without_logo.content)
