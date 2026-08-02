"""The service a conversation is actually running inside.

A conversation is bound to a service **version**, not to a service, and the
difference is the whole point: its configuration is frozen when it starts, so
an administrator editing a threshold at noon does not change the answer a
conversation that began at eleven gets.

That makes the lookup two steps — binding, then version — and two steps
written out at each call site is two places to get it wrong. One of them
already existed in the AI pickup sweep; the confidence threshold needed the
same thing, and a third copy is where the version-versus-service distinction
quietly becomes "whatever the service says now".
"""

import uuid

from blinkengage.domain.service_context import ServiceContext
from blinkengage.infrastructure.repositories.service_directory_repository import (
    ContextBindingRepository,
    ServiceRepository,
)


class ServiceContextResolver:
    def __init__(self, *, bindings: ContextBindingRepository, services: ServiceRepository) -> None:
        self._bindings = bindings
        self._services = services

    async def for_conversation(self, conversation_id: uuid.UUID) -> ServiceContext | None:
        """``None`` when the conversation is bound to no service.

        A real and common case, not an error: a company that has not adopted
        the service directory has conversations that predate it, and every
        caller has to have an answer for them.
        """
        binding = await self._bindings.current(conversation_id)
        if binding is None:
            return None
        return await self._services.context_for_version(binding.service_version_id)


__all__ = ["ServiceContextResolver"]
