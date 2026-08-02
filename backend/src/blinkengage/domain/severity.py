"""How serious an event is, decided once, for every client.

Severity belongs to the *event contract*, not to a console. The web app, a
mobile app, an API consumer and whatever integrates next must all colour the
same event the same way — and the only place that can be true is here, where
the platform knows what actually happened. A frontend that inferred it from
the word "breach" would be forming a judgement the platform never recorded,
and an invented flag is indistinguishable from one the platform raised.

Five levels, and the distinction that matters most is between the last three:

- ``INFO`` — it happened. Most of a healthy conversation is this.
- ``SUCCESS`` — a promise to the customer was kept.
- ``WARNING`` — somebody should look, and there is still time to act.
- ``ERROR`` — a promise was broken. Acting now cannot un-break it.
- ``CRITICAL`` — the platform could not do its job. Nothing will pick this up
  without intervention.

**Deliberate configuration is not an error.** A policy that denies AI because
a company switched AI off is the platform doing exactly what it was told, and
marking it ``ERROR`` would paint red across every conversation at every
company that made that choice — which teaches people to ignore red. A denial
is only ``CRITICAL`` when the reason is something *missing* rather than
something chosen.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class Severity(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


#: Worst first, so a caller summarising a set takes the first it finds. A
#: tuple rather than the enum's declaration order, for the same reason
#: ``HEALTH_ORDER`` is: reordering an enum for tidiness must not silently
#: reorder what a person is shown.
SEVERITY_ORDER: Final[tuple[Severity, ...]] = (
    Severity.CRITICAL,
    Severity.ERROR,
    Severity.WARNING,
    Severity.SUCCESS,
    Severity.INFO,
)


def worst(severities: list[Severity]) -> Severity:
    """The most serious of them. Never an average."""
    found = set(severities)
    for level in SEVERITY_ORDER:
        if level in found:
            return level
    return Severity.INFO


__all__ = ["SEVERITY_ORDER", "Severity", "worst"]
