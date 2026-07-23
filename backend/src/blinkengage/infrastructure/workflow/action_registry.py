"""Process-wide registry mapping an action type string (``"add_tag"``,
``"send_reply"``, ...) to a ``WorkflowAction`` — mirrors
``ChannelRegistry``/``SmsGatewayRegistry`` (the third application of this
same "named lookup from a database-stored string" idiom in this
codebase). See ``docs/architecture/workflow-engine.md``.

``@WorkflowActionRegistry.register("add_tag")`` decorates a class exactly
like ``ChannelRegistry.register`` does, but stores one constructed
instance per action type rather than the class itself: unlike
``ChannelProvider``/``SmsGateway`` (built per-``ChannelConfig``, since
each carries different per-company credentials), ``WorkflowAction``
implementations are stateless — one shared instance is correct and avoids
reconstructing them on every workflow run.
"""

from collections.abc import Callable

from blinkengage.application.workflow_actions.base import WorkflowAction


class WorkflowActionRegistry:
    _actions: dict[str, WorkflowAction] = {}

    @classmethod
    def register(cls, action_type: str) -> Callable[[type[WorkflowAction]], type[WorkflowAction]]:
        def _decorator(action_cls: type[WorkflowAction]) -> type[WorkflowAction]:
            existing = cls._actions.get(action_type)
            if existing is not None and type(existing) is not action_cls:
                raise ValueError(f"Workflow action {action_type!r} is already registered")
            cls._actions[action_type] = action_cls()
            return action_cls

        return _decorator

    @classmethod
    def get(cls, action_type: str) -> WorkflowAction | None:
        return cls._actions.get(action_type)

    @classmethod
    def known_action_types(cls) -> frozenset[str]:
        return frozenset(cls._actions.keys())
