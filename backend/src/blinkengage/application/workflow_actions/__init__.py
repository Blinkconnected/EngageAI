"""Import every built-in ``WorkflowAction`` module here so
``@WorkflowActionRegistry.register(...)`` runs at import time — same
discovery pattern as ``infrastructure.channels.providers``.
"""

from blinkengage.application.workflow_actions.builtin import (
    AddTagAction,
    AssignToAgentAction,
    AssignToQueueAction,
    PublishEventAction,
    SendReplyAction,
    SetConversationStatusAction,
)

__all__ = [
    "AddTagAction",
    "AssignToAgentAction",
    "AssignToQueueAction",
    "PublishEventAction",
    "SendReplyAction",
    "SetConversationStatusAction",
]
