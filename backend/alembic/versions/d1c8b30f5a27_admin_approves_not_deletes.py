"""Administrators approve deletions; they do not delete directly.

`conversations.delete` was briefly granted to the Admin system role, and
the generic permission sync is additive-only — it never revokes — so
removing the grant from `DEFAULT_ROLE_PERMISSIONS` alone would leave
every existing Admin still holding it and this change cosmetic. This
migration performs the revocation the sync cannot.

Only from roles whose grants still match the system default
(`permissions_customized = false`). A company that deliberately gave its
Admins direct deletion has made a decision, and a migration that
silently overrules it is worse than the inconsistency it fixes.

Revision ID: d1c8b30f5a27
Revises: c9a2f4e71b83
Create Date: 2026-08-08

"""

import sqlalchemy as sa

from alembic import op

revision = "d1c8b30f5a27"
down_revision = "c9a2f4e71b83"
branch_labels = None
depends_on = None

_DIRECT = "conversations.delete"
_APPROVE = "conversations.delete_approve"


def upgrade() -> None:
    bind = op.get_bind()

    # The catalogue row first: a grant referencing a permission that does
    # not exist violates the foreign key. The generic sync would seed it
    # on the next deploy, but this migration cannot depend on having run
    # after it.
    bind.execute(
        sa.text(
            "INSERT INTO permissions (code, description) VALUES (:code, :description) "
            "ON CONFLICT (code) DO NOTHING"
        ),
        {
            "code": _APPROVE,
            "description": "Approve or reject a request to delete a conversation",
        },
    )

    # Grant the new one to every Admin role, and to Owner, which holds
    # everything by definition.
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_code) "
            "SELECT r.id, :code FROM roles r WHERE r.name IN ('Admin', 'Owner') "
            "ON CONFLICT DO NOTHING"
        ),
        {"code": _APPROVE},
    )

    # Then take away the direct one — Admin only, never Owner, and never
    # from a role somebody has customised.
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions rp USING roles r "
            "WHERE rp.role_id = r.id AND r.name = 'Admin' "
            "AND rp.permission_code = :code "
            "AND r.permissions_customized = false"
        ),
        {"code": _DIRECT},
    )


def downgrade() -> None:
    bind = op.get_bind()
    # Restores the previous shape: Admin deletes directly, and does not
    # hold the approve permission that did not exist before this.
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_code) "
            "SELECT r.id, :code FROM roles r "
            "WHERE r.name = 'Admin' AND r.permissions_customized = false "
            "ON CONFLICT DO NOTHING"
        ),
        {"code": _DIRECT},
    )
    bind.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_code = :code"),
        {"code": _APPROVE},
    )
    bind.execute(sa.text("DELETE FROM permissions WHERE code = :code"), {"code": _APPROVE})
