from uuid import uuid4

import pytest
from fastapi import HTTPException

from blinkengage.api.deps import require_permission
from blinkengage.core.auth_context import AuthContext


def _auth(*permissions: str) -> AuthContext:
    return AuthContext(user_id=uuid4(), company_id=uuid4(), permissions=frozenset(permissions))


def test_require_permission_rejects_unknown_code_at_definition_time() -> None:
    with pytest.raises(ValueError, match="Unknown permission code"):
        require_permission("not.a.real.permission")


async def test_passes_through_when_permission_present() -> None:
    dependency = require_permission("customers.manage")
    auth = _auth("customers.manage", "customers.read")

    result = await dependency(auth)

    assert result is auth


async def test_raises_403_when_permission_missing() -> None:
    dependency = require_permission("customers.manage")
    auth = _auth("customers.read")

    with pytest.raises(HTTPException) as exc_info:
        await dependency(auth)

    assert exc_info.value.status_code == 403
    assert "customers.manage" in exc_info.value.detail
