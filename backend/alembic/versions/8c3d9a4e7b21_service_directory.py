"""service directory: services, frozen versions, runtime lanes

See ``docs/architecture/execution-context.md``.

Five tables behind one idea: a conversation must be able to say what rules
it ran under, months later, after everything has been edited.

``services`` is the identity — renamed, archived, switched off.
``service_versions`` is the configuration, **append-only**, with a trigger
that refuses UPDATE and DELETE so the guarantee survives a ``psql`` session
and not merely repository discipline. Editing a service mints a version;
conversations already running keep the one they started with.

``customer_context_versions`` versions the customer the same way, but minted
from a **fingerprint** of the routing-relevant attributes rather than on
every edit — a customer record changes constantly (a CRM sync writing a field
back, an agent correcting a phone number), and a version per change would be
a version per conversation, which is the same as no versioning at all.

``runtime_queues`` splits the lanes out of the logical queue. ``queues`` is
what an administrator names and assigns agents to; a runtime queue is a lane
inside it with its own capacity. Without the split, "the support queue is
full" cannot be answered.

``conversation_context_bindings`` records which versions a conversation is
running inside and why — also append-only, because a rebinding is a new fact
("moved to another service on the 3rd, by Sara") and an UPDATE would erase
the very question the table exists to answer.

**No backfill.** Existing conversations have no service and no binding, and
inventing one would be a guess presented as a record — the same reasoning as
``routing_decisions``. Nothing reads these tables yet; the resolution
pipeline is wired in a following change, and until then a conversation
without a binding behaves exactly as it does today.

Revision ID: 8c3d9a4e7b21
Revises: 77fb520751b8
Create Date: 2026-08-01 09:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "8c3d9a4e7b21"
down_revision: str | None = "77fb520751b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "services",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        # Added after service_versions exists — see below. A service and its
        # versions point at each other, so one direction has to be added
        # second or the tables cannot be created in any order.
        sa.Column("current_version_id", GUID(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_services_company_id", "services", ["company_id"])
    op.create_index("ix_services_company_active", "services", ["company_id", "is_active"])
    op.create_index(
        "uq_services_company_code",
        "services",
        ["company_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "service_versions",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "service_id",
            GUID(),
            sa.ForeignKey("services.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        # SET NULL: deleting a queue must not delete the history of every
        # service that once fed it.
        sa.Column(
            "logical_queue_id",
            GUID(),
            sa.ForeignKey("queues.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("logical_queue_name", sa.String(255), nullable=True),
        sa.Column(
            "overflow_strategy", sa.String(30), nullable=False, server_default="WAIT"
        ),
        sa.Column(
            "ai_overflow_policy", sa.String(30), nullable=False, server_default="NEVER"
        ),
        # Four independent clocks. NULL means "not measured" and is different
        # from 0, which means "breached the moment it starts".
        sa.Column("sla_queue_minutes", sa.Integer(), nullable=True),
        sa.Column("sla_first_response_minutes", sa.Integer(), nullable=True),
        sa.Column("sla_next_response_minutes", sa.Integer(), nullable=True),
        sa.Column("sla_resolution_minutes", sa.Integer(), nullable=True),
        sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "ai_pickup_delay_seconds", sa.Integer(), nullable=False, server_default="30"
        ),
        sa.Column(
            "ai_resume_delay_seconds", sa.Integer(), nullable=False, server_default="900"
        ),
        # Text, not float: a threshold compared against a model's confidence
        # must not have two numbers differing in the last binary place
        # straddle it.
        sa.Column(
            "ai_confidence_threshold", sa.String(16), nullable=False, server_default="0.75"
        ),
        sa.Column("extras", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "created_by_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("change_note", sa.String(500), nullable=True),
        sa.UniqueConstraint("service_id", "version", name="uq_service_versions_service_version"),
    )
    op.create_index("ix_service_versions_service", "service_versions", ["service_id", "version"])

    op.create_foreign_key(
        "fk_services_current_version",
        "services",
        "service_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "customer_context_versions",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "customer_id",
            GUID(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        # SHA-256 hex, not Python's hash(), which is salted per process and
        # would fork every customer's history on restart.
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False, server_default="STANDARD"),
        sa.Column("is_vip", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=True),
        # No FK: the billing domain owns these, and a live reference here
        # would be a second place billing configuration could be read from.
        sa.Column("contract_id", GUID(), nullable=True),
        sa.Column("contract_name", sa.String(255), nullable=True),
        sa.Column("pricing_profile_id", GUID(), nullable=True),
        sa.Column("segment", sa.String(120), nullable=True),
        sa.Column("contact_preference", sa.String(30), nullable=False, server_default="ANY"),
        sa.Column(
            "preferred_agent_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("extras", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "customer_id", "version", name="uq_customer_context_versions_customer_version"
        ),
    )
    op.create_index(
        "ix_customer_context_versions_fingerprint",
        "customer_context_versions",
        ["customer_id", "fingerprint"],
    )

    op.create_table(
        "runtime_queues",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "logical_queue_id",
            GUID(),
            sa.ForeignKey("queues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(30), nullable=False),
        # Zero means unlimited, not closed. A lane that refused everything
        # would drop conversations, and the guarantee is that a full lane
        # never refuses one.
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("overflow_queue_id", GUID(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("logical_queue_id", "kind", name="uq_runtime_queues_queue_kind"),
    )
    op.create_index("ix_runtime_queues_logical_queue_id", "runtime_queues", ["logical_queue_id"])
    op.create_index("ix_runtime_queues_company", "runtime_queues", ["company_id", "is_active"])
    op.create_foreign_key(
        "fk_runtime_queues_overflow",
        "runtime_queues",
        "runtime_queues",
        ["overflow_queue_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "conversation_context_bindings",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "conversation_id",
            GUID(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # RESTRICT: deleting a version a conversation is bound to would leave
        # it unable to say what rules it ran under — the one thing this whole
        # design guarantees.
        sa.Column(
            "service_version_id",
            GUID(),
            sa.ForeignKey("service_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "customer_context_version_id",
            GUID(),
            sa.ForeignKey("customer_context_versions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("reason", sa.String(40), nullable=False, server_default="BOUND_AT_START"),
        sa.Column("bound_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "bound_by_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.String(500), nullable=True),
    )
    op.create_index(
        "ix_conversation_context_bindings_current",
        "conversation_context_bindings",
        ["conversation_id", "bound_at"],
    )

    if _is_postgres():
        # The same shape as routing_decisions. One function per table rather
        # than a shared one, so dropping a table takes its trigger with it
        # and cannot leave another table's guarantee depending on a function
        # this migration's downgrade removed.
        for table, message in (
            (
                "service_versions",
                "service_versions is append-only; conversations are bound to a "
                "version and editing one would rewrite the rules they ran under",
            ),
            (
                "customer_context_versions",
                "customer_context_versions is append-only; a conversation reads "
                "the version it started with, and editing one would change it",
            ),
            (
                "conversation_context_bindings",
                "conversation_context_bindings is append-only; a rebinding is a "
                "new row, and an update would erase why a conversation moved",
            ),
        ):
            op.execute(
                f"""
                CREATE OR REPLACE FUNCTION {table}_append_only()
                RETURNS TRIGGER AS $$
                BEGIN
                  RAISE EXCEPTION '{message}';
                END;
                $$ LANGUAGE plpgsql
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER trg_{table}_immutable
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION {table}_append_only()
                """
            )


def downgrade() -> None:
    if _is_postgres():
        for table in (
            "conversation_context_bindings",
            "customer_context_versions",
            "service_versions",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_append_only()")

    op.drop_table("conversation_context_bindings")
    op.drop_constraint("fk_runtime_queues_overflow", "runtime_queues", type_="foreignkey")
    op.drop_table("runtime_queues")
    op.drop_table("customer_context_versions")
    # The services → service_versions pointer has to go before the table it
    # points at, or the drop fails on PostgreSQL.
    op.drop_constraint("fk_services_current_version", "services", type_="foreignkey")
    op.drop_table("service_versions")
    op.drop_table("services")
