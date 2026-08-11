"""The allowlist. A tool that is not in here cannot be called.

See ``docs/architecture/ai-tool-calling.md``.

Dispatch is a dictionary lookup on a name the registry put there. A model
that emits ``delete_company`` does not reach a handler that refuses — it
reaches nothing, and gets a structured "unknown tool" back. The absence
of destructive tools is therefore a property of *what was registered*,
not of what a system prompt asked the model to avoid.

Everything below is checked when a tool is registered, which is at import
time, which means a violation is a failure to start rather than a
surprise in production. ``tests/unit/test_ai_tool_registry_invariants.py``
asserts the same properties over the real catalog so they are also a CI
gate rather than only a runtime one.
"""

import re
from collections.abc import Iterable

from blinkengage.application.ai_tools.spec import ToolSpec
from blinkengage.domain.ai_tools import ToolDefinition
from blinkengage.domain.rbac import is_known_permission

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

#: Verbs a tool name may never contain. Not a list of forbidden *tools* —
#: a list of forbidden *intents*, so the guarantee covers the delete tool
#: nobody has thought of yet. Deliberately broad: `reset` and `truncate`
#: are here because "reset the workspace" destroys a customer's history
#: just as thoroughly as `delete_company` would.
FORBIDDEN_NAME_FRAGMENTS: frozenset[str] = frozenset(
    {"delete", "remove", "purge", "drop", "reset", "truncate", "wipe", "erase", "destroy"}
)

#: Argument names a tool may never declare. Identity and authorization
#: come from the authenticated request; a schema that accepts them is a
#: schema a model can lie to. ``target_user_id`` is the idiom for naming
#: somebody else, which keeps ``user_id`` unambiguous everywhere.
RESERVED_ARGUMENT_NAMES: frozenset[str] = frozenset(
    {
        "company_id",
        "user_id",
        "actor",
        "actor_user_id",
        "auth",
        "auth_context",
        "authorization",
        "permission",
        "permissions",
        "principal",
        "tenant",
        "tenant_id",
        "session_id",
        "is_company_owner",
        "is_platform_admin",
    }
)

#: Argument names that would put a secret into model context and into the
#: audit record. Refused at registration, which is why the audit
#: serialiser can treat the declared schema as an allowlist.
SECRET_NAME_FRAGMENTS: frozenset[str] = frozenset(
    {"password", "secret", "token", "api_key", "apikey", "credential", "private_key", "hashed"}
)


class ToolRegistrationError(ValueError):
    """A tool violates a registry invariant. Raised at import time."""


class ToolRegistry:
    """A closed set of tools. Construct, register, freeze, use."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        self._validate(spec)
        if spec.name in self._tools:
            raise ToolRegistrationError(f"Tool {spec.name!r} is already registered")
        self._tools[spec.name] = spec
        return spec

    @staticmethod
    def _validate(spec: ToolSpec) -> None:
        if not _NAME_PATTERN.match(spec.name):
            raise ToolRegistrationError(
                f"Tool name {spec.name!r} must be lower_snake_case starting with a letter"
            )

        lowered = spec.name.lower()
        for fragment in FORBIDDEN_NAME_FRAGMENTS:
            if fragment in lowered:
                raise ToolRegistrationError(
                    f"Tool {spec.name!r} contains the forbidden fragment {fragment!r}. "
                    "Destructive tools are not registrable; deletion goes through the "
                    "platform's own request/approve path, performed by a human."
                )

        if spec.permission is not None and not is_known_permission(spec.permission):
            raise ToolRegistrationError(
                f"Tool {spec.name!r} declares unknown permission {spec.permission!r}"
            )

        if spec.mutating and spec.permission is None:
            raise ToolRegistrationError(
                f"Mutating tool {spec.name!r} must declare a permission — a change nobody "
                "needs authority to make is a change nobody is accountable for"
            )

        config = getattr(spec.args_model, "model_config", {})
        if config.get("extra") != "forbid":
            raise ToolRegistrationError(
                f"Tool {spec.name!r} argument model must set extra='forbid', so a model "
                "cannot smuggle a field the schema never declared"
            )

        for field_name in spec.args_model.model_fields:
            if field_name in RESERVED_ARGUMENT_NAMES:
                raise ToolRegistrationError(
                    f"Tool {spec.name!r} declares reserved argument {field_name!r}. "
                    "Identity and tenant scope come from the authenticated request; "
                    "use 'target_...' to name another entity."
                )
            lowered_field = field_name.lower()
            for fragment in SECRET_NAME_FRAGMENTS:
                if fragment in lowered_field:
                    raise ToolRegistrationError(
                        f"Tool {spec.name!r} declares argument {field_name!r}, which would "
                        "place a secret in model context and in the audit record"
                    )

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def all(self) -> tuple[ToolSpec, ...]:
        return tuple(self._tools.values())

    def visible_to(self, permissions: Iterable[str]) -> tuple[ToolSpec, ...]:
        """The tools a caller may actually use.

        Filtering the *offered* set to what the caller can do is a
        courtesy to the model, not a security control — the executor
        re-checks every permission regardless. Its real value is that the
        model stops proposing actions the user will only be refused.
        """
        held = frozenset(permissions)
        return tuple(
            spec
            for spec in self._tools.values()
            if spec.permission is None or spec.permission in held
        )

    def definitions_for(self, permissions: Iterable[str]) -> list[ToolDefinition]:
        """The provider-facing projection: name, prose, JSON Schema.

        Note what is *not* here — handler, permission, confirmation
        policy. The model is told what it may ask for, never how the
        request will be judged.
        """
        return [
            ToolDefinition(
                name=spec.name,
                description=spec.description,
                parameters=spec.args_model.model_json_schema(),
            )
            for spec in self.visible_to(permissions)
        ]
