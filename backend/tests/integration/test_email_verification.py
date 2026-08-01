"""Email verification on signup.

The chosen behaviour: an unverified company can **sign in and read**,
but cannot act. Each half is pinned here, because getting either wrong
is invisible until somebody complains — a gate that is too tight locks
out a paying customer, and one that is too loose is no gate at all.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from blinkengage.application.services.verification_service import hash_token
from blinkengage.domain.verification import generate_token
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.database.models.verification import (
    EmailVerificationToken,
)

#: The whole module runs with the gate active — conftest relaxes it for
#: the rest of the suite, and these are the tests that are about it.
pytestmark = pytest.mark.enforce_verification

SIGNUP = {
    "company_name": "Unverified Co",
    "owner_email": "founder@unverified.example",
    "owner_password": "correct-horse-battery-9",
    "owner_full_name": "Fou Nder",
}


async def register(client: AsyncClient, **overrides: Any) -> dict:
    response = await client.post("/api/v1/auth/register", json={**SIGNUP, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


async def issue_token(app: Any, email: str) -> str:
    """Mints a link the way the service does, without sending mail."""
    raw = generate_token()
    async with app.state.container.session_factory()() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        session.add(
            EmailVerificationToken(
                user_id=user.id,
                company_id=user.company_id,
                token_hash=hash_token(raw),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await session.commit()
    return raw


class TestSignup:
    async def test_a_new_company_starts_unverified(self, client: AsyncClient) -> None:
        account = await register(client)
        assert account["user"]["company"]["verified"] is False

    async def test_registration_survives_a_mail_failure(self, client: AsyncClient) -> None:
        """The relay is unreachable in tests, so this is the failure
        path by default. Registration must still succeed: a rolled-back
        signup leaves the customer with nothing and an address that now
        looks taken."""
        account = await register(client, owner_email="mail-fails@unverified.example")
        assert account["tokens"]["access_token"]

    async def test_a_token_is_issued(self, client: AsyncClient, app: Any) -> None:
        await register(client, owner_email="tokened@unverified.example")
        async with app.state.container.session_factory()() as session:
            rows = (await session.execute(select(EmailVerificationToken))).scalars().all()
        assert rows

    async def test_the_raw_token_is_never_stored(self, client: AsyncClient, app: Any) -> None:
        """A verification link is a bearer credential. Only its hash
        exists here, so a database backup is not a way to verify
        somebody else's account."""
        await register(client, owner_email="hashed@unverified.example")
        raw = await issue_token(app, "hashed@unverified.example")
        async with app.state.container.session_factory()() as session:
            stored = (
                (await session.execute(select(EmailVerificationToken.token_hash))).scalars().all()
            )
        assert raw not in stored
        assert hash_token(raw) in stored


class TestGate:
    async def test_an_unverified_company_can_sign_in_and_read(self, client: AsyncClient) -> None:
        account = await register(client, owner_email="reader@unverified.example")
        headers = {"Authorization": f"Bearer {account['tokens']['access_token']}"}

        assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200
        assert (await client.get("/api/v1/conversations", headers=headers)).status_code == 200

    async def test_an_unverified_company_cannot_act(self, client: AsyncClient) -> None:
        account = await register(client, owner_email="actor@unverified.example")
        headers = {"Authorization": f"Bearer {account['tokens']['access_token']}"}

        response = await client.post(
            "/api/v1/customers", headers=headers, json={"full_name": "Nope"}
        )

        assert response.status_code == 403
        # The message names the actual fix. Telling somebody they lack a
        # permission would send them to an administrator who cannot help
        # — they *are* the administrator.
        assert "Confirm your email" in response.json()["detail"]

    async def test_verifying_lifts_the_gate(self, client: AsyncClient, app: Any) -> None:
        account = await register(client, owner_email="lifted@unverified.example")
        headers = {"Authorization": f"Bearer {account['tokens']['access_token']}"}
        raw = await issue_token(app, "lifted@unverified.example")

        verified = await client.get("/api/v1/auth/verify-email", params={"token": raw})

        assert verified.json()["status"] == "verified"
        allowed = await client.post(
            "/api/v1/customers", headers=headers, json={"full_name": "Now fine"}
        )
        assert allowed.status_code == 201
        # And the existing token reflects it without signing in again.
        profile = await client.get("/api/v1/auth/me", headers=headers)
        assert profile.json()["company"]["verified"] is True


class TestConsumingALink:
    async def test_an_unknown_token_is_reported_not_raised(self, client: AsyncClient) -> None:
        """200, not 404: a 404 would let anybody probe which tokens
        exist."""
        response = await client.get(
            "/api/v1/auth/verify-email", params={"token": "not-a-real-token"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "invalid"

    async def test_clicking_the_link_twice_is_not_an_error(
        self, client: AsyncClient, app: Any
    ) -> None:
        """A mail client that prefetches links, or a customer who clicks
        twice, has done nothing wrong — and "invalid link" reads as
        though something broke."""
        await register(client, owner_email="twice@unverified.example")
        raw = await issue_token(app, "twice@unverified.example")

        first = await client.get("/api/v1/auth/verify-email", params={"token": raw})
        second = await client.get("/api/v1/auth/verify-email", params={"token": raw})

        assert first.json()["status"] == "verified"
        assert second.json()["status"] == "already_verified"

    async def test_an_expired_link_says_so(self, client: AsyncClient, app: Any) -> None:
        await register(client, owner_email="stale@unverified.example")
        raw = await issue_token(app, "stale@unverified.example")
        async with app.state.container.session_factory()() as session:
            await session.execute(
                update(EmailVerificationToken)
                .where(EmailVerificationToken.token_hash == hash_token(raw))
                .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            await session.commit()

        response = await client.get("/api/v1/auth/verify-email", params={"token": raw})

        assert response.json()["status"] == "expired"
        # And it did not verify anything on the way past.
        async with app.state.container.session_factory()() as session:
            company = (
                (await session.execute(select(Company).where(Company.slug.like("unverified-co%"))))
                .scalars()
                .first()
            )
        assert company is not None and company.verified_at is None


class TestResend:
    async def test_resending_is_throttled(self, client: AsyncClient) -> None:
        """Legitimate and common — the first one lands in spam — but an
        unthrottled resend is a way to mail somebody repeatedly."""
        account = await register(client, owner_email="resend@unverified.example")
        headers = {"Authorization": f"Bearer {account['tokens']['access_token']}"}

        second = await client.post("/api/v1/auth/resend-verification", headers=headers)

        # Registration already issued one moments ago.
        assert second.status_code == 200
        assert second.json()["sent"] is False

    async def test_resending_requires_a_session(self, client: AsyncClient) -> None:
        """An unauthenticated resend taking an email address is a way to
        mail anybody."""
        response = await client.post("/api/v1/auth/resend-verification")
        # 403 rather than 401: the app's bearer scheme refuses a missing
        # credential outright. Either way, unauthenticated cannot reach it.
        assert response.status_code in (401, 403)
