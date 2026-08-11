"""The structural guarantees, asserted over the real registry.

See ``docs/architecture/ai-tool-calling.md``.

``ToolRegistry`` enforces these at import time, so a violation already
fails to start. These tests exist anyway, and for a reason worth stating:
they are what makes the guarantee survive somebody *changing the
registry's own rules*. A future edit that loosened
``FORBIDDEN_NAME_FRAGMENTS`` would keep every runtime check passing and
break the promise; this file fails.
"""

import inspect

import pytest
from pydantic import BaseModel, ConfigDict

from blinkengage.application.ai_tools.catalog import DEFAULT_REGISTRY
from blinkengage.application.ai_tools.registry import (
    RESERVED_ARGUMENT_NAMES,
    SECRET_NAME_FRAGMENTS,
    ToolRegistrationError,
    ToolRegistry,
)
from blinkengage.application.ai_tools.spec import ToolSpec
from blinkengage.domain.rbac import is_known_permission

#: Names from the approved M2 brief that must never become callable.
FORBIDDEN_TOOL_NAMES = (
    "delete_company",
    "delete_user",
    "delete_agent",
    "delete_conversation",
    "delete_message",
    "delete_audit_log",
    "delete_billing_record",
)

#: An escape hatch is a tool that lets the model choose *what code runs*
#: rather than choosing among reviewed operations. None may exist.
ESCAPE_HATCH_FRAGMENTS = (
    "execute_sql",
    "run_sql",
    "query",
    "raw",
    "eval",
    "exec",
    "call_service",
    "invoke",
    "dispatch",
    "getattr",
    "shell",
    "command",
)


def test_no_forbidden_tool_is_registered() -> None:
    for name in FORBIDDEN_TOOL_NAMES:
        assert DEFAULT_REGISTRY.get(name) is None, f"{name} must never be callable by a model"


def test_no_tool_name_contains_a_destructive_verb() -> None:
    for spec in DEFAULT_REGISTRY.all():
        lowered = spec.name.lower()
        for fragment in ("delete", "remove", "purge", "drop", "reset", "truncate"):
            assert fragment not in lowered, f"{spec.name} implies destruction"


def test_no_tool_is_a_generic_escape_hatch() -> None:
    """No tool may take "what to run" as an argument.

    Checked on names *and* argument fields: a tool called
    ``list_departments`` that accepted a ``query`` string would be an
    escape hatch wearing an innocuous name.
    """
    for spec in DEFAULT_REGISTRY.all():
        for fragment in ESCAPE_HATCH_FRAGMENTS:
            assert fragment not in spec.name.lower(), f"{spec.name} looks like an escape hatch"
        for field_name in spec.args_model.model_fields:
            assert field_name.lower() not in {
                "sql",
                "query",
                "expression",
                "code",
                "script",
            }, f"{spec.name}.{field_name} would let a model choose what runs"


def test_no_handler_reaches_a_deleting_repository_method() -> None:
    """Read every handler's source and refuse deletion verbs.

    Crude by design. A handler cannot reach a repository at all — it is
    handed a fixed ``ToolServices`` and nothing else — so this is the
    second line, catching the case where somebody adds a deleting method
    to one of those services and a tool starts calling it.
    """
    banned = ("delete", "hard_delete", "purge", "soft_delete", "truncate", "drop")
    for spec in DEFAULT_REGISTRY.all():
        source = inspect.getsource(spec.handler)  # type: ignore[arg-type]
        for verb in banned:
            assert verb not in source, f"{spec.name}'s handler mentions {verb!r}"


def test_handlers_receive_no_session_or_repository() -> None:
    """``ToolServices`` is the whole surface, and it is all services."""
    from blinkengage.application.ai_tools.spec import ToolServices

    for field_name, field in ToolServices.__dataclass_fields__.items():
        type_name = str(field.type)
        assert "Repository" not in type_name, f"ToolServices.{field_name} exposes a repository"
        assert "Session" not in type_name, f"ToolServices.{field_name} exposes a session"
        assert "Service" in type_name, f"ToolServices.{field_name} is not an application service"


def test_every_tool_permission_exists_in_the_rbac_catalog() -> None:
    for spec in DEFAULT_REGISTRY.all():
        if spec.permission is not None:
            assert is_known_permission(
                spec.permission
            ), f"{spec.name} declares unknown permission {spec.permission}"


def test_every_mutating_tool_declares_a_permission() -> None:
    for spec in DEFAULT_REGISTRY.all():
        if spec.mutating:
            assert spec.permission is not None, f"{spec.name} mutates with no permission"


def test_every_argument_model_forbids_extra_fields() -> None:
    for spec in DEFAULT_REGISTRY.all():
        assert spec.args_model.model_config.get("extra") == "forbid", spec.name


def test_no_tool_declares_identity_or_secret_arguments() -> None:
    for spec in DEFAULT_REGISTRY.all():
        for field_name in spec.args_model.model_fields:
            assert field_name not in RESERVED_ARGUMENT_NAMES, f"{spec.name}.{field_name}"
            for fragment in SECRET_NAME_FRAGMENTS:
                assert fragment not in field_name.lower(), f"{spec.name}.{field_name}"


# --- the registry refuses bad registrations -------------------------------


def _spec(name: str, args_model: type[BaseModel], **kwargs: object) -> ToolSpec:
    async def _handler(ctx: object, args: object) -> dict[str, object]:
        return {}

    return ToolSpec(
        name=name,
        description="test",
        args_model=args_model,
        handler=_handler,  # type: ignore[arg-type]
        permission=kwargs.pop("permission", None),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "x"


def test_registering_a_delete_tool_raises() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolRegistrationError, match="forbidden fragment"):
        registry.register(_spec("delete_company", _Strict))


def test_registering_a_tool_that_accepts_company_id_raises() -> None:
    class WithCompanyId(BaseModel):
        model_config = ConfigDict(extra="forbid")

        company_id: str

    registry = ToolRegistry()
    with pytest.raises(ToolRegistrationError, match="reserved argument"):
        registry.register(_spec("do_thing", WithCompanyId))


def test_registering_a_tool_that_accepts_user_id_raises() -> None:
    class WithUserId(BaseModel):
        model_config = ConfigDict(extra="forbid")

        user_id: str

    registry = ToolRegistry()
    with pytest.raises(ToolRegistrationError, match="reserved argument"):
        registry.register(_spec("do_thing", WithUserId))


def test_registering_a_tool_that_accepts_permission_raises() -> None:
    class WithPermission(BaseModel):
        model_config = ConfigDict(extra="forbid")

        permission: str

    registry = ToolRegistry()
    with pytest.raises(ToolRegistrationError, match="reserved argument"):
        registry.register(_spec("do_thing", WithPermission))


def test_registering_a_tool_that_accepts_a_secret_raises() -> None:
    class WithSecret(BaseModel):
        model_config = ConfigDict(extra="forbid")

        api_key: str

    registry = ToolRegistry()
    with pytest.raises(ToolRegistrationError, match="secret"):
        registry.register(_spec("do_thing", WithSecret))


def test_registering_a_permissive_argument_model_raises() -> None:
    class Loose(BaseModel):
        name: str = "x"

    registry = ToolRegistry()
    with pytest.raises(ToolRegistrationError, match="extra='forbid'"):
        registry.register(_spec("do_thing", Loose))


def test_registering_an_unknown_permission_raises() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolRegistrationError, match="unknown permission"):
        registry.register(_spec("do_thing", _Strict, permission="not.a.real.permission"))


def test_registering_a_mutating_tool_without_permission_raises() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolRegistrationError, match="must declare a permission"):
        registry.register(_spec("do_thing", _Strict, mutating=True))
