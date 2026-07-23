"""Application-wide dependency injection container.

Wires configuration, the database engine/session factory, and the Redis
client. API route handlers receive dependencies via FastAPI's ``Depends``,
which reads from this container — nothing is instantiated at import time.
Per-request objects (sessions, repositories, services) are constructed in
``api/deps.py`` from these singletons, not stored on the container itself.
"""

from dependency_injector import containers, providers

from blinkengage.core.config import Settings, get_settings
from blinkengage.infrastructure.cache.redis import create_redis_client
from blinkengage.infrastructure.database.session import create_engine, create_session_factory
from blinkengage.infrastructure.storage.s3_client import create_minio_client


class Container(containers.DeclarativeContainer):
    settings: providers.Singleton[Settings] = providers.Singleton(get_settings)

    engine = providers.Singleton(create_engine, settings=settings)

    session_factory = providers.Singleton(create_session_factory, engine=engine)

    redis = providers.Singleton(create_redis_client, settings=settings)

    minio_client = providers.Singleton(create_minio_client, settings=settings)
