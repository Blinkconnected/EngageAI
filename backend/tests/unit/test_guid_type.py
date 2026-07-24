"""Regression test for GUID.process_result_value — see
docs/architecture/event-bus.md's incident note and
infrastructure/database/base.py's GUID docstring for the full story.

asyncpg returns its own asyncpg.pgproto.pgproto.UUID for UUID columns —
a *subclass* of uuid.UUID, so `isinstance(value, uuid.UUID)` is True for
it even though it isn't recognized by orjson's native UUID fast path.
Passing it through unconverted let the type look correct everywhere
(str(), equality, Pydantic) except when the event outbox relay tried to
orjson.dumps() it directly, where it failed with "Type is not JSON
serializable" on every single publish attempt — confirmed live to have
silently stalled the relay for ~20 hours before being found and fixed.
"""

import uuid

import orjson
import pytest

from blinkengage.infrastructure.database.base import GUID


class _AsyncpgLikeUUID(uuid.UUID):
    """Stands in for asyncpg.pgproto.pgproto.UUID without requiring a real
    asyncpg connection in a unit test — it only needs to satisfy the same
    property that broke `process_result_value`: being a `uuid.UUID`
    subclass whose exact type is not `uuid.UUID` itself."""


def test_process_result_value_returns_exact_uuid_type_not_a_subclass() -> None:
    raw = _AsyncpgLikeUUID(str(uuid.uuid4()))
    assert isinstance(raw, uuid.UUID)  # the exact condition that fooled `isinstance`
    assert type(raw) is not uuid.UUID  # ...and the exact condition orjson cares about

    result = GUID().process_result_value(raw, dialect=None)  # type: ignore[arg-type]

    assert type(result) is uuid.UUID
    assert result == raw


def test_process_result_value_output_is_orjson_serializable() -> None:
    raw = _AsyncpgLikeUUID(str(uuid.uuid4()))
    with pytest.raises(TypeError, match="not JSON serializable"):
        orjson.dumps({"id": raw})  # the exact failure mode this type decorator must avoid

    result = GUID().process_result_value(raw, dialect=None)  # type: ignore[arg-type]
    orjson.dumps({"id": result})  # must not raise


def test_process_result_value_passes_through_a_real_uuid_unchanged() -> None:
    real = uuid.uuid4()
    result = GUID().process_result_value(real, dialect=None)  # type: ignore[arg-type]
    assert result is real


def test_process_result_value_converts_a_plain_string() -> None:
    value = str(uuid.uuid4())
    result = GUID().process_result_value(value, dialect=None)  # type: ignore[arg-type]
    assert type(result) is uuid.UUID
    assert str(result) == value


def test_process_result_value_passes_through_none() -> None:
    assert GUID().process_result_value(None, dialect=None) is None  # type: ignore[arg-type]
