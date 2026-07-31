"""Who at a customer hears about their bill.

One definition, deliberately. A dunning notice, an invoice sent by email and
anything else billing ever wants to tell a customer must reach the same people
— a system where the overdue notice goes to the finance manager and the
invoice itself goes to the account owner is one where each of them assumes the
other received it.

"Everybody who can act on it, and nobody who cannot": the set is derived from
the ``billing.read`` permission rather than from a role name or a stored
contact field. An agent handling conversations has no use for a payment
reminder and no way to act on one; a company that grants billing to three
people has told us, in the only place it is authoritative, who those three
are. It also means the answer follows a permission change on its own, with
nothing to keep in step.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.rbac import RolePermission, UserRole
from blinkengage.infrastructure.database.models.user import User

#: The permission that makes somebody a billing contact.
BILLING_PERMISSION = "billing.read"


async def billing_contact_ids(session: AsyncSession, company_id: uuid.UUID) -> list[uuid.UUID]:
    """Everybody at the company who can act on an invoice.

    Deactivated and deleted users are excluded — mailing somebody who has
    left is how a company comes to believe it was never told.
    """
    rows = await session.execute(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .where(
            User.company_id == company_id,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
            RolePermission.permission_code == BILLING_PERMISSION,
        )
        .distinct()
    )
    return list(rows.scalars().all())


async def billing_contact_emails(session: AsyncSession, company_id: uuid.UUID) -> list[str]:
    """The same people, as addresses.

    Returned in a stable order so a test — and a support conversation about
    who was mailed — can rely on it.
    """
    rows = await session.execute(
        select(User.email)
        .join(UserRole, UserRole.user_id == User.id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .where(
            User.company_id == company_id,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
            RolePermission.permission_code == BILLING_PERMISSION,
        )
        .distinct()
        .order_by(User.email)
    )
    return list(rows.scalars().all())


__all__ = ["BILLING_PERMISSION", "billing_contact_emails", "billing_contact_ids"]
