"""Platform staff administering a company's user accounts.

The value of these tests is mostly in the refusals. This is the second
place in the codebase where a ``company_id`` arrives from the caller
rather than from their token (``platform.py`` is the first), and it is
the first where a *user* id does — so the assertions that matter are the
ones proving an operator cannot reach across a tenant boundary, cannot
leave a company with nobody able to run it, and cannot do any of it
without the customer being able to read about it afterwards.

The isolation promise itself (`platform staff never read tenant content`)
is pinned in ``test_platform_admin_api.py``; nothing here may weaken it,
which is why every route below deals in accounts and never in
conversations, customers or messages.
"""

from typing import Any

import pytest
from httpx import AsyncClient

from blinkengage.core.security import hash_password
from blinkengage.infrastructure.database.models.user import User
from tests.integration.test_platform_read_only import make_read_only

_PLATFORM_EMAIL = "user.ops@blinkengage.example"
_PASSWORD = "correct-horse-battery-9"
_AGENT = {
    "email": "casey@acme.example",
    "full_name": "Casey Agent",
    "password": _PASSWORD,
}
_OTHER_COMPANY = {
    "company_name": "Globex Ltd",
    "owner_full_name": "Hank Other",
    "owner_email": "hank@globex.example",
    "owner_password": _PASSWORD,
}


async def _platform_headers(client: AsyncClient, app: Any) -> dict[str, str]:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        session.add(
            User(
                company_id=None,
                email=_PLATFORM_EMAIL,
                hashed_password=hash_password(_PASSWORD),
                full_name="User Operator",
                is_company_owner=False,
                is_platform_admin=True,
            )
        )
        await session.commit()
    response = await client.post(
        "/api/v1/auth/login", json={"email": _PLATFORM_EMAIL, "password": _PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _company_id(client: AsyncClient, owner_headers: dict) -> str:
    me = await client.get("/api/v1/auth/me", headers=owner_headers)
    return str(me.json()["company"]["id"])


async def _owner_user_id(client: AsyncClient, owner_headers: dict) -> str:
    me = await client.get("/api/v1/auth/me", headers=owner_headers)
    return str(me.json()["id"])


async def _invite_agent(client: AsyncClient, owner_headers: dict, **overrides: Any) -> dict:
    """An ordinary second user of the company, created the way a customer
    creates one."""
    response = await client.post(
        "/api/v1/agents", json={**_AGENT, **overrides}, headers=owner_headers
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _register_other_company(client: AsyncClient) -> dict:
    """A second tenant, so every cross-tenant assertion has a real other
    side rather than a made-up id."""
    response = await client.post("/api/v1/auth/register", json=_OTHER_COMPANY)
    assert response.status_code == 201, response.text
    return response.json()["user"]


def _users_url(company_id: str) -> str:
    return f"/api/v1/platform/companies/{company_id}/users"


def _row(listing: Any, email: str) -> dict:
    return next(item for item in listing.json()["items"] if item["email"] == email)


async def _role_id(client: AsyncClient, owner_headers: dict, name: str) -> str:
    roles = await client.get("/api/v1/roles", headers=owner_headers)
    return str(next(role for role in roles.json() if role["name"] == name)["id"])


class TestWhoMayCallThisAtAll:
    """Platform authority, and nothing that can be edited into it."""

    async def test_a_tenant_token_is_refused_on_every_route(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """A company Owner holds every tenant permission there is.
        Administering their own account through the *platform* API is not
        among them — otherwise the cross-tenant surface would be reachable
        by editing a role."""
        company_id = await _company_id(client, owner_headers)
        user_id = await _owner_user_id(client, owner_headers)
        users = _users_url(company_id)

        responses = [
            await client.get(users, headers=owner_headers),
            await client.patch(
                f"{users}/{user_id}/status",
                json={"is_active": False, "reason": "no"},
                headers=owner_headers,
            ),
            await client.post(
                f"{users}/{user_id}/verification", json={"reason": "no"}, headers=owner_headers
            ),
            await client.put(
                f"{users}/{user_id}/role",
                json={"role_id": user_id, "reason": "no"},
                headers=owner_headers,
            ),
            await client.post(
                f"/api/v1/platform/companies/{company_id}/owner",
                json={"user_id": user_id, "reason": "no"},
                headers=owner_headers,
            ),
        ]

        assert [response.status_code for response in responses] == [403] * 5

    async def test_an_unauthenticated_request_is_refused(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        company_id = await _company_id(client, owner_headers)

        listing = await client.get(_users_url(company_id))
        writing = await client.post(
            f"/api/v1/platform/companies/{company_id}/owner",
            json={"user_id": company_id, "reason": "no"},
        )

        assert listing.status_code in (401, 403)
        assert writing.status_code in (401, 403)


class TestTheList:
    async def test_it_shows_the_companys_own_users(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        await _invite_agent(client, owner_headers)
        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)

        response = await client.get(_users_url(company_id), headers=headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 2
        by_email = {row["email"]: row for row in body["items"]}
        assert set(by_email) == {"ada@acme.example", _AGENT["email"]}
        owner = by_email["ada@acme.example"]
        assert owner["is_company_owner"] is True
        assert owner["is_active"] is True
        assert owner["email_verified"] is True
        assert owner["role"]["name"] == "Owner"
        assert owner["last_login_at"] is None or isinstance(owner["last_login_at"], str)
        assert by_email[_AGENT["email"]]["role"]["name"] == "Agent"

    async def test_it_shows_nothing_of_another_company(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The isolation model in one predicate. Both companies are real,
        so this fails loudly if the filter is ever dropped."""
        other = await _register_other_company(client)
        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)

        ours = await client.get(_users_url(company_id), headers=headers)
        theirs = await client.get(_users_url(str(other["company"]["id"])), headers=headers)

        assert [row["email"] for row in ours.json()["items"]] == ["ada@acme.example"]
        assert [row["email"] for row in theirs.json()["items"]] == [_OTHER_COMPANY["owner_email"]]

    async def test_a_platform_administrator_never_appears(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Platform accounts carry ``company_id IS NULL``, so the company
        filter already excludes them — but the list also excludes them by
        flag, because a platform account appearing here would be
        *actionable* through these routes, and one operator deactivating
        another is not tenant administration.

        Pinned with a deliberately impossible row (a platform admin
        carrying a company id) so the second check is exercised rather
        than merely present.
        """
        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)
        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            impossible = User(
                company_id=company_id,
                email="drifted.ops@blinkengage.example",
                hashed_password=hash_password(_PASSWORD),
                full_name="Drifted Operator",
                is_company_owner=False,
                is_platform_admin=True,
            )
            session.add(impossible)
            await session.commit()
            drifted_id = str(impossible.id)

        response = await client.get(_users_url(company_id), headers=headers)

        emails = {row["email"] for row in response.json()["items"]}
        assert _PLATFORM_EMAIL not in emails
        assert "drifted.ops@blinkengage.example" not in emails

        # ...and is not reachable through the write routes either.
        refused = await client.patch(
            f"{_users_url(company_id)}/{drifted_id}/status",
            json={"is_active": False, "reason": "should not be possible"},
            headers=headers,
        )
        assert refused.status_code == 404

    async def test_a_soft_deleted_user_never_appears(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Removing an agent soft-deletes their login and releases the
        email address for reuse. A console still listing them would offer
        actions on an account that no longer exists."""
        agent = await _invite_agent(client, owner_headers)
        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)
        removal = await client.delete(f"/api/v1/agents/{agent['id']}", headers=owner_headers)
        assert removal.status_code == 204, removal.text

        response = await client.get(_users_url(company_id), headers=headers)

        assert [row["email"] for row in response.json()["items"]] == ["ada@acme.example"]
        acting = await client.patch(
            f"{_users_url(company_id)}/{agent['user_id']}/status",
            json={"is_active": False, "reason": "gone"},
            headers=headers,
        )
        assert acting.status_code == 404

    async def test_an_unknown_company_is_a_404(self, client: AsyncClient, app: Any) -> None:
        """Not an empty list — "this customer has no users" and "no such
        customer" send an operator to different places."""
        headers = await _platform_headers(client, app)

        response = await client.get(
            _users_url("11111111-1111-1111-1111-111111111111"), headers=headers
        )

        assert response.status_code == 404


class TestDeactivation:
    async def test_it_locks_the_account_out_and_reactivation_restores_it(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        agent = await _invite_agent(client, owner_headers)
        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)
        status_url = f"{_users_url(company_id)}/{agent['user_id']}/status"
        credentials = {"email": _AGENT["email"], "password": _PASSWORD}
        assert (await client.post("/api/v1/auth/login", json=credentials)).status_code == 200

        deactivated = await client.patch(
            status_url,
            json={"is_active": False, "reason": "Suspected credential sharing"},
            headers=headers,
        )

        assert deactivated.status_code == 200, deactivated.text
        assert deactivated.json()["is_active"] is False
        assert (await client.post("/api/v1/auth/login", json=credentials)).status_code == 401

        reactivated = await client.patch(
            status_url,
            json={"is_active": True, "reason": "Cleared by the customer"},
            headers=headers,
        )

        assert reactivated.json()["is_active"] is True
        assert (await client.post("/api/v1/auth/login", json=credentials)).status_code == 200

    async def test_another_companys_user_is_a_404_not_a_403(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The distinction is the point. A 403 for "exists but is not
        yours" answers, for any id an operator cares to try, whether that
        id exists — which is a leak across tenants all by itself."""
        other = await _register_other_company(client)
        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)

        response = await client.patch(
            f"{_users_url(company_id)}/{other['id']}/status",
            json={"is_active": False, "reason": "wrong tenant"},
            headers=headers,
        )

        assert response.status_code == 404
        assert (
            await client.patch(
                f"{_users_url(company_id)}/11111111-1111-1111-1111-111111111111/status",
                json={"is_active": False, "reason": "no such user"},
                headers=headers,
            )
        ).status_code == 404


class TestTheLastOwner:
    async def test_the_only_active_owner_cannot_be_deactivated(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The flag would survive, so the company would still record an
        owner — but nobody could sign in as them, and nothing needing
        ``roles.manage`` could ever be done from inside the tenant
        again."""
        company_id = await _company_id(client, owner_headers)
        owner_id = await _owner_user_id(client, owner_headers)
        headers = await _platform_headers(client, app)

        response = await client.patch(
            f"{_users_url(company_id)}/{owner_id}/status",
            json={"is_active": False, "reason": "Customer asked"},
            headers=headers,
        )

        assert response.status_code == 400, response.text
        # The refusal has to say what to do instead; "not allowed" alone
        # sends an operator to try the same thing on another account.
        assert "transfer ownership" in response.json()["detail"].lower()

    async def test_the_owner_cannot_be_demoted_out_of_the_owner_role(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Different from deactivation: this account still signs in
        perfectly well, it simply stops holding the permission needed to
        grant the permission back."""
        await _invite_agent(client, owner_headers)
        company_id = await _company_id(client, owner_headers)
        owner_id = await _owner_user_id(client, owner_headers)
        agent_role = await _role_id(client, owner_headers, "Agent")
        headers = await _platform_headers(client, app)

        response = await client.put(
            f"{_users_url(company_id)}/{owner_id}/role",
            json={"role_id": agent_role, "reason": "Customer asked"},
            headers=headers,
        )

        assert response.status_code == 400, response.text
        assert "transfer ownership" in response.json()["detail"].lower()

    async def test_after_a_transfer_the_previous_owner_can_be_demoted(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The guard protects the company, not the person. Once somebody
        else holds ownership the original account is an ordinary user."""
        agent = await _invite_agent(client, owner_headers)
        company_id = await _company_id(client, owner_headers)
        owner_id = await _owner_user_id(client, owner_headers)
        admin_role = await _role_id(client, owner_headers, "Admin")
        headers = await _platform_headers(client, app)
        transferred = await client.post(
            f"/api/v1/platform/companies/{company_id}/owner",
            json={"user_id": agent["user_id"], "reason": "Founder left the company"},
            headers=headers,
        )
        assert transferred.status_code == 200, transferred.text

        demoted = await client.put(
            f"{_users_url(company_id)}/{owner_id}/role",
            json={"role_id": admin_role, "reason": "Now an ordinary administrator"},
            headers=headers,
        )
        deactivated = await client.patch(
            f"{_users_url(company_id)}/{owner_id}/status",
            json={"is_active": False, "reason": "Left the company"},
            headers=headers,
        )

        assert demoted.status_code == 200, demoted.text
        assert demoted.json()["role"]["name"] == "Admin"
        assert deactivated.status_code == 200, deactivated.text


class TestOwnershipTransfer:
    async def test_it_moves_the_flag_off_the_previous_owner(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        agent = await _invite_agent(client, owner_headers)
        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)

        response = await client.post(
            f"/api/v1/platform/companies/{company_id}/owner",
            json={"user_id": agent["user_id"], "reason": "Founder left the company"},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["is_company_owner"] is True
        listing = await client.get(_users_url(company_id), headers=headers)
        owners = {row["email"]: row["is_company_owner"] for row in listing.json()["items"]}
        assert owners == {_AGENT["email"]: True, "ada@acme.example": False}

    async def test_the_new_owner_receives_the_owner_role(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Ownership without the Owner role is a company whose owner
        cannot manage its roles and whose only possible rescuer is
        themselves."""
        agent = await _invite_agent(client, owner_headers)
        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)

        response = await client.post(
            f"/api/v1/platform/companies/{company_id}/owner",
            json={"user_id": agent["user_id"], "reason": "Founder left the company"},
            headers=headers,
        )

        assert response.json()["role"]["name"] == "Owner"

    async def test_it_is_refused_for_a_deactivated_recipient(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Otherwise the ownerless company the required ``user_id``
        prevents is reachable by a longer route."""
        agent = await _invite_agent(client, owner_headers)
        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)
        await client.patch(
            f"{_users_url(company_id)}/{agent['user_id']}/status",
            json={"is_active": False, "reason": "On leave"},
            headers=headers,
        )

        response = await client.post(
            f"/api/v1/platform/companies/{company_id}/owner",
            json={"user_id": agent["user_id"], "reason": "Founder left the company"},
            headers=headers,
        )

        assert response.status_code == 400, response.text
        assert "reactivate" in response.json()["detail"].lower()

    async def test_it_is_refused_for_another_companys_user(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        other = await _register_other_company(client)
        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)

        response = await client.post(
            f"/api/v1/platform/companies/{company_id}/owner",
            json={"user_id": other["id"], "reason": "wrong tenant"},
            headers=headers,
        )

        assert response.status_code == 404


class TestRoleChange:
    async def test_it_moves_a_user_to_another_role(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        agent = await _invite_agent(client, owner_headers)
        company_id = await _company_id(client, owner_headers)
        admin_role = await _role_id(client, owner_headers, "Admin")
        headers = await _platform_headers(client, app)

        response = await client.put(
            f"{_users_url(company_id)}/{agent['user_id']}/role",
            json={"role_id": admin_role, "reason": "Promoted at the customer's request"},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["role"] == {"id": admin_role, "name": "Admin"}

    async def test_a_role_belonging_to_another_company_is_a_404(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Roles are per-company by schema, so a role id from elsewhere is
        not a permission problem — from this caller it does not exist."""
        agent = await _invite_agent(client, owner_headers)
        other = await _register_other_company(client)
        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)
        other_login = await client.post(
            "/api/v1/auth/login",
            json={
                "email": _OTHER_COMPANY["owner_email"],
                "password": _OTHER_COMPANY["owner_password"],
            },
        )
        other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
        assert other["company"]["id"] != company_id
        foreign_role = await _role_id(client, other_headers, "Admin")

        response = await client.put(
            f"{_users_url(company_id)}/{agent['user_id']}/role",
            json={"role_id": foreign_role, "reason": "wrong tenant"},
            headers=headers,
        )

        assert response.status_code == 404


class TestVerificationResend:
    """Reuses ``VerificationService`` — the application's one token
    issuer, which stores only the hash. The operator never sees the token
    and cannot choose where it goes."""

    @staticmethod
    def _capture(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        """The relay is unreachable in tests, so a real send is the
        failure path by default. Captured rather than stubbed away, so the
        recipient can be asserted."""
        sent: list[dict[str, Any]] = []

        async def _send(config: Any, **kwargs: Any) -> None:
            sent.append(kwargs)

        monkeypatch.setattr(
            "blinkengage.application.services.verification_service.send_with_config", _send
        )
        return sent

    async def test_it_goes_to_the_address_already_on_the_account(
        self,
        client: AsyncClient,
        owner_headers: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sent = self._capture(monkeypatch)
        agent = await _invite_agent(client, owner_headers)
        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)

        response = await client.post(
            f"{_users_url(company_id)}/{agent['user_id']}/verification",
            json={"reason": "Customer says the first one never arrived"},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert response.json() == {"sent_to": _AGENT["email"]}
        assert [message["to_address"] for message in sent] == [_AGENT["email"]]

    async def test_a_second_send_is_throttled(
        self,
        client: AsyncClient,
        owner_headers: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The throttle is kept deliberately. Without it, a platform token
        is a way to use this installation to mail an address somebody else
        owns."""
        self._capture(monkeypatch)
        agent = await _invite_agent(client, owner_headers)
        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)
        url = f"{_users_url(company_id)}/{agent['user_id']}/verification"
        first = await client.post(url, json={"reason": "First attempt"}, headers=headers)
        assert first.status_code == 200, first.text

        response = await client.post(url, json={"reason": "Again"}, headers=headers)

        assert response.status_code == 400
        assert "two minutes" in response.json()["detail"]

    async def test_an_already_verified_account_is_refused(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Answering "sent" would send an operator and a customer looking
        through a spam folder for an email that does not exist."""
        company_id = await _company_id(client, owner_headers)
        owner_id = await _owner_user_id(client, owner_headers)
        headers = await _platform_headers(client, app)

        response = await client.post(
            f"{_users_url(company_id)}/{owner_id}/verification",
            json={"reason": "Customer asked"},
            headers=headers,
        )

        assert response.status_code == 400
        assert "already verified" in response.json()["detail"]


class TestAReasonIsAlwaysRequired:
    """Six months later that sentence is the only explanation anybody has
    for why platform staff touched a customer's account."""

    @staticmethod
    def _writes(company_id: str, user_id: str, role_id: str) -> list[tuple[str, str, dict]]:
        users = _users_url(company_id)
        return [
            ("PATCH", f"{users}/{user_id}/status", {"is_active": False}),
            ("POST", f"{users}/{user_id}/verification", {}),
            ("PUT", f"{users}/{user_id}/role", {"role_id": role_id}),
            ("POST", f"/api/v1/platform/companies/{company_id}/owner", {"user_id": user_id}),
        ]

    async def test_every_write_refuses_a_missing_or_blank_reason(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        agent = await _invite_agent(client, owner_headers)
        company_id = await _company_id(client, owner_headers)
        admin_role = await _role_id(client, owner_headers, "Admin")
        headers = await _platform_headers(client, app)

        accepted = []
        for method, path, body in self._writes(company_id, agent["user_id"], admin_role):
            missing = await client.request(method, path, json=body, headers=headers)
            # Whitespace is stripped before the length check — a field
            # satisfied by pressing the space bar records nothing.
            blank = await client.request(
                method, path, json={**body, "reason": "   "}, headers=headers
            )
            for response in (missing, blank):
                if response.status_code != 422:
                    accepted.append(f"{method} {path} -> {response.status_code}")

        assert accepted == [], "a write was accepted without a reason"


class TestTheReadOnlyOperator:
    """Narrowing platform authority, never widening it: reads stay open,
    writes close. A tier that blocked reading would be pointless and one
    that allowed writing would be a lie."""

    async def test_they_can_list_a_companys_users(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        await _invite_agent(client, owner_headers)
        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)
        await make_read_only(app)

        response = await client.get(_users_url(company_id), headers=headers)

        assert response.status_code == 200, response.text
        assert response.json()["total"] == 2

    async def test_they_cannot_change_anything(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        agent = await _invite_agent(client, owner_headers)
        company_id = await _company_id(client, owner_headers)
        admin_role = await _role_id(client, owner_headers, "Admin")
        headers = await _platform_headers(client, app)
        await make_read_only(app)

        reached = []
        for method, path, body in TestAReasonIsAlwaysRequired._writes(
            company_id, agent["user_id"], admin_role
        ):
            response = await client.request(
                method, path, json={**body, "reason": "Should be refused"}, headers=headers
            )
            if response.status_code != 403:
                reached.append(f"{method} {path} -> {response.status_code}")

        assert reached == [], "a read-only operator reached a write route"


class TestTheCustomerCanSeeWhatWasDone:
    """The property that makes this defensible.

    Platform staff acting on a customer's account produces rows in the
    *customer's own* audit log, readable with ``audit_logs.read``. An
    accountability record only the operator can read is not
    accountability.
    """

    async def test_every_write_lands_in_the_tenants_own_audit_log(
        self,
        client: AsyncClient,
        owner_headers: dict,
        app: Any,
        drain_outbox: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        TestVerificationResend._capture(monkeypatch)
        agent = await _invite_agent(client, owner_headers)
        company_id = await _company_id(client, owner_headers)
        admin_role = await _role_id(client, owner_headers, "Admin")
        headers = await _platform_headers(client, app)
        users = _users_url(company_id)
        operator_id = (await client.get("/api/v1/platform/me", headers=headers)).json()["id"]

        writes = [
            await client.patch(
                f"{users}/{agent['user_id']}/status",
                json={"is_active": False, "reason": "Suspected credential sharing"},
                headers=headers,
            ),
            await client.patch(
                f"{users}/{agent['user_id']}/status",
                json={"is_active": True, "reason": "Cleared by the customer"},
                headers=headers,
            ),
            await client.post(
                f"{users}/{agent['user_id']}/verification",
                json={"reason": "Customer says the first one never arrived"},
                headers=headers,
            ),
            await client.put(
                f"{users}/{agent['user_id']}/role",
                json={"role_id": admin_role, "reason": "Promoted at the customer's request"},
                headers=headers,
            ),
            await client.post(
                f"/api/v1/platform/companies/{company_id}/owner",
                json={"user_id": agent["user_id"], "reason": "Founder left the company"},
                headers=headers,
            ),
        ]
        assert [response.status_code for response in writes] == [200] * 5
        await drain_outbox()

        logs = await client.get("/api/v1/audit-logs?page_size=100", headers=owner_headers)

        assert logs.status_code == 200, logs.text
        entries = [row for row in logs.json()["items"] if row["action"].startswith("platform.")]
        assert {row["action"] for row in entries} == {
            "platform.user_status_changed",
            "platform.user_verification_resent",
            "platform.user_role_changed",
            "platform.company_owner_transferred",
        }
        for row in entries:
            # The operator is named, the target is named, and the reason
            # travels with both — a row saying only "a role changed" is
            # not a record of anything.
            assert row["actor_user_id"] == operator_id
            assert row["entity_type"] == "user"
            assert row["entity_id"] == agent["user_id"]
            assert row["details"]["reason"]
        assert {row["details"]["reason"] for row in entries} >= {
            "Suspected credential sharing",
            "Cleared by the customer",
            "Founder left the company",
        }

    async def test_a_refused_write_records_nothing(
        self, client: AsyncClient, owner_headers: dict, app: Any, drain_outbox: Any
    ) -> None:
        """An audit log carrying attempts that never happened is a log
        nobody can reason from."""
        company_id = await _company_id(client, owner_headers)
        owner_id = await _owner_user_id(client, owner_headers)
        headers = await _platform_headers(client, app)

        refused = await client.patch(
            f"{_users_url(company_id)}/{owner_id}/status",
            json={"is_active": False, "reason": "Customer asked"},
            headers=headers,
        )
        assert refused.status_code == 400
        await drain_outbox()

        logs = await client.get("/api/v1/audit-logs?page_size=100", headers=owner_headers)
        actions = {row["action"] for row in logs.json()["items"]}
        assert "platform.user_status_changed" not in actions


async def test_deactivation_does_not_touch_the_users_last_login(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """The console shows ``last_login_at`` to explain why somebody cannot
    get in. An operator action rewriting it would destroy the evidence
    they opened the page to read."""
    agent = await _invite_agent(client, owner_headers)
    company_id = await _company_id(client, owner_headers)
    headers = await _platform_headers(client, app)
    await client.post("/api/v1/auth/login", json={"email": _AGENT["email"], "password": _PASSWORD})
    before = _row(await client.get(_users_url(company_id), headers=headers), _AGENT["email"])
    assert before["last_login_at"] is not None

    await client.patch(
        f"{_users_url(company_id)}/{agent['user_id']}/status",
        json={"is_active": False, "reason": "Suspected credential sharing"},
        headers=headers,
    )

    after = _row(await client.get(_users_url(company_id), headers=headers), _AGENT["email"])
    assert after["last_login_at"] == before["last_login_at"]
    assert after["is_active"] is False
