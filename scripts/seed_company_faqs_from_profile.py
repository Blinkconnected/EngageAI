"""Seed a company's FAQ set from the business facts it has already verified.

AI Autopilot may state only what it is given (see
``docs/architecture/ai-engine.md``'s grounding contract): the company's
business profile, plus whatever retrieval finds in its own Knowledge Base
and FAQs. A company that has filled in its profile but published no FAQs
is therefore answered narrowly — the profile reaches the prompt, but a
customer who phrases a question differently, or asks in another language,
matches nothing and is handed to a human.

This script closes that gap **without inventing anything**. Every answer
it writes is assembled from fields already stored on the company:
``settings.business_profile`` and ``settings.business_hours``. It has no
knowledge of what any company sells, and it will not write a claim those
two sources do not support. If a field is absent, the FAQs that depend on
it are skipped rather than filled with a plausible value — the whole
reason the grounding contract exists is that a plausible business fact is
indistinguishable from a true one once a customer has read it.

**Arabic FAQs are seeded alongside the English ones**, restating the same
verified fields. This is not decoration. Retrieval is hybrid, and where no
embedding provider is configured it degrades to lexical matching only — at
which point an Arabic question cannot match English text at all, and a
company whose customers write in Arabic gets a handoff for questions it
demonstrably has the answer to.

**Dry run is the default.** With no arguments it reports what it would
write and touches nothing.

    # what would happen
    docker compose exec backend python scripts/seed_company_faqs_from_profile.py --company <uuid>

    # do it
    docker compose exec backend python scripts/seed_company_faqs_from_profile.py \
        --company <uuid> --apply

Idempotent: an FAQ whose question already exists for that company is left
alone, so a re-run after a partial failure finishes the work rather than
doubling it. Existing answers are never overwritten — a human may have
edited them, and this script's content is a starting point, not a source
of truth.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from typing import Any

from blinkengage.application.services.embedding_service import EmbeddingService
from blinkengage.application.services.faq_service import FaqService
from blinkengage.core.config import get_settings
from blinkengage.infrastructure.database.session import create_engine, create_session_factory
from blinkengage.infrastructure.embeddings.factory import build_embedding_provider_for_company
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.event_outbox_repository import EventOutboxRepository
from blinkengage.infrastructure.repositories.faq_repository import FaqRepository
from blinkengage.infrastructure.repositories.knowledge_index_repository import (
    EmbeddingRepository,
    KnowledgeChunkRepository,
)

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_EN_DAY = {d: d.capitalize() for d in _WEEKDAYS}
_AR_DAY = {
    "monday": "الاثنين",
    "tuesday": "الثلاثاء",
    "wednesday": "الأربعاء",
    "thursday": "الخميس",
    "friday": "الجمعة",
    "saturday": "السبت",
    "sunday": "الأحد",
}


def _open_days(settings: dict[str, Any]) -> tuple[list[str], list[str], str | None, str | None]:
    """Open days, closed days, and the single open/close pair — but only
    when every open day shares one. A company with different hours per day
    gets no sentence rather than a wrong one; the structured schedule on
    the Business Hours tab remains the source of truth either way."""
    section = settings.get("business_hours")
    section = section if isinstance(section, dict) else {}
    if not section.get("enabled", False):
        return [], [], None, None
    schedule = section.get("schedule")
    schedule = schedule if isinstance(schedule, dict) else {}

    open_days: list[str] = []
    closed_days: list[str] = []
    pairs: set[tuple[str, str]] = set()
    for day in _WEEKDAYS:
        raw = schedule.get(day)
        if not isinstance(raw, dict):
            continue
        if raw.get("closed", False):
            closed_days.append(day)
            continue
        opens, closes = raw.get("open"), raw.get("close")
        if isinstance(opens, str) and isinstance(closes, str):
            open_days.append(day)
            pairs.add((opens, closes))

    if len(pairs) != 1:
        return open_days, closed_days, None, None
    opens, closes = next(iter(pairs))
    return open_days, closed_days, opens, closes


def _join(names: list[str], mapping: dict[str, str], conjunction: str) -> str:
    labels = [mapping[n] for n in names]
    if len(labels) == 1:
        return labels[0]
    return f"{', '.join(labels[:-1])} {conjunction} {labels[-1]}"


def build_faqs(settings: dict[str, Any]) -> list[tuple[str, str, str]]:
    """``(question, answer, locale)`` for every fact this company has
    actually recorded. Facts it has not recorded produce no FAQ."""
    profile = settings.get("business_profile")
    profile = profile if isinstance(profile, dict) else {}

    def field(key: str) -> str | None:
        value = profile.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    name = field("legal_name")
    location = field("location")
    contact = field("contact")
    website = field("website")
    about = field("about")

    faqs: list[tuple[str, str, str]] = []

    if name:
        # `about` is free text an administrator wrote ("ICT Provider"),
        # so it is appended rather than slotted into a sentence: "{name}
        # is {about}" produces "is ICT Provider" for exactly the phrasing
        # people actually use, and inventing the missing article would be
        # this script deciding how a company describes itself.
        who_en = f"{name} — {about}." if about else f"Our company is {name}."
        who_ar = f"{name} — {about}." if about else f"اسم شركتنا هو {name}."
        faqs += [
            ("What is your company name?", f"Our company is {name}.", "en"),
            ("Who are you?", who_en, "en"),
            ("ما اسم الشركة؟", f"اسم شركتنا هو {name}.", "ar"),
            ("شو اسم الشركه؟", f"اسم شركتنا هو {name}.", "ar"),
            ("شو بتعملو؟", who_ar, "ar"),
        ]
    if location:
        faqs += [
            ("Where are you located?", f"Our office is in {location}.", "en"),
            ("What is your address?", f"Our office is in {location}.", "en"),
            ("وين موقعكم؟", f"مكتبنا في {location}.", "ar"),
            ("ما هو عنوانكم؟", f"مكتبنا في {location}.", "ar"),
        ]
    if contact:
        faqs += [
            ("How can I contact you?", f"You can reach us at {contact}.", "en"),
            ("كيف أتواصل معكم؟", f"يمكنكم التواصل معنا على {contact}.", "ar"),
        ]
    if website:
        faqs += [
            ("What is your website?", f"Our website is {website}.", "en"),
            ("ما هو موقعكم الإلكتروني؟", f"موقعنا الإلكتروني هو {website}.", "ar"),
        ]

    open_days, closed_days, opens, closes = _open_days(settings)
    if open_days and opens and closes:
        en = f"We are open {_join(open_days, _EN_DAY, 'and')}, {opens} to {closes}."
        ar = f"نعمل أيام {_join(open_days, _AR_DAY, 'و')}، من الساعة {opens} حتى {closes}."
        if closed_days:
            en += f" We are closed on {_join(closed_days, _EN_DAY, 'and')}."
            ar += f" ونغلق أيام {_join(closed_days, _AR_DAY, 'و')}."
        faqs += [
            ("What are your business hours?", en, "en"),
            ("When are you open?", en, "en"),
            ("ما هي ساعات العمل؟", ar, "ar"),
            ("أي ساعة بتفتحوا؟", ar, "ar"),
        ]

    return faqs


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", required=True, help="company UUID")
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = parser.parse_args()

    company_id = uuid.UUID(args.company)
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)

    try:
        async with factory() as session:
            company = await CompanyRepository(session).get_by_id(company_id)
            if company is None:
                print(f"company {company_id} not found")
                return 1

            planned = build_faqs(company.settings)
            if not planned:
                print(
                    "nothing to seed: this company has no business profile and no "
                    "enabled business hours. Fill in Settings -> Business Profile "
                    "and Settings -> Business Hours first."
                )
                return 1

            existing_rows, _ = await FaqRepository(session).list_for_company(
                company_id=company_id, offset=0, limit=1000
            )
            existing = {row.question for row in existing_rows}
            to_create = [entry for entry in planned if entry[0] not in existing]

            print(f"company        : {company.name}")
            print(f"planned        : {len(planned)}")
            print(f"already present: {len(planned) - len(to_create)}")
            print(f"to create      : {len(to_create)}")
            for question, answer, locale in to_create:
                print(f"  [{locale}] {question}  ->  {answer}")

            if not args.apply:
                print("\ndry run — nothing written. Re-run with --apply to write.")
                return 0

            events = OutboxEventPublisher(EventOutboxRepository(session))
            faq_service = FaqService(faqs=FaqRepository(session), events=events)
            embedding_provider = build_embedding_provider_for_company(settings, company.ai_config)
            embeddings = EmbeddingService(
                provider=embedding_provider,
                chunks=KnowledgeChunkRepository(session),
                embeddings=EmbeddingRepository(session),
                batch_size=settings.embedding_batch_size,
                max_attempts=settings.embedding_index_max_attempts,
            )

            created = []
            for question, answer, locale in to_create:
                created.append(
                    await faq_service.create(
                        company_id=company_id,
                        question=question,
                        answer=answer,
                        locale=locale,
                        is_published=True,
                    )
                )
            await session.flush()

            vectors = 0
            for faq in created:
                result = await embeddings.index_faq(faq)
                vectors += int(getattr(result, "embedded", 0) or 0)
            await session.commit()

            print(f"\ncreated {len(created)} published FAQs; {vectors} vectors written")
            if embedding_provider is None:
                print(
                    "note: no embedding provider is configured, so retrieval for these "
                    "FAQs is lexical only. Configure one to enable semantic matching."
                )
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
