from typing import Any
from uuid import UUID

from blinkengage.domain.exceptions import EntityAlreadyExistsError, EntityNotFoundError
from blinkengage.infrastructure.database.models.customer import Customer, CustomerTag, Tag
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
from blinkengage.infrastructure.repositories.tag_repository import TagRepository


class CustomerService:
    def __init__(self, *, customers: CustomerRepository, tags: TagRepository) -> None:
        self._customers = customers
        self._tags = tags

    async def create(
        self,
        *,
        company_id: UUID,
        full_name: str,
        email: str | None,
        phone: str | None,
        notes: str | None,
        custom_fields: dict[str, Any],
        tag_names: list[str],
    ) -> Customer:
        normalized_email = email.strip().lower() if email else None
        if normalized_email is not None:
            existing = await self._customers.get_by_email(
                company_id=company_id, email=normalized_email
            )
            if existing is not None:
                raise EntityAlreadyExistsError("Customer", "email", normalized_email)

        tags = await self._resolve_tags(company_id=company_id, tag_names=tag_names)
        # Tags are assigned on the transient (not-yet-flushed) object, so this
        # collection is "loaded" from the start — no reload needed before a
        # later caller reads `.customer_tags` (see the note on `_set_tags`
        # below for what goes wrong if you touch an unloaded collection on an
        # already-persistent object instead).
        customer = Customer(
            company_id=company_id,
            full_name=full_name.strip(),
            email=normalized_email,
            phone=phone.strip() if phone else None,
            notes=notes,
            custom_fields=custom_fields,
            customer_tags=[CustomerTag(tag=tag) for tag in tags],
        )
        return await self._customers.add(customer)

    async def get(self, *, company_id: UUID, customer_id: UUID) -> Customer:
        customer = await self._customers.get_by_id(company_id=company_id, customer_id=customer_id)
        if customer is None:
            raise EntityNotFoundError("Customer", customer_id)
        return customer

    async def list_customers(
        self, *, company_id: UUID, offset: int, limit: int, search: str | None
    ) -> tuple[list[Customer], int]:
        return await self._customers.list_for_company(
            company_id=company_id, offset=offset, limit=limit, search=search
        )

    async def update(
        self,
        *,
        company_id: UUID,
        customer_id: UUID,
        full_name: str | None,
        email: str | None,
        phone: str | None,
        notes: str | None,
        custom_fields: dict[str, Any] | None,
        tag_names: list[str] | None,
    ) -> Customer:
        customer = await self.get(company_id=company_id, customer_id=customer_id)

        if email is not None:
            normalized_email = email.strip().lower() or None
            if normalized_email is not None and normalized_email != customer.email:
                existing = await self._customers.get_by_email(
                    company_id=company_id, email=normalized_email
                )
                if existing is not None:
                    raise EntityAlreadyExistsError("Customer", "email", normalized_email)
            customer.email = normalized_email
        if full_name is not None:
            customer.full_name = full_name.strip()
        if phone is not None:
            customer.phone = phone.strip() or None
        if notes is not None:
            customer.notes = notes
        if custom_fields is not None:
            customer.custom_fields = custom_fields
        if tag_names is not None:
            await self._set_tags(company_id=company_id, customer=customer, tag_names=tag_names)

        return customer

    async def delete(self, *, company_id: UUID, customer_id: UUID) -> None:
        customer = await self.get(company_id=company_id, customer_id=customer_id)
        await self._customers.soft_delete(customer)

    async def _resolve_tags(self, *, company_id: UUID, tag_names: list[str]) -> list[Tag]:
        names = {name.strip() for name in tag_names if name.strip()}
        return [
            await self._tags.get_or_create(company_id=company_id, name=name)
            for name in sorted(names)
        ]

    async def _set_tags(
        self, *, company_id: UUID, customer: Customer, tag_names: list[str]
    ) -> None:
        """Replace ``customer``'s tags with exactly ``tag_names``.

        Mutates the ``customer.customer_tags`` collection directly (append/
        remove) rather than inserting/deleting ``CustomerTag`` rows through
        the session independently of it. The latter was a real bug: within
        one request, ``customer`` is already in the session's identity map,
        so a second fetch after mutating rows out-of-band doesn't see the
        change — the identity map hands back the same (now-stale) cached
        object instead of re-querying. Only ``customer`` here must already
        have ``customer_tags`` eager-loaded (true for every caller of this
        method, via ``get()``).
        """
        desired = {name.strip() for name in tag_names if name.strip()}
        current = {ct.tag.name: ct for ct in customer.customer_tags}

        for name in current.keys() - desired:
            customer.customer_tags.remove(current[name])

        for name in desired - current.keys():
            tag = await self._tags.get_or_create(company_id=company_id, name=name)
            customer.customer_tags.append(CustomerTag(tag=tag))
