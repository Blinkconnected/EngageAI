"""Invariants on the real Grafana alert provisioning.

Alert expressions are the one piece of production logic with no type
checker, no linter and no runtime that would notice them being wrong: a
rule that matches nothing is provisioned successfully, renders in the UI,
and reports no data forever — which looks exactly like a healthy
platform. Two defects of that shape have now reached production here, and
both are cheap to detect from the provisioning file itself.

- **The empty-vector defect.** ``sum()`` over a selector matching no
  series returns an empty vector, not zero, and any arithmetic on an
  empty vector is empty. The 5xx rule was a bare ratio, so a backend with
  no errors produced no data and Grafana escalated that to
  DatasourceNoData critical — loudest precisely when nothing was wrong,
  and indistinguishable from a broken pipeline.

- **The ``or vector(0)`` label defect.** ``or`` yields right-hand samples
  for label sets *not present* on the left, and ``vector(0)`` carries no
  labels. Against a labelled selector it therefore adds a permanent extra
  ``{}`` series next to the real ones instead of substituting for them.
  ``nginx_up or vector(0)`` fired continuously for ten hours before this
  was understood; ``min(nginx_up) or vector(0)`` is correct because the
  aggregation leaves ``{}`` on both sides.

The path resolution mirrors tests/unit/test_version_consistency.py: on a
bare checkout ``docker/`` sits beside ``backend/``, while inside the
backend container only ``./backend`` is mounted and the file is genuinely
absent. CI runs on a checkout, which is the gate that matters.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

RULES_PATH = Path(__file__).resolve().parents[3] / (
    "docker/grafana/provisioning/alerting/rules.yml"
)

#: Aggregation operators that reduce to the empty label set when written
#: without `by`/`without`. Only these make `or vector(...)` a substitution
#: rather than an addition.
AGGREGATIONS = frozenset(
    {
        "sum",
        "min",
        "max",
        "avg",
        "count",
        "group",
        "stddev",
        "stdvar",
    }
)

pytestmark = pytest.mark.skipif(
    not RULES_PATH.exists(),
    reason="alert provisioning is outside the backend container's mount",
)


def _rules() -> dict[str, dict[str, Any]]:
    document = yaml.safe_load(RULES_PATH.read_text())
    return {rule["uid"]: rule for group in document["groups"] for rule in group.get("rules", [])}


def _query(rule: dict[str, Any], ref_id: str = "A") -> str:
    for datum in rule["data"]:
        if datum["refId"] == ref_id:
            return str(datum["model"]["expr"])
    raise AssertionError(f"{rule['uid']} has no refId {ref_id}")


def _threshold(rule: dict[str, Any]) -> tuple[str, list[float]]:
    for datum in rule["data"]:
        if datum["datasourceUid"] == "__expr__":
            evaluator = datum["model"]["conditions"][0]["evaluator"]
            return str(evaluator["type"]), list(evaluator["params"])
    raise AssertionError(f"{rule['uid']} has no threshold stage")


def _matching_open_paren(expr: str, close: int) -> int:
    depth = 0
    for index in range(close, -1, -1):
        if expr[index] == ")":
            depth += 1
        elif expr[index] == "(":
            depth -= 1
            if depth == 0:
                return index
    raise AssertionError(f"unbalanced parentheses in: {expr}")


def _identifier_before(expr: str, index: int) -> str:
    end = index
    start = end
    while start > 0 and (expr[start - 1].isalnum() or expr[start - 1] == "_"):
        start -= 1
    return expr[start:end]


# --- the label defect --------------------------------------------------


def test_every_or_vector_substitutes_rather_than_adds_a_series() -> None:
    """The left of `or vector(...)` must already be the empty label set.

    Enforced by shape: it has to end in a closed parenthesis whose opening
    is either an aggregation call or a plain group. A bare selector —
    `nginx_up or vector(0)`, the original defect — fails on the first
    condition.
    """
    offenders: list[str] = []
    for uid, rule in _rules().items():
        for datum in rule["data"]:
            expr = " ".join(str(datum["model"].get("expr", "")).split())
            search_from = 0
            while (found := expr.find("or vector(", search_from)) != -1:
                search_from = found + 1
                left = expr[:found].rstrip()
                if not left.endswith(")"):
                    offenders.append(f"{uid}: bare operand before `or vector(` -> {left[-60:]!r}")
                    continue
                opening = _matching_open_paren(left, len(left) - 1)
                head = _identifier_before(left, opening)
                if head and head not in AGGREGATIONS:
                    offenders.append(f"{uid}: `or vector(` applied to {head}(...)")

    assert offenders == [], "\n".join(offenders)


def test_no_aggregation_feeding_or_vector_keeps_labels_with_by_or_without() -> None:
    """`sum by (job) (...) or vector(0)` would reintroduce the same bug."""
    for uid, rule in _rules().items():
        for datum in rule["data"]:
            expr = " ".join(str(datum["model"].get("expr", "")).split())
            if "or vector(" not in expr:
                continue
            assert " by (" not in expr, f"{uid} keeps labels via `by` alongside `or vector(`"
            assert " without (" not in expr, f"{uid} keeps labels via `without`"


# --- the empty-vector defect ------------------------------------------


def test_the_5xx_rule_reports_zero_rather_than_no_data() -> None:
    """A healthy backend must produce a number, not an empty vector.

    Without the fallback the rule cannot express "no errors": the
    numerator matches nothing, `sum()` is empty, the division is empty and
    Grafana raises DatasourceNoData critical on a backend that is fine.
    """
    expr = " ".join(_query(_rules()["blinkengage-high-5xx-rate"]).split())

    assert expr.endswith("or vector(0)"), (
        "the whole expression must fall back to 0, otherwise an empty "
        "numerator or a closed traffic gate still yields no data"
    )
    assert expr.count("or vector(0)") >= 2, (
        "the 5xx numerator needs its own fallback: with traffic present "
        "and zero errors the ratio is still empty without it"
    )


def test_the_5xx_rule_gates_on_a_minimum_request_rate() -> None:
    """A ratio over a handful of requests is noise, not a signal."""
    expr = " ".join(_query(_rules()["blinkengage-high-5xx-rate"]).split())

    assert " and " in expr, "no traffic gate"
    assert ">= 0.2" in expr


def test_the_5xx_threshold_and_duration_are_unchanged() -> None:
    """The fix must not have quietly bought quiet with sensitivity."""
    rule = _rules()["blinkengage-high-5xx-rate"]

    assert _threshold(rule) == ("gt", [0.05])
    assert rule["for"] == "5m"
    assert rule["labels"]["severity"] == "critical"


# --- separation of concerns -------------------------------------------


def test_the_5xx_rule_does_not_also_police_absence() -> None:
    """Six states, not one.

    Healthy-and-idle, healthy-with-errors, broken-metrics, failed-scrape
    and backend-down were all the same DatasourceNoData critical. The
    ratio rule now answers only "what share of traffic is failing".
    """
    expr = _query(_rules()["blinkengage-high-5xx-rate"])

    assert "absent(" not in expr
    assert "up{" not in expr


def test_scrape_failure_has_its_own_alert() -> None:
    rule = _rules()["blinkengage-backend-down"]

    assert 'up{job="blinkengage-backend"}' in _query(rule)
    assert _threshold(rule) == ("lt", [1])
    assert rule["labels"]["severity"] == "critical"


def test_missing_series_has_its_own_alert() -> None:
    """The failure `up` cannot see: scrape fine, counters absent."""
    rule = _rules()["blinkengage-backend-metrics-missing"]
    expr = " ".join(_query(rule).split())

    assert expr.startswith('max(absent(http_requests_total{job="blinkengage-backend"}))')
    assert _threshold(rule) == ("gt", [0])


# --- provisioning hygiene ---------------------------------------------


def test_no_rule_treats_missing_data_as_healthy() -> None:
    """`noDataState: OK` is how a blind alert is made to look green.

    Grafana's default for a provisioned rule is NoData, which is correct:
    once the expressions above cannot go empty on their own, no data
    genuinely means the datasource or Grafana is broken.
    """
    for uid, rule in _rules().items():
        assert rule.get("noDataState", "NoData") == "NoData", f"{uid} ignores missing data"


def test_rule_uids_are_unique() -> None:
    document = yaml.safe_load(RULES_PATH.read_text())
    uids = [rule["uid"] for group in document["groups"] for rule in group.get("rules", [])]

    assert len(uids) == len(set(uids))
