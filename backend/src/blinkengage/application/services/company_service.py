"""``CompanyService`` — company profile + admin-configurable settings.
See ``docs/architecture/administration.md`` and
``docs/architecture/company-onboarding.md``.

No ``get_current_auth``-only read gate the way Notifications (personal,
per-user) work: a company's profile/settings are shared, company-wide
information, not a personal inbox, so viewing them only requires being
an authenticated member of the company (any role), while editing
requires ``company.manage``.
"""

from typing import Any
from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository


def _merge_settings(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Merges one level deeper than a plain ``{**existing, **patch}``: for
    any top-level key present in both and object-shaped on both sides,
    the *nested* keys are merged too rather than the whole section being
    replaced. Without this, a caller that PATCHes only
    ``{"business_hours": {"enabled": False}}`` (a perfectly ordinary
    partial PATCH — every field here is optional) would silently wipe out
    an already-saved weekly ``schedule``, and ``{"business_hours": {}}``
    would silently reset the whole section to schema defaults, both with
    a 200 OK and no signal anything was lost. A flat/scalar value (e.g. a
    plain string for ``language``, or a value that isn't a dict on either
    side) still fully replaces, matching ordinary PATCH semantics."""
    merged = dict(existing)
    for key, value in patch.items():
        current = merged.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merged[key] = {**current, **value}
        else:
            merged[key] = value
    return merged


class CompanyService:
    def __init__(self, *, companies: CompanyRepository, events: DomainEventPublisher) -> None:
        self._companies = companies
        self._events = events

    async def get(self, company_id: UUID) -> Company:
        company = await self._companies.get_by_id(company_id)
        if company is None:
            raise EntityNotFoundError("Company", company_id)
        return company

    async def update(
        self,
        *,
        company_id: UUID,
        name: str | None,
        settings_patch: dict[str, Any] | None,
        actor_user_id: UUID | None = None,
    ) -> Company:
        """``settings_patch`` is merged one level deep (see
        ``_merge_settings``): each top-level key present in it merges
        into that same key in the stored settings rather than replacing
        it outright, while every top-level key *not* present is left
        completely untouched. This is what lets independent Company
        Settings tabs (Branding, Business Hours, Notifications, ...) save
        without clobbering each other — and, within a section, what
        stops a partial or empty PATCH to that one section from
        silently discarding fields the caller didn't mention."""
        company = await self.get(company_id)
        if name is not None:
            company.name = name
        if settings_patch is not None:
            company.settings = _merge_settings(company.settings, settings_patch)
        await self._companies.save(company)
        await self._events.publish(
            DomainEvent(
                event_type="company.updated",
                company_id=company_id,
                aggregate_type="company",
                aggregate_id=company_id,
                actor_user_id=actor_user_id,
                payload={"name": company.name},
            )
        )
        return company
