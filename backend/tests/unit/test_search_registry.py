"""The search registry is a contract held in three places at once.

``_SEARCHABLES`` names an entity type, a permission and a repository
method. Nothing at import time checks that the method exists, that the
permission is real, or that the API's ``SearchEntityType`` literal knows
the type — the first two fail at request time with an ``AttributeError``
or a silently unreachable branch, and the third fails as a response
validation error only once something actually matches.

Adding an entity type is exactly the moment somebody updates two of the
three and not the third, so all three are checked here.
"""

from typing import get_args

from blinkengage.api.schemas.search import SearchEntityType
from blinkengage.application.services.search_service import _SEARCHABLES
from blinkengage.domain.rbac import PERMISSIONS
from blinkengage.infrastructure.repositories.search_repository import SearchRepository


def test_every_searchable_has_a_repository_method() -> None:
    for searchable in _SEARCHABLES:
        assert hasattr(
            SearchRepository, searchable.method_name
        ), f"{searchable.entity_type} names a method that does not exist"


def test_every_searchable_permission_is_a_real_permission() -> None:
    """A typo here does not raise — it silently makes the type
    unsearchable for everybody, because no role can ever hold a
    permission code that does not exist."""
    codes = {permission.code for permission in PERMISSIONS}
    for searchable in _SEARCHABLES:
        assert (
            searchable.permission in codes
        ), f"{searchable.entity_type} is gated on unknown permission {searchable.permission!r}"


def test_every_searchable_type_is_in_the_api_literal() -> None:
    """The response model rejects any ``entity_type`` outside the
    literal, so a missing entry turns a match into a 500."""
    declared = set(get_args(SearchEntityType))
    for searchable in _SEARCHABLES:
        assert searchable.entity_type in declared


def test_the_api_literal_declares_nothing_that_is_not_searched() -> None:
    """The frontend builds a label, an icon and a route for every member
    of the literal. One that is never returned is dead UI nobody will
    think to delete."""
    searched = {searchable.entity_type for searchable in _SEARCHABLES}
    assert set(get_args(SearchEntityType)) == searched


def test_entity_types_are_unique() -> None:
    """Two entries sharing a type would merge into one group in the UI
    with no indication that the results came from different tables."""
    types = [searchable.entity_type for searchable in _SEARCHABLES]
    assert len(types) == len(set(types))
