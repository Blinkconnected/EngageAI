from blinkengage.domain.rbac import (
    DEFAULT_ROLE_PERMISSIONS,
    PERMISSIONS,
    SystemRole,
    is_known_permission,
    resolve_effective_permissions,
)

_ALL_CODES = {p.code for p in PERMISSIONS}


def test_every_default_role_permission_is_a_known_permission() -> None:
    for codes in DEFAULT_ROLE_PERMISSIONS.values():
        assert codes <= _ALL_CODES


def test_owner_role_has_every_permission() -> None:
    assert DEFAULT_ROLE_PERMISSIONS[SystemRole.OWNER] == frozenset(_ALL_CODES)


def test_admin_and_agent_are_strict_subsets_of_owner() -> None:
    owner = DEFAULT_ROLE_PERMISSIONS[SystemRole.OWNER]
    assert DEFAULT_ROLE_PERMISSIONS[SystemRole.ADMIN] < owner
    assert DEFAULT_ROLE_PERMISSIONS[SystemRole.AGENT] < owner


def test_is_known_permission() -> None:
    assert is_known_permission("customers.manage")
    assert not is_known_permission("not.a.real.permission")


def test_resolve_effective_permissions_unions_role_sets() -> None:
    result = resolve_effective_permissions(
        [frozenset({"a", "b"}), frozenset({"b", "c"}), frozenset()]
    )
    assert result == frozenset({"a", "b", "c"})


def test_permission_codes_are_unique() -> None:
    codes = [p.code for p in PERMISSIONS]
    assert len(codes) == len(set(codes))


def test_agent_role_can_pick_and_release_conversations() -> None:
    # Unlike conversations.transfer (Owner/Admin-only by default), pick
    # and release are routine agent work and must be granted to the
    # Agent role out of the box.
    agent_permissions = DEFAULT_ROLE_PERMISSIONS[SystemRole.AGENT]
    assert "conversations.pick" in agent_permissions
    assert "conversations.release" in agent_permissions
