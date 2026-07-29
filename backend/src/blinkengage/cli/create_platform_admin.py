"""Creates a platform (super) administrator.

Deliberately a CLI, not an API endpoint. A platform admin can suspend
every company on the installation, so there must be no HTTP route that
mints one — bootstrapping requires shell access to the server, which is
the same trust level as the database itself. Subsequent admins are
created the same way; there is intentionally no "invite a platform admin"
flow, because that would put the most privileged account in the product
behind an email link.

    python -m blinkengage.cli.create_platform_admin ops@example.com "Ops Name"

The password is read interactively (never as an argv, which would land in
shell history and the process table). Re-running for an existing platform
admin resets their password rather than erroring, so this doubles as the
recovery path if the only operator account is locked out.
"""

import asyncio
import getpass
import sys

from sqlalchemy import select

from blinkengage.core.config import get_settings
from blinkengage.core.security import hash_password
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)

_MIN_PASSWORD_LENGTH = 12


async def create_platform_admin(email: str, full_name: str, password: str) -> str:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_scope(session_factory) as session:
            normalized = email.strip().lower()
            existing = (
                await session.execute(
                    select(User).where(User.email == normalized, User.deleted_at.is_(None))
                )
            ).scalar_one_or_none()

            if existing is not None:
                if not existing.is_platform_admin:
                    # Refuses rather than promoting: silently turning a
                    # tenant's user into a platform operator would be an
                    # invisible privilege escalation on somebody else's
                    # account.
                    raise SystemExit(
                        f"{normalized} already exists as a user of a company. "
                        "Use a dedicated address for a platform administrator."
                    )
                existing.hashed_password = hash_password(password)
                existing.is_active = True
                return f"Reset the password for existing platform administrator {normalized}."

            session.add(
                User(
                    company_id=None,
                    email=normalized,
                    hashed_password=hash_password(password),
                    full_name=full_name.strip(),
                    is_company_owner=False,
                    is_platform_admin=True,
                )
            )
            return f"Created platform administrator {normalized}."
    finally:
        await engine.dispose()


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: python -m blinkengage.cli.create_platform_admin <email> <full name>"
        )
    email, full_name = sys.argv[1], sys.argv[2]
    password = getpass.getpass("Password: ")
    if len(password) < _MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Password must be at least {_MIN_PASSWORD_LENGTH} characters.")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords do not match.")
    print(asyncio.run(create_platform_admin(email, full_name, password)))


if __name__ == "__main__":
    main()
