"""Who is allowed to destroy records, asserted rather than assumed.

`conversations.delete` does not only delete one conversation. It also
gates `POST /agents/{id}/removal` with `mode: "permanent"`, which
destroys every conversation belonging to a departing agent in one call
— a separation-of-duties boundary `docs/architecture/administration.md`
records as deliberate.

That breadth is invisible from the permission's name, and it was crossed
once by a change that looked local: granting Admin the permission so
administrators could approve deletion requests also handed them bulk
destruction and a way around the approval process itself. Nothing
failed, because nothing was checking.

These are the checks. They are about defaults only — a company may grant
whatever it likes to a role it has customised.
"""

from blinkengage.domain.rbac import DEFAULT_ROLE_PERMISSIONS, SystemRole

#: Permissions that destroy records and record no reason for it. Adding
#: one here is a deliberate act; so is granting one below.
DESTRUCTIVE = frozenset({"conversations.delete"})


def test_only_the_owner_may_destroy_conversations_by_default() -> None:
    for role in (SystemRole.ADMIN, SystemRole.AGENT):
        overlap = DEFAULT_ROLE_PERMISSIONS[role] & DESTRUCTIVE
        assert not overlap, (
            f"{role.value} holds {sorted(overlap)} by default. That permission also "
            f"gates bulk conversation destruction via agent removal — see "
            f"docs/architecture/administration.md. If this is intended, say so here."
        )


def test_the_owner_does_hold_them() -> None:
    """The other half. A boundary nobody is on the right side of is a
    feature that has quietly stopped existing."""
    assert DEFAULT_ROLE_PERMISSIONS[SystemRole.OWNER] >= DESTRUCTIVE


def test_administrators_can_still_decide_on_deletion_requests() -> None:
    """The split has to leave the approval queue reachable.

    Revoking direct deletion from Admin is only correct because deciding
    moved to its own permission. If that grant ever goes too, requests
    pile up with nobody but the Owner able to clear them.
    """
    assert "conversations.delete_approve" in DEFAULT_ROLE_PERMISSIONS[SystemRole.ADMIN]


def test_every_agent_can_ask() -> None:
    assert "conversations.delete_request" in DEFAULT_ROLE_PERMISSIONS[SystemRole.AGENT]


def test_asking_is_not_deciding() -> None:
    """An agent who can request must not also be able to grant it."""
    assert "conversations.delete_approve" not in DEFAULT_ROLE_PERMISSIONS[SystemRole.AGENT]
