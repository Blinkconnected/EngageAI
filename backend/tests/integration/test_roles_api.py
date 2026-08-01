import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.application.services.permission_sync_service import PermissionSyncService
from blinkengage.domain.rbac import DEFAULT_ROLE_PERMISSIONS, PERMISSIONS, SystemRole
from blinkengage.infrastructure.database.models.rbac import Role
from blinkengage.infrastructure.database.models.user import User

AGENT_PAYLOAD = {
    "email": "agent1@acme.example",
    "full_name": "Test Agent",
    "password": "correct-horse-battery-9",
}


async def _invite_agent(client: AsyncClient, owner_headers: dict) -> dict:
    response = await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _agent_headers(client: AsyncClient) -> dict[str, str]:
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": AGENT_PAYLOAD["email"], "password": AGENT_PAYLOAD["password"]},
    )
    assert login_response.status_code == 200, login_response.text
    return {"Authorization": f"Bearer {login_response.json()['access_token']}"}


def _role(roles: list[dict], name: str) -> dict:
    return next(role for role in roles if role["name"] == name)


async def test_list_roles_returns_seeded_system_roles(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.get("/api/v1/roles", headers=owner_headers)
    assert response.status_code == 200, response.text
    roles = response.json()
    names = {role["name"] for role in roles}
    assert names == {"Owner", "Admin", "Agent"}
    for role in roles:
        assert role["is_system"] is True

    owner_role = _role(roles, "Owner")
    assert owner_role["member_count"] == 1
    assert _role(roles, "Admin")["member_count"] == 0


async def test_list_permissions_returns_full_catalog(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.get("/api/v1/permissions", headers=owner_headers)
    assert response.status_code == 200, response.text
    codes = {item["code"] for item in response.json()}
    assert codes == {permission.code for permission in PERMISSIONS}


async def test_create_role_with_permissions(client: AsyncClient, owner_headers: dict) -> None:
    response = await client.post(
        "/api/v1/roles",
        json={
            "name": "Billing Reviewer",
            "description": "Read-only access to reports and customers",
            "permission_codes": ["reports.read", "customers.read"],
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Billing Reviewer"
    assert body["is_system"] is False
    assert body["member_count"] == 0
    assert body["permission_codes"] == ["customers.read", "reports.read"]


async def test_create_role_duplicate_name_conflicts(
    client: AsyncClient, owner_headers: dict
) -> None:
    payload = {"name": "Billing Reviewer", "permission_codes": []}
    await client.post("/api/v1/roles", json=payload, headers=owner_headers)
    response = await client.post("/api/v1/roles", json=payload, headers=owner_headers)
    assert response.status_code == 409


async def test_create_role_rejects_unknown_permission_code(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/roles",
        json={"name": "Bogus", "permission_codes": ["not.a.real.permission"]},
        headers=owner_headers,
    )
    assert response.status_code == 422


async def test_update_role_name_description_and_permissions(
    client: AsyncClient, owner_headers: dict
) -> None:
    create_response = await client.post(
        "/api/v1/roles",
        json={"name": "Tier 1", "permission_codes": ["conversations.read"]},
        headers=owner_headers,
    )
    role_id = create_response.json()["id"]

    update_response = await client.patch(
        f"/api/v1/roles/{role_id}",
        json={
            "name": "Tier 1 Support",
            "description": "Front-line support",
            "permission_codes": ["conversations.read", "conversations.manage"],
        },
        headers=owner_headers,
    )
    assert update_response.status_code == 200, update_response.text
    body = update_response.json()
    assert body["name"] == "Tier 1 Support"
    assert body["description"] == "Front-line support"
    assert body["permission_codes"] == ["conversations.manage", "conversations.read"]


async def test_cannot_rename_a_system_role(client: AsyncClient, owner_headers: dict) -> None:
    roles_response = await client.get("/api/v1/roles", headers=owner_headers)
    admin_id = _role(roles_response.json(), "Admin")["id"]

    response = await client.patch(
        f"/api/v1/roles/{admin_id}", json={"name": "Renamed Admin"}, headers=owner_headers
    )
    assert response.status_code == 400


async def test_cannot_change_owner_permissions_but_can_edit_its_description(
    client: AsyncClient, owner_headers: dict
) -> None:
    roles_response = await client.get("/api/v1/roles", headers=owner_headers)
    owner_id = _role(roles_response.json(), "Owner")["id"]

    forbidden = await client.patch(
        f"/api/v1/roles/{owner_id}",
        json={"permission_codes": ["reports.read"]},
        headers=owner_headers,
    )
    assert forbidden.status_code == 400

    allowed = await client.patch(
        f"/api/v1/roles/{owner_id}",
        json={"description": "The company founder"},
        headers=owner_headers,
    )
    assert allowed.status_code == 200
    assert allowed.json()["description"] == "The company founder"


async def test_can_edit_admin_role_permissions(client: AsyncClient, owner_headers: dict) -> None:
    roles_response = await client.get("/api/v1/roles", headers=owner_headers)
    admin_id = _role(roles_response.json(), "Admin")["id"]

    response = await client.patch(
        f"/api/v1/roles/{admin_id}",
        json={"permission_codes": ["reports.read"]},
        headers=owner_headers,
    )
    assert response.status_code == 200
    assert response.json()["permission_codes"] == ["reports.read"]


async def test_cannot_delete_a_system_role(client: AsyncClient, owner_headers: dict) -> None:
    roles_response = await client.get("/api/v1/roles", headers=owner_headers)
    agent_role_id = _role(roles_response.json(), "Agent")["id"]

    response = await client.delete(f"/api/v1/roles/{agent_role_id}", headers=owner_headers)
    assert response.status_code == 400


async def test_cannot_delete_a_role_with_members(client: AsyncClient, owner_headers: dict) -> None:
    agent = await _invite_agent(client, owner_headers)
    create_response = await client.post(
        "/api/v1/roles",
        json={"name": "Custom", "permission_codes": []},
        headers=owner_headers,
    )
    role_id = create_response.json()["id"]

    assign_response = await client.put(
        f"/api/v1/agents/{agent['id']}/role", json={"role_id": role_id}, headers=owner_headers
    )
    assert assign_response.status_code == 200

    delete_response = await client.delete(f"/api/v1/roles/{role_id}", headers=owner_headers)
    assert delete_response.status_code == 400

    members_response = await client.get(f"/api/v1/roles/{role_id}/members", headers=owner_headers)
    assert members_response.status_code == 200
    members = members_response.json()
    assert len(members) == 1
    assert members[0]["email"] == AGENT_PAYLOAD["email"]


async def test_delete_an_empty_custom_role(client: AsyncClient, owner_headers: dict) -> None:
    create_response = await client.post(
        "/api/v1/roles",
        json={"name": "Unused", "permission_codes": []},
        headers=owner_headers,
    )
    role_id = create_response.json()["id"]

    delete_response = await client.delete(f"/api/v1/roles/{role_id}", headers=owner_headers)
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/v1/roles/{role_id}", headers=owner_headers)
    assert get_response.status_code == 404


async def test_get_and_change_an_agents_role(client: AsyncClient, owner_headers: dict) -> None:
    agent = await _invite_agent(client, owner_headers)

    current = await client.get(f"/api/v1/agents/{agent['id']}/role", headers=owner_headers)
    assert current.status_code == 200
    assert current.json()["role_name"] == "Agent"

    create_response = await client.post(
        "/api/v1/roles",
        json={"name": "Senior Agent", "permission_codes": ["conversations.transfer"]},
        headers=owner_headers,
    )
    new_role_id = create_response.json()["id"]

    update_response = await client.put(
        f"/api/v1/agents/{agent['id']}/role",
        json={"role_id": new_role_id},
        headers=owner_headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["role_name"] == "Senior Agent"

    confirm = await client.get(f"/api/v1/agents/{agent['id']}/role", headers=owner_headers)
    assert confirm.json()["role_name"] == "Senior Agent"

    # The agent's permissions on their next login now reflect the new role.
    new_headers = await _agent_headers(client)
    me_response = await client.get("/api/v1/auth/me", headers=new_headers)
    assert "conversations.transfer" in me_response.json()["permissions"]


async def test_cannot_reassign_the_founding_owners_role(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """A user flagged ``is_company_owner`` must always keep the Owner
    role — see ``CompanyOwnerRoleImmutableError``'s docstring on why (the
    one invariant guaranteeing a company can never end up with nobody
    holding ``roles.manage``). Simulated here by flipping the flag
    directly on an invited agent's ``User`` row, the same direct-session
    approach already used elsewhere in this suite (see
    test_agents_api.py's outbox-event assertions) since no endpoint
    exposes changing this flag after registration."""
    agent = await _invite_agent(client, owner_headers)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        user = await session.get(User, agent["user_id"])
        assert user is not None
        user.is_company_owner = True
        await session.commit()

    roles_response = await client.get("/api/v1/roles", headers=owner_headers)
    admin_role_id = _role(roles_response.json(), "Admin")["id"]

    response = await client.put(
        f"/api/v1/agents/{agent['id']}/role",
        json={"role_id": admin_role_id},
        headers=owner_headers,
    )
    assert response.status_code == 400


async def test_editing_admin_permissions_survives_a_later_permission_sync(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """Regression test for the interaction ``Role.permissions_customized``
    exists to prevent: permission_sync.sync_permissions() runs on every
    service start (via core/migrate.py), and — being a stateless,
    additive-only diff against domain.rbac's current defaults — would
    otherwise silently re-grant whatever an Owner just deliberately
    revoked from Admin/Agent through this very API."""
    roles_response = await client.get("/api/v1/roles", headers=owner_headers)
    admin_id = _role(roles_response.json(), "Admin")["id"]
    removed_code = next(iter(DEFAULT_ROLE_PERMISSIONS[SystemRole.ADMIN]))
    remaining_codes = [
        code for code in DEFAULT_ROLE_PERMISSIONS[SystemRole.ADMIN] if code != removed_code
    ]

    update_response = await client.patch(
        f"/api/v1/roles/{admin_id}",
        json={"permission_codes": remaining_codes},
        headers=owner_headers,
    )
    assert update_response.status_code == 200
    assert removed_code not in update_response.json()["permission_codes"]

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        await PermissionSyncService(session).sync()
        await session.commit()

    get_response = await client.get(f"/api/v1/roles/{admin_id}", headers=owner_headers)
    assert removed_code not in get_response.json()["permission_codes"]

    async with session_factory() as session:
        role = (
            await session.execute(select(Role).where(Role.id == uuid.UUID(admin_id)))
        ).scalar_one()
        assert role.permissions_customized is True


async def test_roles_require_roles_manage_permission(
    client: AsyncClient, owner_headers: dict
) -> None:
    await _invite_agent(client, owner_headers)
    headers = await _agent_headers(client)

    response = await client.get("/api/v1/roles", headers=headers)
    assert response.status_code == 403


async def test_roles_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/roles")
    assert response.status_code in (401, 403)


async def test_roles_are_scoped_to_company(client: AsyncClient, owner_headers: dict) -> None:
    create_response = await client.post(
        "/api/v1/roles",
        json={"name": "Custom", "permission_codes": []},
        headers=owner_headers,
    )
    role_id = create_response.json()["id"]

    other = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Other Corp",
            "owner_full_name": "Bea Owner",
            "owner_email": "bea@other.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

    response = await client.get(f"/api/v1/roles/{role_id}", headers=other_headers)
    assert response.status_code == 404
