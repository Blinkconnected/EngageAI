"""The admin assistant runtime, and the things it structurally cannot do.

The runtime is orchestration. Its safety comes almost entirely from what it
delegates: the registry decides what exists, the executor decides whether a
call is allowed and whether it parks, the knowledge service performs changes,
the gate decides authority. These tests assert that it has not quietly grown
any of those capabilities of its own.

The one that matters most is ``confirm``. An assistant that could call it
would be approving its own proposals, and every confirmation in the system
would become a formality nobody noticed stopped happening.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from blinkengage.application.assistant.admin_assistant import (
    ADMIN_PERMISSION,
    SYSTEM_PROMPT,
    AdminAssistant,
)
from blinkengage.domain.rbac import is_known_permission

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "blinkengage"
RUNTIME = SRC / "application" / "assistant" / "admin_assistant.py"

#: Methods that change knowledge. The runtime must reach none of them: every
#: change goes through a registered tool and therefore through the executor.
WRITE_METHODS = frozenset({"create_draft", "publish", "supersede", "archive"})

#: The one executor method the runtime may never call.
FORBIDDEN_EXECUTOR_METHODS = frozenset({"confirm", "reject"})


def _tree() -> ast.Module:
    return ast.parse(RUNTIME.read_text(), filename=str(RUNTIME))


def _called_attributes() -> set[str]:
    return {
        node.func.attr
        for node in ast.walk(_tree())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def _imported_modules(path: pathlib.Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


# --- it cannot confirm, publish, or write -----------------------------


def test_the_runtime_never_confirms_an_action() -> None:
    """The single most important structural claim in this phase.

    Checked on call sites rather than source text: the module's own docstring
    explains that it does not confirm, and a substring guard would trip on
    the sentence describing the rule it enforces.
    """
    offenders = sorted(_called_attributes() & FORBIDDEN_EXECUTOR_METHODS)
    assert offenders == [], f"admin_assistant.py calls executor.{offenders}"


def test_the_runtime_never_calls_a_knowledge_write_method() -> None:
    offenders = sorted(_called_attributes() & WRITE_METHODS)
    assert offenders == [], f"admin_assistant.py calls {offenders}"


def test_the_runtime_never_calls_the_publication_gate_itself() -> None:
    """Authority is decided inside the tool, behind confirmation. A runtime
    that evaluated the gate could reach a publication decision without a
    parked action ever existing."""
    plain_calls = {
        node.func.id
        for node in ast.walk(_tree())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "publication_gate" not in plain_calls
    assert "publication_gate" not in _imported_modules(RUNTIME)


def test_the_runtime_holds_no_repository() -> None:
    """It has a session — it writes conversation turns — but no repository
    and no knowledge model. Turn persistence is the only thing it owns."""
    offenders = [
        module
        for module in sorted(_imported_modules(RUNTIME))
        if "repositories" in module or "models.knowledge" in module
    ]
    assert offenders == [], f"admin_assistant.py imports {offenders}"


def test_the_only_model_the_runtime_writes_is_the_turn() -> None:
    added = [
        node
        for node in ast.walk(_tree())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add"
        # ``self._session.add`` specifically — a bare ``.add`` also matches
        # set membership bookkeeping, which is not persistence.
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "_session"
    ]
    assert len(added) == 1, "the runtime adds more than one kind of row"

    # The row is built into a local first, so follow the type rather than the
    # argument: the only ORM class this module constructs must be the turn.
    constructed = {
        node.func.id
        for node in ast.walk(_tree())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    orm_classes = {name for name in constructed if name.endswith(("Turn", "Log", "Record"))}
    assert orm_classes == {"AiAssistantTurn"}, f"the runtime constructs {orm_classes}"

    # And the imported model surface is exactly that one class.
    imported_models = {
        alias.name
        for node in ast.walk(_tree())
        if isinstance(node, ast.ImportFrom) and "database.models" in (node.module or "")
        for alias in node.names
    }
    assert imported_models == {"AiAssistantTurn"}


# --- identity cannot be manufactured ----------------------------------


def test_identity_comes_from_the_auth_context_only() -> None:
    """Every ``company_id``/``user_id`` written or queried must be an
    attribute read off ``auth``, never a parameter or a literal."""
    source = RUNTIME.read_text()
    assert "company_id=auth.company_id" in source
    assert "user_id=auth.user_id" in source
    assert "AiAssistantTurn.company_id == auth.company_id" in source
    assert "AiAssistantTurn.user_id == auth.user_id" in source


def test_the_runtime_signature_accepts_no_identity_argument() -> None:
    """A caller passes a message and a session. It cannot pass a tenant."""
    respond = next(
        node
        for node in ast.walk(_tree())
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "respond"
    )
    parameters = {argument.arg for argument in [*respond.args.args, *respond.args.kwonlyargs]}
    for forbidden in (
        "company_id",
        "user_id",
        "actor_user_id",
        "permissions",
        "tenant_id",
        "is_platform_admin",
        "approved_by_user_id",
    ):
        assert forbidden not in parameters, f"respond() accepts {forbidden}"
    assert "auth" in parameters


def test_the_admin_permission_is_an_existing_rbac_code() -> None:
    """Not an AI-specific grant. An administrator who may use the assistant
    is exactly an actor who may administer the company."""
    assert ADMIN_PERMISSION == "company.manage"
    assert is_known_permission(ADMIN_PERMISSION)


def test_authorization_runs_before_the_provider_is_touched() -> None:
    """An unauthorised caller must cost nothing — no provider bill, and no
    company data placed in a prompt."""
    respond = next(
        node
        for node in ast.walk(_tree())
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "respond"
    )
    body = [ast.dump(statement) for statement in respond.body]
    authorize_at = next(i for i, dumped in enumerate(body) if "_authorize" in dumped)
    provider_at = next(i for i, dumped in enumerate(body) if "_converse" in dumped)
    assert authorize_at < provider_at


# --- no second anything -----------------------------------------------


def test_the_runtime_builds_no_registry_and_no_executor() -> None:
    """Both are injected. Constructing either here would be a second copy
    with its own, quietly different, rules."""
    constructed = {
        node.func.id
        for node in ast.walk(_tree())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    for forbidden in ("ToolRegistry", "ToolExecutor", "build_default_registry"):
        assert forbidden not in constructed, f"admin_assistant.py constructs {forbidden}"


def test_dispatch_goes_through_the_executor_and_nowhere_else() -> None:
    """One call site, and it is ``executor.execute``. Any other dispatch
    would be a tool name reaching a handler the registry never vetted."""
    receivers = [
        node.func.value.attr
        for node in ast.walk(_tree())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
        and isinstance(node.func.value, ast.Attribute)
    ]
    # ``_session.execute`` is the replay lookup, which is this module's own
    # persistence rather than tool dispatch. Every *tool* execution is the
    # executor's, and there is exactly one such call site.
    assert receivers.count("_executor") == 1
    assert set(receivers) <= {"_executor", "_session"}


def test_the_runtime_introduces_no_retrieval_of_its_own() -> None:
    forbidden = ("subject_matching", "vector", "embedding", "knowledge_retrieval", "lexical")
    offenders = [
        module
        for module in sorted(_imported_modules(RUNTIME))
        for needle in forbidden
        if needle in module
    ]
    assert offenders == [], f"admin_assistant.py imports {offenders}"


def test_no_shell_filesystem_or_network_capability_is_reachable() -> None:
    forbidden = ("subprocess", "os.system", "socket", "httpx", "requests", "pathlib", "shutil")
    offenders = [
        module
        for module in sorted(_imported_modules(RUNTIME))
        if any(module == needle or module.startswith(f"{needle}.") for needle in forbidden)
    ]
    assert offenders == [], f"admin_assistant.py imports {offenders}"


# --- the boundary with the customer-facing paths ----------------------


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(SRC / "application" / "services" / "autopilot_service.py", id="autopilot"),
        pytest.param(SRC / "application" / "brain" / "fact_extraction.py", id="4E-extraction"),
        pytest.param(SRC / "application" / "brain" / "extraction_bridge.py", id="4E-bridge"),
        pytest.param(SRC / "application" / "brain" / "service.py", id="company-brain"),
    ],
)
def test_customer_and_ingestion_paths_cannot_reach_the_admin_assistant(
    path: pathlib.Path,
) -> None:
    """Autopilot answers a customer and 4E reads a stranger's document.
    Neither has an authenticated administrator behind it, so neither may
    hold a runtime whose authority comes from one."""
    assert path.is_file()
    offenders = [
        module
        for module in _imported_modules(path)
        if "admin_assistant" in module or "ai_tools" in module
    ]
    assert offenders == [], f"{path.name} imports {offenders}"


# --- the prompt states the trust boundary -----------------------------


def test_the_system_prompt_marks_retrieved_knowledge_as_untrusted() -> None:
    """The weaker half of the injection defence, but it has to be present.

    The strong half is structural and tested elsewhere: a record asking to be
    published reaches a tool that parks for a human.
    """
    prompt = SYSTEM_PROMPT.lower()
    assert "data" in prompt and "not instruction" in prompt
    assert "cannot grant permission" in prompt
    assert "identity and permissions come from the authenticated request" in prompt
    assert "you cannot approve it yourself" in prompt


def test_the_assistant_reports_unavailable_without_a_provider() -> None:
    assistant = AdminAssistant(
        provider=None,
        executor=None,  # type: ignore[arg-type]
        registry=None,  # type: ignore[arg-type]
        session=None,  # type: ignore[arg-type]
    )
    assert assistant.available is False


def test_the_runtime_does_not_live_in_the_customer_facing_brain_package() -> None:
    """Where this module sits is itself a security boundary.

    ``application/brain`` is the path that answers a stranger — CompanyBrain
    grounding a customer reply, 4E reading a stranger's document — and a
    guard forbids that whole package from importing ``ai_tools``. The admin
    assistant must reach the tools, so putting it there would have forced the
    first exemption into a rule that is only useful while it is absolute.

    This test exists because that is exactly the mistake that was made and
    caught: the runtime was written into ``application/brain`` and the
    existing guard failed. It was moved rather than exempted.
    """
    assert RUNTIME.is_file()
    assert RUNTIME.parent.name == "assistant"
    assert not (SRC / "application" / "brain" / "admin_assistant.py").exists()

    for path in sorted((SRC / "application" / "brain").rglob("*.py")):
        assert "ai_tools" not in _imported_modules(
            path
        ), f"{path.name} reaches the tool registry from the customer-facing package"
