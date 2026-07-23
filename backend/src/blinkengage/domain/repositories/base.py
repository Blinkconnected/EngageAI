"""Repository pattern abstractions.

Concrete implementations live in ``infrastructure.repositories`` and are
injected via the DI container — domain and application code depend only on
these interfaces, never on SQLAlchemy directly.
"""

from abc import ABC, abstractmethod
from typing import Protocol, TypeVar
from uuid import UUID

EntityT = TypeVar("EntityT")


class Repository(Protocol[EntityT]):
    async def get_by_id(self, entity_id: UUID) -> EntityT | None: ...

    async def add(self, entity: EntityT) -> EntityT: ...

    async def delete(self, entity_id: UUID) -> None: ...


class AbstractUnitOfWork(ABC):
    """Coordinates one atomic transaction across one or more repositories."""

    async def __aenter__(self) -> "AbstractUnitOfWork":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is None:
            await self.commit()
        else:
            await self.rollback()

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...


__all__ = ["Repository", "AbstractUnitOfWork", "EntityT"]
