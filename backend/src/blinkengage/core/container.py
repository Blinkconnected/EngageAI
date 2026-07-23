"""Application-wide dependency injection container.

Wires configuration, the database engine/session factory, and (in later
milestones) repositories and application services. API route handlers
receive dependencies via FastAPI's ``Depends``, which reads from this
container — nothing is instantiated at import time.
"""

from dependency_injector import containers, providers

from blinkengage.core.config import Settings, get_settings
from blinkengage.infrastructure.database.session import create_engine, create_session_factory


class Container(containers.DeclarativeContainer):
    settings: providers.Singleton[Settings] = providers.Singleton(get_settings)

    engine = providers.Singleton(create_engine, settings=settings)

    session_factory = providers.Singleton(create_session_factory, engine=engine)
