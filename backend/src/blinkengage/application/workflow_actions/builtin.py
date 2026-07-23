"""Built-in ``WorkflowAction`` implementations. See
``docs/architecture/workflow-engine.md`` for the full action catalog,
including deliberately-deferred ones (a generic outbound-HTTP action is
not built here — see that doc for why).

Every action that touches a conversation reuses ``ConversationService``
(status-transition validation, provider dispatch, event publishing)
rather than re-deriving that logic against the ORM directly.
"""

from typing import Any
from uuid import UUID

from blinkengage.application.workflow_actions.base import WorkflowAction, WorkflowExecutionContext
from blinkengage.domain.events import DomainEvent
from blinkengage.infrastructure.database.models.conversation import ConversationStatus
from blinkengage.infrastructure.database.models.customer import CustomerTag
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
from blinkengage.infrastructure.repositories.tag_repository import TagRepository
from blinkengage.infrastructure.workflow.action_registry import WorkflowActionRegistry


def _require_id(event: dict[str, Any], key: str) -> UUID:
    raw = event.get("payload", {}).get(key)
    if not raw:
        raise ValueError(
            f"This action requires a triggering event whose payload has {key!r} "
            "(e.g. conversation.created, message.persisted, conversation.assignment_changed)"
        )
    return UUID(raw)


@WorkflowActionRegistry.register("add_tag")
class AddTagAction(WorkflowAction):
    async def execute(
        self, *, params: dict[str, Any], context: WorkflowExecutionContext
    ) -> dict[str, Any]:
        tag_name = str(params.get("tag", "")).strip()
        if not tag_name:
            raise ValueError("add_tag requires params['tag']")
        customer_id = _require_id(context.event, "customer_id")

        customers = CustomerRepository(context.session)
        customer = await customers.get_by_id(company_id=context.company_id, customer_id=customer_id)
        if customer is None:
            raise ValueError(f"Customer {customer_id} not found")

        tags = TagRepository(context.session)
        tag = await tags.get_or_create(company_id=context.company_id, name=tag_name)
        if tag.name not in {ct.tag.name for ct in customer.customer_tags}:
            customer.customer_tags.append(CustomerTag(tag=tag))

        return {"tag": tag_name, "customer_id": str(customer_id)}


@WorkflowActionRegistry.register("assign_to_queue")
class AssignToQueueAction(WorkflowAction):
    async def execute(
        self, *, params: dict[str, Any], context: WorkflowExecutionContext
    ) -> dict[str, Any]:
        conversation_id = _require_id(context.event, "conversation_id")
        queue_id = UUID(str(params["queue_id"]))
        await context.conversation_service.update(
            company_id=context.company_id,
            conversation_id=conversation_id,
            status=None,
            assigned_agent_id=None,
            queue_id=queue_id,
        )
        return {"conversation_id": str(conversation_id), "queue_id": str(queue_id)}


@WorkflowActionRegistry.register("assign_to_agent")
class AssignToAgentAction(WorkflowAction):
    async def execute(
        self, *, params: dict[str, Any], context: WorkflowExecutionContext
    ) -> dict[str, Any]:
        conversation_id = _require_id(context.event, "conversation_id")
        agent_id = UUID(str(params["agent_id"]))
        await context.conversation_service.update(
            company_id=context.company_id,
            conversation_id=conversation_id,
            status=None,
            assigned_agent_id=agent_id,
        )
        return {"conversation_id": str(conversation_id), "agent_id": str(agent_id)}


@WorkflowActionRegistry.register("set_conversation_status")
class SetConversationStatusAction(WorkflowAction):
    async def execute(
        self, *, params: dict[str, Any], context: WorkflowExecutionContext
    ) -> dict[str, Any]:
        conversation_id = _require_id(context.event, "conversation_id")
        status = ConversationStatus(str(params["status"]))
        await context.conversation_service.update(
            company_id=context.company_id,
            conversation_id=conversation_id,
            status=status,
            assigned_agent_id=None,
        )
        return {"conversation_id": str(conversation_id), "status": status.value}


@WorkflowActionRegistry.register("send_reply")
class SendReplyAction(WorkflowAction):
    async def execute(
        self, *, params: dict[str, Any], context: WorkflowExecutionContext
    ) -> dict[str, Any]:
        conversation_id = _require_id(context.event, "conversation_id")
        body = str(params.get("body", "")).strip()
        if not body:
            raise ValueError("send_reply requires params['body']")
        message = await context.conversation_service.send_reply(
            company_id=context.company_id,
            conversation_id=conversation_id,
            body=body,
            attachment_ids=[],
        )
        return {"conversation_id": str(conversation_id), "message_id": str(message.id)}


@WorkflowActionRegistry.register("create_notification")
class CreateNotificationAction(WorkflowAction):
    """A company-configurable notification, layered on top of the
    built-in ones ``notification_consumer.py`` already sends for
    assignment/SLA events — this is how a workflow can notify any user
    about anything, without new backend code per notification type."""

    async def execute(
        self, *, params: dict[str, Any], context: WorkflowExecutionContext
    ) -> dict[str, Any]:
        user_id = UUID(str(params["user_id"]))
        title = str(params.get("title", "")).strip()
        body = str(params.get("body", "")).strip()
        if not title or not body:
            raise ValueError("create_notification requires params['title'] and params['body']")

        notification_payload: dict[str, Any] = dict(params.get("payload", {}))
        conversation_id = context.event.get("payload", {}).get("conversation_id")
        if conversation_id and "conversation_id" not in notification_payload:
            notification_payload["conversation_id"] = conversation_id

        notification = await context.notifications.create(
            company_id=context.company_id,
            user_id=user_id,
            notification_type="workflow.notification",
            title=title,
            body=body,
            payload=notification_payload,
        )
        return {"notification_id": str(notification.id), "user_id": str(user_id)}


@WorkflowActionRegistry.register("publish_event")
class PublishEventAction(WorkflowAction):
    """The extensibility escape hatch: lets a workflow emit a custom
    domain event onto the same bus, so future modules (Notifications, ERP
    sync) can integrate with workflows purely by subscribing to whatever
    event_type a company's workflows choose to publish, with zero changes
    here."""

    async def execute(
        self, *, params: dict[str, Any], context: WorkflowExecutionContext
    ) -> dict[str, Any]:
        event_type = str(params.get("event_type", "")).strip()
        if not event_type:
            raise ValueError("publish_event requires params['event_type']")
        payload = params.get("payload", {})
        if not isinstance(payload, dict):
            raise ValueError("publish_event's params['payload'] must be an object")

        await context.events.publish(
            DomainEvent(
                event_type=event_type,
                company_id=context.company_id,
                aggregate_type="workflow_action",
                aggregate_id=None,
                payload=payload,
            )
        )
        return {"event_type": event_type}
