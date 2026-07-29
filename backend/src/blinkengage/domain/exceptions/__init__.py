"""Domain-level exceptions.

These are raised by the domain/application layers and translated to HTTP
responses at the API boundary — the domain layer itself has no knowledge of
HTTP or FastAPI.
"""


class DomainError(Exception):
    """Base class for all domain-level errors."""


class EntityNotFoundError(DomainError):
    def __init__(self, entity_name: str, identifier: object) -> None:
        self.entity_name = entity_name
        self.identifier = identifier
        super().__init__(f"{entity_name} with id={identifier!r} was not found")


class EntityAlreadyExistsError(DomainError):
    def __init__(self, entity_name: str, field: str, value: object) -> None:
        self.entity_name = entity_name
        self.field = field
        self.value = value
        super().__init__(f"{entity_name} with {field}={value!r} already exists")


class AuthenticationError(DomainError):
    """Raised on invalid credentials or invalid/expired tokens."""


class CompanyNotActiveError(AuthenticationError):
    """Raised when sign-in is refused because the company itself is
    suspended or closed, rather than because the credentials are wrong.

    Subclasses ``AuthenticationError`` so it keeps the same 401 mapping
    and every existing handler keeps working, while carrying a distinct,
    actionable message — "your credentials are fine, your workspace is
    suspended" is a materially different thing to tell someone than
    "wrong password", and conflating them sends people to reset a
    password that was never the problem."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        message = (
            "This workspace has been suspended. Please contact your administrator."
            if reason == "suspended"
            else "This workspace is no longer active."
        )
        super().__init__(message)


class AuthorizationError(DomainError):
    """Raised when an authenticated principal lacks a required permission."""


class InvalidChannelTypeError(DomainError):
    """Raised when a ``channel_type`` isn't registered in
    ``infrastructure.channels.registry.ChannelRegistry`` — an invalid
    client-supplied value, not a missing resource, so it falls through to
    the generic 400 in ``core/exceptions.py`` rather than 404."""

    def __init__(self, channel_type: str) -> None:
        self.channel_type = channel_type
        super().__init__(f"Unknown channel type: {channel_type!r}")


class InvalidChannelCredentialsError(DomainError):
    """Raised when a channel type has a known required-fields schema
    (``infrastructure.channels.credential_schemas``) and the supplied
    ``credentials`` dict doesn't satisfy it — a client-input validation
    failure, not a missing resource, so it falls through to the generic
    400 like ``InvalidChannelTypeError``. Channel types with no schema
    registered (not yet covered by Phase 1: Channel Experience) are left
    unvalidated at this layer, same as before."""

    def __init__(self, channel_type: str, detail: str) -> None:
        self.channel_type = channel_type
        self.detail = detail
        super().__init__(f"Invalid credentials for channel type {channel_type!r}: {detail}")


class InvalidSmsGatewayError(DomainError):
    """Raised when ``ChannelConfig.credentials["gateway"]`` isn't
    registered in ``infrastructure.channels.sms_gateway_registry.
    SmsGatewayRegistry`` — the inner plugin registry behind ``SmsProvider``
    (see ``docs/architecture/sms.md``). Same 400-by-default reasoning as
    ``InvalidChannelTypeError``."""

    def __init__(self, gateway_name: str) -> None:
        self.gateway_name = gateway_name
        super().__init__(f"Unknown SMS gateway: {gateway_name!r}")


class InvalidConversationStatusTransitionError(DomainError):
    """Raised on an illegal conversation status transition (e.g.
    ``closed`` -> ``pending`` directly, skipping ``open``) — see
    ``docs/architecture/conversations.md``."""

    def __init__(self, current: str, requested: str) -> None:
        self.current = current
        self.requested = requested
        super().__init__(f"Cannot transition conversation from {current!r} to {requested!r}")


class AttachmentValidationError(DomainError):
    """Raised when an uploaded attachment fails type/size validation."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)


class AttachmentNotLinkableError(DomainError):
    """Raised when a referenced attachment doesn't exist, belongs to a
    different conversation, or is already linked to another message."""

    def __init__(self, attachment_id: object) -> None:
        self.attachment_id = attachment_id
        super().__init__(f"Attachment {attachment_id!r} cannot be attached to this message")


class AiNotConfiguredError(DomainError):
    """Raised when an AI Engine feature is called but
    ``settings.ai_provider`` is ``"disabled"`` (the default) — a
    deployment/configuration state, not a missing resource, so it maps to
    503 rather than 404/400 in ``core/exceptions.py``. See
    ``docs/architecture/ai-engine.md``."""

    def __init__(self) -> None:
        super().__init__("AI features are not configured on this platform")


class InvalidNotificationPreferenceError(DomainError):
    """Raised when a preference update names a ``notification_type`` not
    in ``domain.notification_types.NOTIFICATION_TYPES`` or a ``channel``
    not in ``NotificationChannel`` — a client-input validation failure,
    not a missing resource, so it falls through to the generic 400 like
    ``InvalidChannelTypeError``."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


class ErpNotConfiguredError(DomainError):
    """Raised when an ERPNext-dependent action is requested for a company
    with no active ``ErpConfig``, or whose ERP master switch
    (``Company.settings["erp"]["enabled"]`` — see
    ``domain.company_settings.is_erp_enabled``) is off — a deployment/
    configuration state, not a missing resource, so it maps to 503 like
    ``AiNotConfiguredError``. See ``docs/architecture/erp-integration.md``
    and ``docs/architecture/company-onboarding.md``."""

    def __init__(self) -> None:
        super().__init__("ERPNext is not configured for this company")


class PricingNotConfiguredError(DomainError):
    """No price is configured for a metric at the requested instant, at
    any level of the hierarchy.

    A deployment/configuration state rather than a missing resource, so
    it maps to 503 like ``AiNotConfiguredError`` — the caller asked a
    well-formed question the installation is not yet set up to answer.
    Deliberately an error rather than a zero: a silent zero is a revenue
    leak that looks exactly like a working system."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


class AmbiguousPricingConfigurationError(DomainError):
    """Two rates of equal precedence cover the same instant.

    An integrity violation, mapped to 409. There is deliberately no
    tiebreak — a billing engine that guesses which of two prices applies
    is worse than one that stops and says so."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


class MetricNotPriceableError(DomainError):
    """The metric exists but nothing measures it yet, so it cannot carry
    a price. 409, not 404: a typo and "we can't measure that yet" are
    different problems with different fixes."""

    def __init__(self, code: str) -> None:
        super().__init__(
            f"{code} has no measurement engine yet, so it cannot be priced. "
            "It becomes priceable in the release that ships its meter."
        )


class PricingRangeOverlapError(DomainError):
    """The requested effective range overlaps an existing rate for the
    same target. 409 — resolving it is the operator's decision, not
    something to guess at."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


class PricingConcurrentEditError(DomainError):
    """The price changed between the operator reading it and writing it.

    409, carrying what the value is now, so they can re-read and decide
    rather than silently overwriting somebody else's change."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


class PricingBackdatingRefusedError(DomainError):
    """An effective date in the past, without explicit opt-in.

    Backdating is not forbidden outright — an operator who genuinely
    needs it (a contract signed on the 10th, effective the 1st) would
    otherwise do it in psql, unaudited. It requires ``allow_backdating``
    plus a reason, and is recorded distinctly."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


class SystemProfileNotPriceableError(DomainError):
    """The seeded Default profile deliberately carries no prices of its
    own; it falls through to the global default. One editable place."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"{name} has no prices of its own — it falls through to the global "
            "default. Edit the global price instead."
        )


class RateAlreadyEffectiveError(DomainError):
    """Voiding is only for a rate that has not taken effect yet. A rate
    that has been live may already have priced usage, and unwinding that
    is not a schema operation."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


class InvoiceStateError(DomainError):
    """An operation the invoice's current state does not allow — issuing
    something already issued, crediting a draft, cancelling an invoice
    with money against it. Maps to 409: the request was well-formed and
    would have been valid in a different state."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


class InvoiceNotPayableError(DomainError):
    """A payment cannot be applied as asked — the invoice is settled or
    cancelled, the amounts do not fit, or the payment belongs to another
    company. 409, for the same reason as ``InvoiceStateError``."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


class ConversationNotInQueueError(DomainError):
    """Raised when ``ConversationService.pick()`` is called on a
    conversation with no ``queue_id`` — picking only makes sense for a
    conversation currently sitting in a queue's shared pool. A plain
    precondition failure, not a missing resource, so — like
    ``AttachmentValidationError`` — it falls through to the generic 400
    in ``core/exceptions.py`` rather than getting its own mapping."""

    def __init__(self) -> None:
        super().__init__("Conversation is not in a queue")


class AgentMissingRequiredSkillError(DomainError):
    """Raised when ``ConversationService.pick()`` finds that the calling
    agent doesn't satisfy the target queue's required skills (any-of
    match — see ``application.services.assignment_engine.
    filter_by_required_skills``). This is an authorization failure (this
    specific agent isn't allowed to take this specific conversation),
    not a missing resource, so it maps to 403 like ``AuthorizationError``
    rather than 404."""

    def __init__(self, agent_id: object, queue_id: object) -> None:
        self.agent_id = agent_id
        self.queue_id = queue_id
        super().__init__(f"Agent {agent_id!r} lacks a required skill for queue {queue_id!r}")


class ConversationNotAssignedError(DomainError):
    """Raised when ``ConversationService.release()`` is called on a
    conversation with no ``assigned_agent_id`` — there is nothing to
    release. A plain precondition failure, not a missing resource, so —
    like ``ConversationNotInQueueError`` — it falls through to the
    generic 400 in ``core/exceptions.py`` rather than getting its own
    mapping."""

    def __init__(self) -> None:
        super().__init__("Conversation is not currently assigned to anyone")


class ConversationNotPickableError(DomainError):
    """Raised when ``ConversationService.pick()`` is called on a
    conversation whose status is ``RESOLVED`` or ``CLOSED`` — picking
    only makes sense for a conversation still actively in progress
    (``OPEN``/``PENDING``). A plain precondition failure, not a missing
    resource, so it falls through to the generic 400 like
    ``ConversationNotInQueueError``."""

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"Cannot pick a conversation with status {status!r}")


class ConversationAlreadyClaimedError(DomainError):
    """Raised when ``ConversationRepository.claim()``'s atomic conditional
    UPDATE affects zero rows — the conversation was already claimed
    (by another agent, or by this same agent's own request racing
    itself) between the caller's initial load and the atomic claim
    attempt. A genuine conflict with concurrent state, not a missing
    resource, so it maps to 409 like ``EntityAlreadyExistsError``."""

    def __init__(self, conversation_id: object) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"Conversation with id={conversation_id!r} was already claimed")


class SystemRoleNotDeletableError(DomainError):
    """Raised when ``RoleService.delete()`` targets a role with
    ``is_system=True`` (Owner/Admin/Agent, seeded per company at creation
    — see ``infrastructure.database.models.rbac.Role``). Deleting one
    would strand every company using the default set with no equivalent
    of a role several hardcoded lookups depend on (``auth_service``'s
    Owner seeding, ``agent_service``'s Agent seeding). A plain
    precondition failure, not a missing resource, so it falls through to
    the generic 400 like ``ConversationNotInQueueError``."""

    def __init__(self, role_name: str) -> None:
        self.role_name = role_name
        super().__init__(f"System role {role_name!r} cannot be deleted")


class RoleHasMembersError(DomainError):
    """Raised when ``RoleService.delete()`` targets a role that still has
    one or more users assigned to it. ``UserRole.role_id`` cascade-deletes
    on ``Role`` deletion, so allowing this would silently strip those
    users of every permission with no warning. Falls through to the
    generic 400 like ``SystemRoleNotDeletableError``."""

    def __init__(self, role_name: str, member_count: int) -> None:
        self.role_name = role_name
        self.member_count = member_count
        super().__init__(
            f"Role {role_name!r} still has {member_count} member(s) and cannot be deleted"
        )


class SystemRoleNameImmutableError(DomainError):
    """Raised when ``RoleService.update()`` attempts to rename a system
    role. Unlike the rest of a system role's fields (description,
    and — for Admin/Agent — permissions), the *name* of ``Owner``/
    ``Agent`` is a hardcoded lookup key relied on elsewhere
    (``auth_service`` seeds a new company's owner by looking up
    ``name="Owner"``; ``agent_service`` seeds every new agent by looking
    up ``name="Agent"``). Renaming either out from under those lookups
    would silently break agent/owner creation for that company, so it's
    blocked outright rather than merely discouraged."""

    def __init__(self, role_name: str) -> None:
        self.role_name = role_name
        super().__init__(f"System role {role_name!r} cannot be renamed")


class OwnerPermissionsImmutableError(DomainError):
    """Raised when ``RoleService.update()`` attempts to change the
    ``Owner`` system role's permission set. Owner always holds the full
    permission catalog by design (see
    ``domain.rbac.DEFAULT_ROLE_PERMISSIONS`` and
    ``infrastructure.database.models.rbac.Role``'s docstring) — there
    must always be at least one role in a company that can never be
    locked out of its own RBAC configuration."""

    def __init__(self) -> None:
        super().__init__("The Owner role's permissions cannot be changed")


class CompanyOwnerRoleImmutableError(DomainError):
    """Raised when ``RoleService.assign_role_to_user()`` targets the
    user flagged ``User.is_company_owner`` (the one who originally
    registered the company — see ``AuthService.register_company``) with
    any role other than the ``Owner`` system role. Every other user's
    role is freely reassignable, but the founding owner staying Owner is
    the one invariant this app relies on to guarantee a company can
    never end up with nobody holding ``roles.manage`` (only Owner is
    granted it by default, and Admin/Agent's default grants are
    themselves edited through that same permission)."""

    def __init__(self) -> None:
        super().__init__("The company owner's role cannot be changed away from Owner")


class SlaPolicyHasAssignedQueuesError(DomainError):
    """Raised when ``SlaPolicyService.delete()`` targets a policy still
    assigned to one or more queues. ``Queue.sla_policy_id`` is
    ``ondelete="SET NULL"``, so deleting an assigned policy wouldn't
    break at the database level — but it would silently revert every one
    of its queues back to their own legacy flat SLA fields (usually no
    SLA at all) with no warning. Same reasoning as
    ``RoleHasMembersError``."""

    def __init__(self, policy_name: str, queue_count: int) -> None:
        self.policy_name = policy_name
        self.queue_count = queue_count
        super().__init__(
            f"SLA policy {policy_name!r} is still assigned to {queue_count} queue(s) "
            "and cannot be deleted"
        )


class WeakPasswordError(DomainError):
    """Raised when a password satisfies the platform-wide floor
    (``validate_password_strength`` — at least 10 characters with a
    letter and a digit) but not a company's own, higher configurable
    minimum (``Company.settings["security"]["min_password_length"]`` —
    see ``domain.company_settings.min_password_length``). Falls through
    to the generic 400 like ``InvalidChannelTypeError``, since this is a
    client-input validation failure, not a missing resource. Not applied
    at company-registration time — a company's policy doesn't exist
    until the company itself does."""

    def __init__(self, required_length: int) -> None:
        self.required_length = required_length
        super().__init__(f"Password must be at least {required_length} characters long")


class InvalidAgentTransferTargetError(DomainError):
    """Raised when removing an agent in "transfer" mode names the agent
    being removed as its own transfer target — every other target-not-
    found case already raises ``EntityNotFoundError`` naturally (the same
    lookup ``ConversationService.transfer`` performs for a manual
    transfer)."""

    def __init__(self, agent_id: object) -> None:
        self.agent_id = agent_id
        super().__init__(f"Agent {agent_id!r} cannot be its own conversation-transfer target")
