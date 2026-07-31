"""Request/response schemas for platform administration of a company's
user accounts — see ``api/v1/endpoints/platform_users.py``.

What a platform operator is shown about a tenant's people is deliberately
the *account*, never their work: name, address, role, state and the two
timestamps that say whether the account is usable. There is no field here
that comes from a conversation, a customer or a message, and one added
would be the bug — the same rule ``CompanyOverviewResponse`` follows for
companies.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

#: Why platform staff touched a customer's account. Required on every
#: write on this surface and recorded on the domain event, because six
#: months later this sentence is the only explanation anybody has.
#:
#: Whitespace is stripped *before* the length check, so a reason of three
#: spaces is refused rather than stored — a field that can be satisfied
#: by pressing the space bar is not a record of anything.
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class CompanyUserRoleResponse(BaseModel):
    """The role a user holds, named as well as identified — a console
    showing only an id would send the operator to look it up."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class CompanyUserResponse(BaseModel):
    """One account inside a company, as the platform console renders it.

    ``email_verified`` and ``last_login_at`` are the two fields that
    answer the question this page exists for — "why can this person not
    get in?" — without the operator needing to ask the customer.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    is_active: bool
    is_company_owner: bool
    email_verified: bool
    last_login_at: datetime | None
    created_at: datetime
    #: Null for a user holding no role at all — possible in the schema
    #: (``UserRole`` is a join table with no minimum), so it is rendered
    #: rather than assumed away.
    role: CompanyUserRoleResponse | None = None


class CompanyUserListResponse(BaseModel):
    """Unpaginated, like ``GET /roles``: a company's user list is a
    bounded administrative set. ``total`` travels in the envelope anyway,
    so pagination can be added later without changing the shape clients
    already parse."""

    items: list[CompanyUserResponse]
    total: int


class CompanyUserStatusRequest(BaseModel):
    """Deactivate or reactivate. A single boolean rather than two routes:
    it is one reversible decision, and an operator restoring access should
    be typing a reason into the same form that took it away."""

    is_active: bool
    reason: Reason


class CompanyUserActionRequest(BaseModel):
    """The body for a write whose only input is the accountability — the
    target is already in the path. Required all the same: an action with
    no side input is still an action on somebody else's account."""

    reason: Reason


class CompanyUserRoleRequest(BaseModel):
    role_id: UUID
    reason: Reason


class CompanyOwnerTransferRequest(BaseModel):
    """Ownership moves *to* a named user. There is no "remove the owner"
    body, so a company left with no owner is a state this API cannot
    express."""

    user_id: UUID
    reason: Reason


class VerificationEmailResponse(BaseModel):
    """Which inbox to go and check.

    The address is echoed back rather than assumed by the console because
    the operator did not choose it — it is whatever is already on the
    account, which is the entire reason this action is safe to give them.
    """

    sent_to: str
