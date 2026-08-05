"""The Memory Platform's HTTP surface, and Conversation Memory.

Consumers of this platform reach it through these endpoints, so the shape
of the responses is part of the contract — particularly that a fact
arrives with its provenance rather than as a bare assertion.
"""

from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.infrastructure.database.models.company import Company


async def _company_id(app) -> UUID:
    async with app.state.container.session_factory()() as session:
        company = (await session.execute(select(Company))).scalars().first()
        assert company is not None
        return company.id


def _record_payload(company_id: UUID, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "tier": "organizational",
        "fact_type": "terminology",
        "subject_type": "company",
        "subject_id": str(company_id),
        "topic": "Silver plan",
        "statement": "'Silver' is the mid pricing tier, not a colour.",
        "created_from": "agent",
        # ``agent_statement`` corroborates, and corroboration is what lifts
        # a fact past CANDIDATE — so it must name the agent. See E3.
        "evidence": [
            {
                "source_type": "agent_statement",
                "source_id": str(uuid4()),
                "agent_id": str(uuid4()),
            }
        ],
    }
    payload.update(overrides)
    return payload


class TestRecordingThroughTheApi:
    async def test_a_fact_can_be_recorded_and_read_back(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        company_id = await _company_id(app)

        created = await client.post(
            "/api/v1/memory/facts", headers=owner_headers, json=_record_payload(company_id)
        )
        assert created.status_code == 201, created.text
        body = created.json()

        assert body["support_count"] == 1
        assert body["has_corroboration"] is True
        assert body["display_label"] in {"observed", "candidate", "confirmed", "trusted"}

        listed = await client.get("/api/v1/memory/facts", headers=owner_headers)
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

    async def test_recording_without_evidence_is_rejected_at_the_boundary(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        """Checked here *and* in the domain. The API answer is a 422 a
        caller can act on; the domain refusal holds for callers that never
        come through HTTP at all."""
        company_id = await _company_id(app)

        response = await client.post(
            "/api/v1/memory/facts",
            headers=owner_headers,
            json=_record_payload(company_id, evidence=[]),
        )

        assert response.status_code == 422

    async def test_an_unknown_fact_type_is_rejected(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        company_id = await _company_id(app)

        response = await client.post(
            "/api/v1/memory/facts",
            headers=owner_headers,
            json=_record_payload(company_id, fact_type="invented_type"),
        )

        assert response.status_code == 400, response.text

    async def test_a_fact_arrives_with_its_evidence(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        """The first question asked of a remembered claim is where it came
        from, so the answer travels with it."""
        company_id = await _company_id(app)
        created = await client.post(
            "/api/v1/memory/facts", headers=owner_headers, json=_record_payload(company_id)
        )
        fact_id = created.json()["id"]

        response = await client.get(f"/api/v1/memory/facts/{fact_id}", headers=owner_headers)

        assert response.status_code == 200
        evidence = response.json()["evidence"]
        assert len(evidence) == 1
        assert evidence[0]["source_type"] == "agent_statement"

    async def test_evidence_carries_no_customer_content(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        """Pointers, never copies. A transcript here would put customer
        content into a second store with different retention."""
        company_id = await _company_id(app)
        created = await client.post(
            "/api/v1/memory/facts", headers=owner_headers, json=_record_payload(company_id)
        )
        fact_id = created.json()["id"]

        response = await client.get(f"/api/v1/memory/facts/{fact_id}", headers=owner_headers)

        evidence_fields = set(response.json()["evidence"][0])
        assert not (evidence_fields & {"excerpt", "body", "text", "content", "message"})


class TestHumanControls:
    async def test_confirming_and_suppressing(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        company_id = await _company_id(app)
        fact_id = (
            await client.post(
                "/api/v1/memory/facts", headers=owner_headers, json=_record_payload(company_id)
            )
        ).json()["id"]

        confirmed = await client.post(
            f"/api/v1/memory/facts/{fact_id}/confirm", headers=owner_headers
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["human_state"] == "confirmed"
        assert confirmed.json()["last_confirmed_at"] is not None

        suppressed = await client.post(
            f"/api/v1/memory/facts/{fact_id}/suppress", headers=owner_headers, json={}
        )
        assert suppressed.status_code == 200
        assert suppressed.json()["display_label"] == "suppressed"

        # Suppressed facts leave the retrievable set, which is what every
        # consumer of the platform reads.
        listed = await client.get("/api/v1/memory/facts", headers=owner_headers)
        assert listed.json()["total"] == 0

        everything = await client.get(
            "/api/v1/memory/facts", headers=owner_headers, params={"retrievable_only": False}
        )
        assert everything.json()["total"] == 1

    async def test_correcting_keeps_the_evidence(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        """The observation was real; the wording was wrong."""
        company_id = await _company_id(app)
        fact_id = (
            await client.post(
                "/api/v1/memory/facts", headers=owner_headers, json=_record_payload(company_id)
            )
        ).json()["id"]

        response = await client.post(
            f"/api/v1/memory/facts/{fact_id}/correct",
            headers=owner_headers,
            json={"statement": "Silver is the middle tier."},
        )

        assert response.status_code == 200
        assert response.json()["statement"] == "Silver is the middle tier."
        assert response.json()["support_count"] == 1


class TestErasureEndpoint:
    async def test_erasing_a_customer_reports_what_it_removed(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        company_id = await _company_id(app)
        customer_id = uuid4()
        await client.post(
            "/api/v1/memory/facts",
            headers=owner_headers,
            json=_record_payload(
                company_id,
                tier="customer",
                fact_type="preferred_language",
                subject_type="customer",
                subject_id=str(customer_id),
                topic="prefers arabic",
                statement="Prefers Arabic.",
            ),
        )

        response = await client.delete(
            f"/api/v1/memory/subjects/customer/{customer_id}", headers=owner_headers
        )

        assert response.status_code == 200, response.text
        assert response.json()["facts_deleted"] == 1

        remaining = await client.get(
            f"/api/v1/memory/subjects/customer/{customer_id}/facts", headers=owner_headers
        )
        assert remaining.json() == []

    async def test_erasure_needs_its_own_permission(
        self, client: AsyncClient, app, registered_owner: dict
    ) -> None:
        """Not something an Admin has merely by being an Admin — the blast
        radius is different in kind from suppressing a fact, and this is
        the permission a regulator asks who holds."""
        from blinkengage.domain.rbac import DEFAULT_ROLE_PERMISSIONS, SystemRole

        assert "memory.erase" in DEFAULT_ROLE_PERMISSIONS[SystemRole.OWNER]
        assert "memory.erase" not in DEFAULT_ROLE_PERMISSIONS[SystemRole.ADMIN]
        assert "memory.erase" not in DEFAULT_ROLE_PERMISSIONS[SystemRole.AGENT]
        assert "memory.manage" in DEFAULT_ROLE_PERMISSIONS[SystemRole.ADMIN]
        assert "memory.read" in DEFAULT_ROLE_PERMISSIONS[SystemRole.AGENT]


class TestStatus:
    async def test_status_reports_holdings_and_retention(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        company_id = await _company_id(app)
        await client.post(
            "/api/v1/memory/facts", headers=owner_headers, json=_record_payload(company_id)
        )

        response = await client.get("/api/v1/memory/status", headers=owner_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["memory_enabled"] is True
        assert body["facts_by_tier"]["organizational"] == 1
        # The windows the sweep will actually apply, not the defaults the
        # platform ships — a status screen that disagreed with the sweep
        # would be worse than none.
        assert body["retention_dormant_after_days"] > 0
        assert (
            body["retention_dormant_after_days"]
            < body["retention_archive_after_days"]
            < body["retention_purge_after_days"]
        )


class TestConversationWorkingMemory:
    async def test_it_starts_empty_rather_than_missing(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        """An absent key is the ordinary state at turn one, so every caller
        would otherwise have to handle the common case as an exception."""
        conversation_id = uuid4()

        response = await client.get(
            f"/api/v1/memory/conversations/{conversation_id}", headers=owner_headers
        )

        assert response.status_code == 200
        assert response.json()["entities"] == []
        assert response.json()["turn_count"] == 0

    async def test_it_round_trips(self, client: AsyncClient, owner_headers: dict[str, str]) -> None:
        conversation_id = uuid4()

        await client.put(
            f"/api/v1/memory/conversations/{conversation_id}",
            headers=owner_headers,
            json={
                "entities": [{"kind": "order", "value": "4471", "turn": 3}],
                "open_questions": [
                    {"text": "When will it ship?", "asked_by": "customer", "turn": 4}
                ],
                "summary": "Customer asking about order 4471.",
            },
        )
        response = await client.get(
            f"/api/v1/memory/conversations/{conversation_id}", headers=owner_headers
        )

        body = response.json()
        assert body["entities"][0]["value"] == "4471"
        assert body["open_questions"][0]["text"] == "When will it ship?"
        assert body["summary"] == "Customer asking about order 4471."

    async def test_an_omitted_field_means_unchanged_not_cleared(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        """Building the new value from the submitted fields alone would
        silently wipe everything the caller did not mention."""
        conversation_id = uuid4()
        await client.put(
            f"/api/v1/memory/conversations/{conversation_id}",
            headers=owner_headers,
            json={
                "entities": [{"kind": "order", "value": "4471", "turn": 3}],
                "summary": "First summary.",
            },
        )

        await client.put(
            f"/api/v1/memory/conversations/{conversation_id}",
            headers=owner_headers,
            json={"summary": "Second summary."},
        )
        response = await client.get(
            f"/api/v1/memory/conversations/{conversation_id}", headers=owner_headers
        )

        body = response.json()
        assert body["summary"] == "Second summary."
        assert body["entities"][0]["value"] == "4471"

    async def test_it_can_be_cleared(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        conversation_id = uuid4()
        await client.put(
            f"/api/v1/memory/conversations/{conversation_id}",
            headers=owner_headers,
            json={"summary": "Something."},
        )

        cleared = await client.delete(
            f"/api/v1/memory/conversations/{conversation_id}", headers=owner_headers
        )
        assert cleared.status_code == 204

        response = await client.get(
            f"/api/v1/memory/conversations/{conversation_id}", headers=owner_headers
        )
        assert response.json()["summary"] is None

    async def test_working_memory_is_keyed_by_company(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        """Tenant isolation is in the key, not in a filter applied to the
        result — so a guessed conversation id cannot reach another
        company's value."""
        from blinkengage.application.services.conversation_memory_service import (
            ConversationMemoryService,
        )

        conversation_id = uuid4()
        await client.put(
            f"/api/v1/memory/conversations/{conversation_id}",
            headers=owner_headers,
            json={"summary": "Ours."},
        )

        service = ConversationMemoryService(app.state.container.redis())
        theirs = await service.get(company_id=uuid4(), conversation_id=conversation_id)

        assert theirs.summary is None

    async def test_it_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.get(f"/api/v1/memory/conversations/{uuid4()}")
        assert response.status_code == 403
