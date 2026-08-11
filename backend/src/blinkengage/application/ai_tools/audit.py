"""Turning a tool call into something safe to keep forever.

See ``docs/architecture/ai-tool-calling.md``.

**Allowlist, not denylist.** What gets recorded is the set of fields the
tool's argument schema *declares*, and that set is checked at
registration time to contain no secret-shaped name (see
``registry.SECRET_NAME_FRAGMENTS``). A field nobody declared is a field
that cannot be logged, so adding a credential to some model later cannot
leak it here by omission — the failure mode of a denylist, where the new
secret is the one nobody remembered to add.

The scrub below is the second layer, for values reached through a
``state_reader`` (which returns a hand-built dict and so is only as
careful as its author). Both layers exist because an audit record is the
one artefact in the platform that is deliberately never deleted.
"""

from typing import Any

from pydantic import BaseModel

from blinkengage.application.ai_tools.registry import SECRET_NAME_FRAGMENTS

REDACTED = "[redacted]"

#: How deep to walk a nested structure before giving up and redacting the
#: rest. A state_reader returning something unexpectedly deep is a bug,
#: and the safe reading of a bug is "do not record what you cannot see".
_MAX_DEPTH = 6


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in SECRET_NAME_FRAGMENTS)


def scrub(value: Any, *, depth: int = 0) -> Any:
    """Recursively redact secret-shaped keys and flatten to JSON types."""
    if depth >= _MAX_DEPTH:
        return REDACTED
    if isinstance(value, dict):
        return {
            str(key): (REDACTED if _is_secret_key(str(key)) else scrub(item, depth=depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [scrub(item, depth=depth + 1) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    # UUIDs, datetimes, enums and anything else become their string form
    # rather than being dropped: the audit trail is more useful with
    # "2026-08-11T09:00:00+00:00" in it than with a hole.
    return str(value)


def serialize_arguments(args: BaseModel) -> dict[str, Any]:
    """The validated input, as recorded.

    ``args`` is the *validated* model, never the model's raw argument
    blob — so what the audit says was requested is what the pipeline
    actually acted on, not what the LLM claimed. Those differ whenever
    validation coerces or defaults a value, and the useful one after an
    incident is the former.
    """
    scrubbed = scrub(args.model_dump(mode="json"))
    # ``scrub`` is deliberately typed loosely (it walks arbitrary nested
    # values); a model dump is always a mapping at the top level.
    return scrubbed if isinstance(scrubbed, dict) else {}


def serialize_state(state: dict[str, Any] | None) -> dict[str, Any] | None:
    return None if state is None else scrub(state)
