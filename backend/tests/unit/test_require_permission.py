from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException

from blinkengage.api.deps import require_permission
from blinkengage.core.auth_context import AuthContext
from blinkengage.domain.exceptions import EmailNotVerifiedError


def _auth(*permissions: str) -> AuthContext:
    return AuthContext(user_id=uuid4(), company_id=uuid4(), permissions=frozenset(permissions))


@dataclass
class _FakeCompany:
    verified_at: datetime | None


class _FakeSession:
    """Stands in for the database on the verification-gate branch.

    The dependency's only use of a session is one primary-key lookup, so
    a stub is enough — and it keeps this a unit test rather than
    dragging a database in for a permission check.
    """

    def __init__(self, company: _FakeCompany | None) -> None:
        self._company = company
        self.lookups = 0

    async def get(self, _model: Any, _pk: Any) -> _FakeCompany | None:
        self.lookups += 1
        return self._company


def test_require_permission_rejects_unknown_code_at_definition_time() -> None:
    with pytest.raises(ValueError, match="Unknown permission code"):
        require_permission("not.a.real.permission")


async def test_passes_through_when_permission_present() -> None:
    dependency = require_permission("customers.manage")
    auth = _auth("customers.manage", "customers.read")
    session = _FakeSession(_FakeCompany(verified_at=datetime.now(UTC)))

    result = await dependency(auth, session)

    assert result is auth


async def test_raises_403_when_permission_missing() -> None:
    dependency = require_permission("customers.manage")
    auth = _auth("customers.read")
    session = _FakeSession(_FakeCompany(verified_at=datetime.now(UTC)))

    with pytest.raises(HTTPException) as exc_info:
        await dependency(auth, session)

    assert exc_info.value.status_code == 403
    assert "customers.manage" in exc_info.value.detail
    # The permission check comes first, so a refused caller never costs
    # a database round trip.
    assert session.lookups == 0


@pytest.mark.enforce_verification
async def test_an_unverified_company_is_refused_a_gated_action() -> None:
    """The gate lives in ``require_permission`` rather than on
    individual endpoints — see docs/architecture/auth-rbac.md."""
    dependency = require_permission("customers.manage")
    auth = _auth("customers.manage")
    session = _FakeSession(_FakeCompany(verified_at=None))

    with pytest.raises(EmailNotVerifiedError):
        await dependency(auth, session)


@pytest.mark.enforce_verification
async def test_an_unverified_company_may_still_read() -> None:
    """Somebody who has just signed up should be able to look around.
    Only acting is blocked."""
    dependency = require_permission("customers.read")
    auth = _auth("customers.read")
    session = _FakeSession(_FakeCompany(verified_at=None))

    assert await dependency(auth, session) is auth
    # A read permission is not in the blocked set, so the gate does not
    # even look the company up.
    assert session.lookups == 0


@pytest.mark.enforce_verification
async def test_a_platform_administrator_is_not_gated() -> None:
    """They have no company, so there is nothing to verify — and locking
    the operator out of a workspace they are fixing would be the wrong
    way round."""
    dependency = require_permission("customers.manage")
    auth = AuthContext(
        user_id=uuid4(), company_id=None, permissions=frozenset({"customers.manage"})
    )
    session = _FakeSession(None)

    assert await dependency(auth, session) is auth
    assert session.lookups == 0
