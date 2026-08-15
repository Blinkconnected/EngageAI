"""Phase 4G-1 step 1: the turn store, and the constraint that makes replay safe.

The table exists for two things an audit log cannot do — hold a conversation
and hold the reply a repeated request must get back. These tests are mostly
about the second, because the partial unique index is the whole mechanism: an
application-level "has this key been used?" cannot work when two requests carry
the same key and both read *no* before either writes.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from blinkengage.infrastructure.database.models.ai_assistant_turn import AiAssistantTurn
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.user import User


def _turn(company_id: UUID, user_id: UUID, **overrides: Any) -> AiAssistantTurn:
    values: dict[str, Any] = {
        "company_id": company_id,
        "user_id": user_id,
        "session_id": uuid4(),
        "turn_id": uuid4(),
        "user_message": "what is our DIA 500 price?",
        "reply": "It is 180 JOD.",
        "model_identifier": "test-model",
        "correlation_id": "corr-1",
        "citations": [],
    }
    values.update(overrides)
    return AiAssistantTurn(**values)


@pytest.mark.usefixtures("registered_owner")
class TestAiAssistantTurns:
    @staticmethod
    async def _company_and_user(session: Any) -> tuple[UUID, UUID]:
        company = (await session.execute(select(Company))).scalars().first()
        user = (await session.execute(select(User))).scalars().first()
        assert company is not None and user is not None
        return company.id, user.id

    @staticmethod
    async def _extra_company(session: Any) -> UUID:
        company = Company(name="Other Co", slug=f"other-{uuid4().hex[:8]}")
        session.add(company)
        await session.flush()
        return company.id

    async def test_a_turn_can_be_created_and_read_back(self, app: Any) -> None:
        async with app.state.container.session_factory()() as session:
            company_id, user_id = await self._company_and_user(session)
            turn = _turn(company_id, user_id, citations=[{"record_id": str(uuid4())}])
            session.add(turn)
            await session.commit()

            stored = (
                (
                    await session.execute(
                        select(AiAssistantTurn).where(AiAssistantTurn.id == turn.id)
                    )
                )
                .scalars()
                .one()
            )

        assert stored.company_id == company_id
        assert stored.user_id == user_id
        assert stored.reply == "It is 180 JOD."
        assert stored.user_message.startswith("what is our DIA")
        assert stored.model_identifier == "test-model"
        assert stored.correlation_id == "corr-1"
        assert stored.created_at is not None

    async def test_the_turn_id_round_trips(self, app: Any) -> None:
        """A replay is recognised by it, so it must survive storage exactly."""
        turn_id = uuid4()

        async with app.state.container.session_factory()() as session:
            company_id, user_id = await self._company_and_user(session)
            session.add(_turn(company_id, user_id, turn_id=turn_id))
            await session.commit()

            found = (
                (
                    await session.execute(
                        select(AiAssistantTurn).where(
                            AiAssistantTurn.company_id == company_id,
                            AiAssistantTurn.turn_id == turn_id,
                        )
                    )
                )
                .scalars()
                .one()
            )

        assert found.turn_id == turn_id

    async def test_citations_persist_as_structured_data(self, app: Any) -> None:
        citations = [
            {
                "record_id": str(uuid4()),
                "subject_label": "DIA 500 Mbps",
                "lifecycle_state": "ACTIVE",
            }
        ]

        async with app.state.container.session_factory()() as session:
            company_id, user_id = await self._company_and_user(session)
            turn = _turn(company_id, user_id, citations=citations)
            session.add(turn)
            await session.commit()

            stored = await session.get(AiAssistantTurn, turn.id)

        assert stored is not None
        assert stored.citations[0]["subject_label"] == "DIA 500 Mbps"
        assert stored.citations[0]["lifecycle_state"] == "ACTIVE"

    # --- the idempotency constraint -----------------------------------

    async def test_many_turns_may_have_no_key(self, app: Any) -> None:
        """The common case. A non-partial index would stack every unkeyed turn
        into the same constraint for no purpose."""
        async with app.state.container.session_factory()() as session:
            company_id, user_id = await self._company_and_user(session)
            session.add(_turn(company_id, user_id, idempotency_key=None))
            session.add(_turn(company_id, user_id, idempotency_key=None))
            session.add(_turn(company_id, user_id, idempotency_key=None))
            await session.commit()

            count = len(
                (
                    await session.execute(
                        select(AiAssistantTurn).where(AiAssistantTurn.company_id == company_id)
                    )
                )
                .scalars()
                .all()
            )

        assert count == 3

    async def test_a_duplicate_key_is_rejected_by_the_database(self, app: Any) -> None:
        """The mechanism replay safety rests on.

        Not an application check: two requests carrying one key both read "no
        such turn" before either writes, and only the index settles it.
        """
        async with app.state.container.session_factory()() as session:
            company_id, user_id = await self._company_and_user(session)
            session.add(_turn(company_id, user_id, idempotency_key="key-1"))
            await session.commit()

            session.add(_turn(company_id, user_id, idempotency_key="key-1"))
            with pytest.raises(IntegrityError):
                await session.commit()

    async def test_the_same_key_in_two_companies_is_allowed(self, app: Any) -> None:
        """Keys are chosen by clients; one tenant's must never collide with
        another's."""
        async with app.state.container.session_factory()() as session:
            company_id, user_id = await self._company_and_user(session)
            other_company = await self._extra_company(session)

            session.add(_turn(company_id, user_id, idempotency_key="shared"))
            session.add(_turn(other_company, user_id, idempotency_key="shared"))
            await session.commit()

            rows = (
                (
                    await session.execute(
                        select(AiAssistantTurn).where(AiAssistantTurn.idempotency_key == "shared")
                    )
                )
                .scalars()
                .all()
            )

        assert len(rows) == 2

    async def test_the_same_key_for_two_users_is_allowed(self, app: Any) -> None:
        async with app.state.container.session_factory()() as session:
            company_id, user_id = await self._company_and_user(session)
            other_user = User(
                email=f"second-{uuid4().hex[:8]}@example.com",
                hashed_password="x",
                full_name="Second Admin",
                company_id=company_id,
            )
            session.add(other_user)
            await session.flush()

            session.add(_turn(company_id, user_id, idempotency_key="per-user"))
            session.add(_turn(company_id, other_user.id, idempotency_key="per-user"))
            await session.commit()

            rows = (
                (
                    await session.execute(
                        select(AiAssistantTurn).where(AiAssistantTurn.idempotency_key == "per-user")
                    )
                )
                .scalars()
                .all()
            )

        assert len(rows) == 2

    # --- schema shape --------------------------------------------------

    async def test_the_constraints_and_indexes_exist_as_intended(self, app: Any) -> None:
        """Asserted against the created schema, not the model source: an index
        that fails to be created is exactly the failure this table cannot
        tolerate, and the model file would still look correct."""

        def _read(connection: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            inspector = inspect(connection)
            return (
                inspector.get_indexes("ai_assistant_turns"),
                inspector.get_foreign_keys("ai_assistant_turns"),
            )

        async with app.state.container.session_factory()() as session:
            indexes, foreign_keys = await session.run_sync(
                lambda sync_session: _read(sync_session.connection())
            )

        names = {index["name"] for index in indexes}
        assert "uq_ai_assistant_turns_idempotency" in names
        assert "ix_ai_assistant_turns_company_session" in names
        assert "ix_ai_assistant_turns_company_turn" in names

        idempotency = next(
            index for index in indexes if index["name"] == "uq_ai_assistant_turns_idempotency"
        )
        # Truthy rather than ``is True``: SQLite's inspector reports 1.
        assert bool(idempotency["unique"])
        assert idempotency["column_names"] == ["company_id", "user_id", "idempotency_key"]

        referred = {fk["referred_table"] for fk in foreign_keys}
        assert "companies" in referred
        assert "users" in referred


class TestAiActionLogsAreUntouched:
    """4G-1 adds a table; it does not repurpose the audit one."""

    def test_the_audit_model_was_not_modified(self) -> None:
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[2]
            / "src/blinkengage/infrastructure/database/models/ai_action.py"
        ).read_text()

        # Still scoped to mutations, and still carrying no reply or key.
        assert "One AI-initiated mutation" in source
        assert "idempotency_key" not in source
        assert "reply" not in source
