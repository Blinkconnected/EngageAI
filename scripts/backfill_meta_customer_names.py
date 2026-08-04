"""Backfill display names for Messenger/Instagram customers created before
the sender-name lookup existed.

Meta's Messenger-platform webhooks carry only a sender id, never a name, so
until `MetaMessagingProvider._fetch_sender_name` was added every new contact
was created with the raw id as its `Customer.full_name` — a seventeen-digit
number in the inbox. New contacts now get a real name; this script fixes the
ones already stored.

Only rewrites a customer whose `full_name` is still *exactly* its external
id. A name that differs — set by an agent, or carried over from another
channel where the same person was already known — is left alone, so running
this can never overwrite a human's correction.

The lookup fails legitimately for some senders (Meta refuses profiles the
app has no access to, and nearly all of them while the app is in
development mode). Those are reported and skipped, not treated as errors.

Runs inside the backend container, which has the app's settings and
credential decryption:

    docker compose exec -T backend python - --apply < scripts/backfill_meta_customer_names.py

Without ``--apply`` it only reports what it would change.
"""

import asyncio
import sys

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from blinkengage.core.config import get_settings
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
from blinkengage.infrastructure.database.models.customer import Customer
from blinkengage.infrastructure.database.models.customer_channel_identity import (
    CustomerChannelIdentity,
)

# Both share MetaMessagingProvider, so both store a bare sender id and both
# resolve a name from the same Graph User Profile endpoint.
META_CHANNEL_TYPES = ("messenger", "instagram")

_DEFAULT_API_BASE_URL = "https://graph.facebook.com"
_DEFAULT_API_VERSION = "v21.0"


async def _fetch_name(
    client: httpx.AsyncClient, *, credentials: dict, external_id: str
) -> str | None:
    """Same contract as the provider's ``_fetch_sender_name``: a name, or
    ``None`` for any failure at all. Deliberately duplicated rather than
    imported, because the provider's copy needs a fully constructed provider
    (realtime publisher, attachment storage) that a maintenance script has no
    reason to build."""
    base = credentials.get("graph_api_base_url", _DEFAULT_API_BASE_URL)
    version = credentials.get("api_version", _DEFAULT_API_VERSION)
    try:
        response = await client.get(
            f"{base}/{version}/{external_id}",
            params={
                "access_token": credentials.get("access_token", ""),
                "fields": "first_name,last_name",
            },
        )
        response.raise_for_status()
        profile = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    name = " ".join(
        str(part)
        for part in (profile.get("first_name"), profile.get("last_name"))
        if part is not None and str(part).strip()
    ).strip()
    return name or None


async def main(apply: bool) -> None:
    settings = get_settings()
    engine = create_async_engine(str(settings.database_url))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    renamed = skipped = untouched = 0
    async with session_factory() as db:
        configs = (
            (
                await db.execute(
                    select(ChannelConfig).where(
                        ChannelConfig.channel_type.in_(META_CHANNEL_TYPES),
                        ChannelConfig.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not configs:
            print("no active messenger/instagram channels — nothing to do")
            return

        # An identity is keyed by (company, channel_type, external_id) — not by
        # channel config — so several configs of the same type in one company
        # all address the same people. Group them and walk each identity once,
        # trying configs until one resolves the name: an installation
        # accumulates superseded channels whose tokens have since expired, and
        # iterating configs on the outside would retry every person against
        # every dead token and report the same failure repeatedly.
        by_scope: dict[tuple, list[ChannelConfig]] = {}
        for config in configs:
            by_scope.setdefault((config.company_id, config.channel_type), []).append(config)

        async with httpx.AsyncClient(timeout=30) as client:
            for (company_id, channel_type), scope_configs in by_scope.items():
                rows = (
                    await db.execute(
                        select(CustomerChannelIdentity, Customer)
                        .join(Customer, Customer.id == CustomerChannelIdentity.customer_id)
                        .where(
                            CustomerChannelIdentity.channel_type == channel_type,
                            CustomerChannelIdentity.company_id == company_id,
                        )
                    )
                ).all()
                names = ", ".join(c.display_name for c in scope_configs)
                print(f"\n== {channel_type}: {len(rows)} identities via {len(scope_configs)} channel(s) [{names}]")
                for identity, customer in rows:
                    if customer.full_name != identity.external_id:
                        untouched += 1
                        continue
                    name = None
                    for config in scope_configs:
                        name = await _fetch_name(
                            client,
                            credentials=config.credentials,
                            external_id=identity.external_id,
                        )
                        if name is not None:
                            break
                    if name is None:
                        print(f"   skip   {identity.external_id} — profile unreadable")
                        skipped += 1
                        continue
                    print(f"   rename {identity.external_id} -> {name}")
                    if apply:
                        customer.full_name = name
                    renamed += 1
        if apply:
            await db.commit()

    print(
        f"\n{'applied' if apply else 'DRY RUN'}: {renamed} renamed, "
        f"{skipped} unreadable, {untouched} already had a real name"
    )
    if not apply and renamed:
        print("re-run with --apply to write these changes")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
