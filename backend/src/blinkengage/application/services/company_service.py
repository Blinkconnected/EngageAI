"""``CompanyService`` — company profile + admin-configurable settings.
See ``docs/architecture/administration.md`` and
``docs/architecture/company-onboarding.md``.

No ``get_current_auth``-only read gate the way Notifications (personal,
per-user) work: a company's profile/settings are shared, company-wide
information, not a personal inbox, so viewing them only requires being
an authenticated member of the company (any role), while editing
requires ``company.manage``.
"""

from contextlib import suppress
from typing import Any
from uuid import UUID, uuid4

from blinkengage.application.services.attachment_validation import validate_logo
from blinkengage.core.config import Settings
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import AttachmentValidationError, EntityNotFoundError
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.storage.attachment_store import AttachmentStore

_LOGO_EXTENSION_BY_CONTENT_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


def _section(settings: dict[str, Any], key: str) -> dict[str, Any]:
    """Same defensive semantics as ``domain.company_settings``'s private
    helper of the same name (a section may be absent, an explicit
    ``None``, or — on a hand-edited row — some other non-dict value) —
    not imported from there since that module is a read-only, framework-
    free reader and shouldn't gain a dependency on this service."""
    value = settings.get(key)
    return value if isinstance(value, dict) else {}


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
    def __init__(
        self,
        *,
        companies: CompanyRepository,
        events: DomainEventPublisher,
        logos: AttachmentStore,
        settings: Settings,
    ) -> None:
        self._companies = companies
        self._events = events
        self._logos = logos
        self._settings = settings

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

    async def update_ai_config(
        self,
        *,
        company_id: UUID,
        provider: str | None,
        api_key: str | None,
        model: str | None,
        base_url: str | None,
        deployment_name: str | None = None,
        api_version: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> Company:
        """``provider=None`` clears the override entirely (reverts to the
        platform default) — ``api_key=None`` otherwise means "leave
        whatever was already saved," so switching models doesn't force
        re-entering a key that hasn't changed. See
        ``api.schemas.company.AiConfigUpdateRequest``'s docstring for why
        there's no separate "clear just the key" operation.
        ``deployment_name``/``api_version`` are Azure OpenAI-only —
        harmless, unread keys for every other provider — and, like
        ``model``/``base_url`` (and unlike ``api_key``), they're not
        secret, so the caller is expected to resend the full desired
        value on every update rather than have it preserved when
        omitted."""
        company = await self.get(company_id)
        if provider is None:
            company.ai_config = None
        else:
            existing = company.ai_config or {}
            # A saved key is only ever carried forward for the SAME
            # provider it was saved under — switching vendors (e.g.
            # openai -> claude) must never silently forward the old
            # vendor's secret into the new one's Authorization header.
            same_provider = existing.get("provider") == provider
            preserved_key = existing.get("api_key") if same_provider else None
            company.ai_config = {
                "provider": provider,
                "api_key": api_key if api_key else preserved_key,
                "model": model,
                "base_url": base_url,
                "deployment_name": deployment_name,
                "api_version": api_version,
            }
        await self._companies.save(company)
        # Never the key itself — only whether one ended up set, same as
        # what GET /company/ai-config itself is willing to reveal.
        await self._events.publish(
            DomainEvent(
                event_type="company.ai_config_updated",
                company_id=company_id,
                aggregate_type="company",
                aggregate_id=company_id,
                actor_user_id=actor_user_id,
                payload={
                    "provider": provider,
                    "api_key_set": bool(company.ai_config and company.ai_config.get("api_key")),
                },
            )
        )
        return company

    async def upload_logo(
        self,
        *,
        company_id: UUID,
        content_type: str,
        data: bytes,
        actor_user_id: UUID | None = None,
    ) -> Company:
        """Stores the logo directly in the shared attachment bucket under
        a ``logos/`` prefix — only the storage key/content type (never a
        raw uploader-supplied URL) end up in ``Company.settings``, so
        ``GET /company/logo`` is the only way to actually read the bytes
        back, gated the same as every other company-wide read."""
        result = validate_logo(
            content_type=content_type, size_bytes=len(data), settings=self._settings
        )
        if not result.approved:
            raise AttachmentValidationError(result.reason or "Logo rejected")

        company = await self.get(company_id)
        previous_key = _section(company.settings, "branding").get("logo_key")

        extension = _LOGO_EXTENSION_BY_CONTENT_TYPE[content_type]
        new_key = f"logos/{company_id}/{uuid4()}.{extension}"
        await self._logos.upload(key=new_key, data=data, content_type=content_type)

        company.settings = _merge_settings(
            company.settings,
            {"branding": {"logo_key": new_key, "logo_content_type": content_type}},
        )
        await self._companies.save(company)

        if previous_key and previous_key != new_key:
            # Best-effort: an orphaned old object left behind on a failed
            # delete is harmless clutter, not worth failing this request
            # (whose own upload has already succeeded and been saved).
            with suppress(Exception):
                await self._logos.delete(key=previous_key)

        await self._events.publish(
            DomainEvent(
                event_type="company.logo_updated",
                company_id=company_id,
                aggregate_type="company",
                aggregate_id=company_id,
                actor_user_id=actor_user_id,
                payload={"content_type": content_type, "size_bytes": len(data)},
            )
        )
        return company

    async def delete_logo(self, *, company_id: UUID, actor_user_id: UUID | None = None) -> Company:
        company = await self.get(company_id)
        previous_key = _section(company.settings, "branding").get("logo_key")

        company.settings = _merge_settings(
            company.settings, {"branding": {"logo_key": None, "logo_content_type": None}}
        )
        await self._companies.save(company)

        if previous_key:
            with suppress(Exception):
                await self._logos.delete(key=previous_key)

        await self._events.publish(
            DomainEvent(
                event_type="company.logo_removed",
                company_id=company_id,
                aggregate_type="company",
                aggregate_id=company_id,
                actor_user_id=actor_user_id,
                payload={},
            )
        )
        return company

    async def get_logo(self, *, company_id: UUID) -> tuple[bytes, str] | None:
        """``None`` when the company has no logo set — distinct from a
        storage-layer failure, which still raises."""
        company = await self.get(company_id)
        branding = _section(company.settings, "branding")
        logo_key = branding.get("logo_key")
        content_type = branding.get("logo_content_type")
        if not logo_key or not content_type:
            return None
        data = await self._logos.download(key=logo_key)
        return data, content_type
