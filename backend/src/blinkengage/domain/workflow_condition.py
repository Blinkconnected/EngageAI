"""The Workflow Engine's condition DSL — pure Python, no framework/ORM
dependency, so it's unit-testable in isolation and reusable by a future
frontend condition-builder's "preview this condition" endpoint without
pulling in SQLAlchemy. See ``docs/architecture/workflow-engine.md``.

Shape (JSON, matching what ``WorkflowDefinition.conditions`` stores)::

    {"all": [
        {"field": "payload.channel_type", "operator": "equals", "value": "whatsapp"},
        {"any": [
            {"field": "payload.body", "operator": "contains", "value": "refund"},
            {"field": "payload.body", "operator": "contains", "value": "cancel"}
        ]}
    ]}

``all``/``any`` (AND/OR) nest arbitrarily via recursion — deliberately not
a full expression grammar (no arithmetic, no cross-field comparison):
"visual-friendly" per the roadmap means a drag-conditions-into-groups
builder, which this shape maps onto directly. An empty/missing condition
tree matches unconditionally (a workflow with no conditions always fires
on its trigger event).
"""

from typing import Any

_TRUTHY_EMPTY: tuple[Any, ...] = (None, "", [], {}, ())


def _resolve_field(event: dict[str, Any], field: str) -> Any:
    """Dot-path lookup into the event dict, e.g. ``"payload.channel_type"``.
    Missing intermediate keys resolve to ``None`` rather than raising —
    a condition referencing a field a given event doesn't have should
    fail to match, not crash the whole evaluation."""
    value: Any = event
    for part in field.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _apply_operator(operator: str, actual: Any, expected: Any) -> bool:
    if operator == "equals":
        return bool(actual == expected)
    if operator == "not_equals":
        return bool(actual != expected)
    if operator == "contains":
        return isinstance(actual, str) and isinstance(expected, str) and expected in actual
    if operator == "not_contains":
        return not (isinstance(actual, str) and isinstance(expected, str) and expected in actual)
    if operator == "starts_with":
        return isinstance(actual, str) and isinstance(expected, str) and actual.startswith(expected)
    if operator == "ends_with":
        return isinstance(actual, str) and isinstance(expected, str) and actual.endswith(expected)
    if operator == "in":
        return isinstance(expected, list) and actual in expected
    if operator == "not_in":
        return isinstance(expected, list) and actual not in expected
    if operator == "is_empty":
        return actual in _TRUTHY_EMPTY
    if operator == "is_not_empty":
        return actual not in _TRUTHY_EMPTY
    if operator == "greater_than":
        return (
            isinstance(actual, int | float)
            and isinstance(expected, int | float)
            and actual > expected
        )
    if operator == "less_than":
        return (
            isinstance(actual, int | float)
            and isinstance(expected, int | float)
            and actual < expected
        )
    raise ValueError(f"Unknown condition operator: {operator!r}")


def evaluate_condition(condition: dict[str, Any], event: dict[str, Any]) -> bool:
    if not condition:
        return True
    if "all" in condition:
        return all(evaluate_condition(clause, event) for clause in condition["all"])
    if "any" in condition:
        return any(evaluate_condition(clause, event) for clause in condition["any"])
    actual = _resolve_field(event, condition["field"])
    return _apply_operator(condition["operator"], actual, condition.get("value"))
