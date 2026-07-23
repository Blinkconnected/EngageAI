"""Async SQLAlchemy engine and session factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from blinkengage.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    is_sqlite = settings.database_url.startswith("sqlite")
    engine_kwargs: dict[str, Any] = {"echo": settings.database_echo, "future": True}
    if is_sqlite:
        # In-memory SQLite is per-connection by default — StaticPool shares
        # the single connection across the whole engine so schema created in
        # one session is visible to every other session (used by the test
        # suite; production always targets Postgres).
        engine_kwargs |= {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
    else:
        engine_kwargs |= {
            "pool_size": settings.database_pool_size,
            "max_overflow": settings.database_max_overflow,
            "pool_pre_ping": True,
        }
    return create_async_engine(settings.database_url, **engine_kwargs)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    """Provide a transactional scope for a series of operations."""
    session = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
