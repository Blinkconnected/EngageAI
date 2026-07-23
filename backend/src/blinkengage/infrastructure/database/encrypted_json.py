"""``EncryptedJSON`` — a SQLAlchemy ``TypeDecorator`` that transparently
encrypts/decrypts a JSON-serializable dict at the bind/result boundary,
the same "abstract storage behind a TypeDecorator" technique ``GUID``
already establishes in ``infrastructure/database/base.py``. Application
code just reads/writes a plain ``dict`` — used for
``ChannelConfig.credentials`` (see ``docs/architecture/channels.md``).
"""

from typing import Any, cast

import orjson
from sqlalchemy import LargeBinary
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from blinkengage.core.config import get_settings
from blinkengage.infrastructure.security.crypto import decrypt, encrypt


class EncryptedJSON(TypeDecorator[dict[str, Any]]):
    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: dict[str, Any] | None, dialect: Dialect) -> bytes | None:
        if value is None:
            return None
        return encrypt(orjson.dumps(value), settings=get_settings())

    def process_result_value(self, value: Any, dialect: Dialect) -> dict[str, Any] | None:
        if value is None:
            return None
        decrypted = decrypt(bytes(value), settings=get_settings())
        return cast(dict[str, Any], orjson.loads(decrypted))
