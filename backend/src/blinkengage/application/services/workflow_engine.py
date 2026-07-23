"""``WorkflowEngine`` — evaluates every active workflow bound to an
incoming domain event's type, executes the ones whose conditions match,
and records one ``WorkflowRun`` per (workflow, event) pair regardless of
outcome (matched-and-succeeded, matched-and-failed, or skipped for not
matching). See ``docs/architecture/workflow-engine.md``.
"""

from datetime import UTC, datetime
from typing import Any

from blinkengage.application.workflow_actions.base import WorkflowExecutionContext
from blinkengage.domain.events import DomainEvent
from blinkengage.domain.workflow_condition import evaluate_condition
from blinkengage.infrastructure.database.models.workflow import (
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunStatus,
)
from blinkengage.infrastructure.repositories.workflow_repository import (
    WorkflowDefinitionRepository,
)
from blinkengage.infrastructure.repositories.workflow_run_repository import (
    WorkflowRunRepository,
)
from blinkengage.infrastructure.workflow.action_registry import WorkflowActionRegistry


class WorkflowEngine:
    def __init__(
        self, *, workflows: WorkflowDefinitionRepository, runs: WorkflowRunRepository
    ) -> None:
        self._workflows = workflows
        self._runs = runs

    async def handle_event(self, *, context: WorkflowExecutionContext) -> None:
        event_type = context.event.get("event_type")
        if not event_type:
            return
        definitions = await self._workflows.list_active_for_trigger(
            company_id=context.company_id, trigger_event_type=event_type
        )
        for workflow in definitions:
            await self._run_one(workflow, context=context)

    async def _run_one(
        self, workflow: WorkflowDefinition, *, context: WorkflowExecutionContext
    ) -> None:
        started_at = datetime.now(UTC)

        if not evaluate_condition(workflow.conditions, context.event):
            await self._record_run(
                workflow,
                context=context,
                status=WorkflowRunStatus.SKIPPED,
                actions_executed=[],
                error_message=None,
                started_at=started_at,
            )
            return

        actions_executed: list[dict[str, Any]] = []
        error_message: str | None = None
        for step in workflow.actions:
            action_type = step.get("type", "")
            params = step.get("params", {})
            action = WorkflowActionRegistry.get(action_type)
            if action is None:
                error_message = f"Unknown workflow action type: {action_type!r}"
                actions_executed.append({"action_type": action_type, "error": error_message})
                break
            try:
                result = await action.execute(params=params, context=context)
            except Exception as exc:
                # One workflow's misconfiguration/failure must never break
                # evaluation of other workflows or the consumer loop
                # itself — recorded on the audit trail instead.
                error_message = str(exc)
                actions_executed.append({"action_type": action_type, "error": error_message})
                break
            actions_executed.append({"action_type": action_type, "result": result})

        status = WorkflowRunStatus.FAILED if error_message else WorkflowRunStatus.SUCCEEDED
        await self._record_run(
            workflow,
            context=context,
            status=status,
            actions_executed=actions_executed,
            error_message=error_message,
            started_at=started_at,
        )

    async def _record_run(
        self,
        workflow: WorkflowDefinition,
        *,
        context: WorkflowExecutionContext,
        status: WorkflowRunStatus,
        actions_executed: list[dict[str, Any]],
        error_message: str | None,
        started_at: datetime,
    ) -> None:
        run = await self._runs.add(
            WorkflowRun(
                company_id=context.company_id,
                workflow_id=workflow.id,
                triggering_event_type=context.event.get("event_type", ""),
                triggering_event_payload=context.event,
                status=status,
                actions_executed=actions_executed,
                error_message=error_message,
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
        )
        await context.events.publish(
            DomainEvent(
                event_type="workflow.executed",
                company_id=context.company_id,
                aggregate_type="workflow_run",
                aggregate_id=run.id,
                payload={
                    "workflow_id": str(workflow.id),
                    "status": status.value,
                    "actions_executed": actions_executed,
                },
            )
        )
