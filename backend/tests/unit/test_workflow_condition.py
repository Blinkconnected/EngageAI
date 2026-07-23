"""Unit tests for the Workflow Engine's condition DSL. See
``docs/architecture/workflow-engine.md``.
"""

import pytest

from blinkengage.domain.workflow_condition import evaluate_condition

_EVENT = {
    "event_type": "message.received",
    "company_id": "c1",
    "payload": {"channel_type": "whatsapp", "body": "I want a refund please", "amount": 42},
}


def test_empty_condition_matches_unconditionally() -> None:
    assert evaluate_condition({}, _EVENT) is True


class TestLeafOperators:
    def test_equals(self) -> None:
        condition = {"field": "payload.channel_type", "operator": "equals", "value": "whatsapp"}
        assert evaluate_condition(condition, _EVENT) is True
        assert evaluate_condition({**condition, "value": "sms"}, _EVENT) is False

    def test_not_equals(self) -> None:
        condition = {"field": "payload.channel_type", "operator": "not_equals", "value": "sms"}
        assert evaluate_condition(condition, _EVENT) is True

    def test_contains(self) -> None:
        condition = {"field": "payload.body", "operator": "contains", "value": "refund"}
        assert evaluate_condition(condition, _EVENT) is True
        assert evaluate_condition({**condition, "value": "cancel"}, _EVENT) is False

    def test_not_contains(self) -> None:
        condition = {"field": "payload.body", "operator": "not_contains", "value": "cancel"}
        assert evaluate_condition(condition, _EVENT) is True

    def test_starts_with(self) -> None:
        condition = {"field": "payload.body", "operator": "starts_with", "value": "I want"}
        assert evaluate_condition(condition, _EVENT) is True

    def test_ends_with(self) -> None:
        condition = {"field": "payload.body", "operator": "ends_with", "value": "please"}
        assert evaluate_condition(condition, _EVENT) is True

    def test_in(self) -> None:
        condition = {
            "field": "payload.channel_type",
            "operator": "in",
            "value": ["whatsapp", "sms"],
        }
        assert evaluate_condition(condition, _EVENT) is True

    def test_not_in(self) -> None:
        condition = {"field": "payload.channel_type", "operator": "not_in", "value": ["sms"]}
        assert evaluate_condition(condition, _EVENT) is True

    def test_is_empty_and_is_not_empty(self) -> None:
        assert (
            evaluate_condition(
                {"field": "payload.missing", "operator": "is_empty", "value": None}, _EVENT
            )
            is True
        )
        assert (
            evaluate_condition(
                {"field": "payload.body", "operator": "is_not_empty", "value": None}, _EVENT
            )
            is True
        )

    def test_greater_than_and_less_than(self) -> None:
        assert (
            evaluate_condition(
                {"field": "payload.amount", "operator": "greater_than", "value": 10}, _EVENT
            )
            is True
        )
        assert (
            evaluate_condition(
                {"field": "payload.amount", "operator": "less_than", "value": 10}, _EVENT
            )
            is False
        )

    def test_unknown_operator_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown condition operator"):
            evaluate_condition(
                {"field": "payload.amount", "operator": "frobnicate", "value": 1}, _EVENT
            )

    def test_missing_field_resolves_to_none_and_fails_equality(self) -> None:
        condition = {"field": "payload.nonexistent.deep", "operator": "equals", "value": "x"}
        assert evaluate_condition(condition, _EVENT) is False


class TestCombinators:
    def test_all_requires_every_clause(self) -> None:
        condition = {
            "all": [
                {"field": "payload.channel_type", "operator": "equals", "value": "whatsapp"},
                {"field": "payload.body", "operator": "contains", "value": "refund"},
            ]
        }
        assert evaluate_condition(condition, _EVENT) is True

        condition["all"][1]["value"] = "cancel"
        assert evaluate_condition(condition, _EVENT) is False

    def test_any_requires_one_clause(self) -> None:
        condition = {
            "any": [
                {"field": "payload.body", "operator": "contains", "value": "cancel"},
                {"field": "payload.body", "operator": "contains", "value": "refund"},
            ]
        }
        assert evaluate_condition(condition, _EVENT) is True

    def test_nested_all_within_any(self) -> None:
        condition = {
            "any": [
                {
                    "all": [
                        {
                            "field": "payload.channel_type",
                            "operator": "equals",
                            "value": "whatsapp",
                        },
                        {"field": "payload.body", "operator": "contains", "value": "refund"},
                    ]
                },
                {"field": "payload.channel_type", "operator": "equals", "value": "sms"},
            ]
        }
        assert evaluate_condition(condition, _EVENT) is True
