"""Structured knowledge over HTTP: the guarantees, not the CRUD.

The tests worth having here are the ones that fail *quietly* if the design
slips — a price that outlives its period, a second active record nobody
noticed, a company reading another company's price list, a draft answering
a customer. Ordinary create-and-read is covered incidentally by the
fixtures every other test builds on.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

BASE = "/api/v1/knowledge/records"

NOW = datetime(2026, 8, 1, tzinfo=UTC)
LATER = NOW + timedelta(days=30)


def price(amount: str = "180", currency: str = "JOD") -> dict[str, str]:
    return {"amount": amount, "currency": currency}


async def draft(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    label: str = "DIA 500 Mbps",
    attributes: dict[str, Any] | None = None,
    effective_from: datetime = NOW,
    effective_until: datetime | None = None,
    source: str | None = "Price List 2026",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "record_type": "PRICE",
        "subject_label": label,
        "attributes": attributes if attributes is not None else price(),
        "effective_from": effective_from.isoformat(),
        "source_reference": source,
    }
    if effective_until is not None:
        payload["effective_until"] = effective_until.isoformat()
    response = await client.post(BASE, json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def publish(client: AsyncClient, headers: dict[str, str], record_id: str) -> dict[str, Any]:
    response = await client.post(f"{BASE}/{record_id}/publish", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def active_price(
    client: AsyncClient, headers: dict[str, str], **kwargs: Any
) -> dict[str, Any]:
    record = await draft(client, headers, **kwargs)
    return await publish(client, headers, record["id"])


class TestSubjectKey:
    async def test_key_is_derived_not_accepted(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        # A caller cannot supply a key. If they could, two callers could
        # write two keys for one product and silently fork its history.
        record = await draft(client, owner_headers, label="  DIA/500  Mbps ")
        assert record["subject_key"] == "dia-500-mbps"
        # The label keeps the punctuation the key folds away: the key is
        # for lookup, the label is what a human reads, and rewriting
        # somebody's product name to match a lookup key would be the
        # display form answering to the index rather than the other way
        # round. Only surrounding whitespace is tidied.
        assert record["subject_label"] == "DIA/500 Mbps"

    async def test_spelling_variants_share_one_chain(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        first = await draft(client, owner_headers, label="DIA 500 Mbps")
        second = await draft(client, owner_headers, label="dia  500  mbps")
        assert first["subject_key"] == second["subject_key"]
        # Same subject, so the second is version 2 rather than a new
        # subject at version 1.
        assert second["version"] == first["version"] + 1


class TestResolution:
    async def test_resolves_the_active_record(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        await active_price(client, owner_headers)
        response = await client.get(
            f"{BASE}/resolve",
            params={"record_type": "PRICE", "subject_label": "DIA 500 Mbps"},
            headers=owner_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["record"]["attributes"]["amount"] == "180"

    async def test_a_draft_never_answers(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        # The one that matters most: an unapproved price must not be
        # quotable. A draft is somebody working, not a company statement.
        await draft(client, owner_headers)
        response = await client.get(
            f"{BASE}/resolve",
            params={"record_type": "PRICE", "subject_label": "DIA 500 Mbps"},
            headers=owner_headers,
        )
        assert response.json()["record"] is None

    async def test_expired_price_is_absent_not_stale(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        # Quoting last year's price is the failure this whole module
        # exists to prevent.
        await active_price(client, owner_headers, effective_from=NOW, effective_until=LATER)
        response = await client.get(
            f"{BASE}/resolve",
            params={
                "record_type": "PRICE",
                "subject_label": "DIA 500 Mbps",
                "at": (LATER + timedelta(days=1)).isoformat(),
            },
            headers=owner_headers,
        )
        assert response.json()["record"] is None

    async def test_absence_is_an_answer_not_an_error(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        # 200 with a null record, not 404. The caller must be able to say
        # "we do not know" rather than treating it as a failed lookup and
        # retrying differently.
        response = await client.get(
            f"{BASE}/resolve",
            params={"record_type": "PRICE", "subject_label": "Nothing We Sell"},
            headers=owner_headers,
        )
        assert response.status_code == 200
        assert response.json()["record"] is None

    async def test_resolution_is_point_in_time(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        # "What did we quote in July" is the same code path as the live
        # lookup, so the two cannot drift into different definitions of
        # active.
        first = await active_price(client, owner_headers, effective_from=NOW, effective_until=LATER)
        await client.post(
            f"{BASE}/{first['id']}/supersede",
            json={
                "attributes": price("200"),
                "effective_from": LATER.isoformat(),
                "source_reference": "Price List 2027",
            },
            headers=owner_headers,
        )
        response = await client.get(
            f"{BASE}/resolve",
            params={
                "record_type": "PRICE",
                "subject_label": "DIA 500 Mbps",
                "at": (NOW + timedelta(days=1)).isoformat(),
            },
            headers=owner_headers,
        )
        assert response.json()["record"]["attributes"]["amount"] == "180"

    async def test_a_scheduled_change_does_not_unprice_today(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        # The sharp edge behind RESOLVABLE_STATES. Superseding marks the
        # current record SUPERSEDED *immediately*, even when the
        # replacement starts next month — so resolving only ACTIVE would
        # answer "what does this cost today?" with nothing, for a month,
        # because somebody scheduled a price rise.
        first = await active_price(client, owner_headers, effective_from=NOW)
        await client.post(
            f"{BASE}/{first['id']}/supersede",
            json={
                "attributes": price("200"),
                "effective_from": LATER.isoformat(),
                "source_reference": "Price List 2027",
            },
            headers=owner_headers,
        )
        today = await client.get(
            f"{BASE}/resolve",
            params={
                "record_type": "PRICE",
                "subject_label": "DIA 500 Mbps",
                "at": (NOW + timedelta(days=1)).isoformat(),
            },
            headers=owner_headers,
        )
        assert today.json()["record"]["attributes"]["amount"] == "180"

        after = await client.get(
            f"{BASE}/resolve",
            params={
                "record_type": "PRICE",
                "subject_label": "DIA 500 Mbps",
                "at": (LATER + timedelta(days=1)).isoformat(),
            },
            headers=owner_headers,
        )
        assert after.json()["record"]["attributes"]["amount"] == "200"


class TestVersioning:
    async def test_supersede_closes_the_old_period_exactly(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        first = await active_price(client, owner_headers)
        response = await client.post(
            f"{BASE}/{first['id']}/supersede",
            json={
                "attributes": price("200"),
                "effective_from": LATER.isoformat(),
                "source_reference": "Price List 2027",
            },
            headers=owner_headers,
        )
        assert response.status_code == 200
        replacement = response.json()

        old = await client.get(f"{BASE}/{first['id']}", headers=owner_headers)
        old_body = old.json()
        assert old_body["lifecycle_state"] == "SUPERSEDED"
        assert old_body["superseded_by_id"] == replacement["id"]
        # The handover is exact: no instant where both are true, and none
        # where neither is.
        assert old_body["effective_until"] == replacement["effective_from"]
        assert replacement["supersedes_id"] == first["id"]
        assert replacement["version"] == first["version"] + 1

    async def test_superseded_record_is_retained(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        first = await active_price(client, owner_headers)
        await client.post(
            f"{BASE}/{first['id']}/supersede",
            json={
                "attributes": price("200"),
                "effective_from": LATER.isoformat(),
                "source_reference": "Price List 2027",
            },
            headers=owner_headers,
        )
        # Still readable. "We quoted 180 in August" must be answerable in
        # two years.
        assert (await client.get(f"{BASE}/{first['id']}", headers=owner_headers)).status_code == 200

    async def test_version_history_lists_every_state(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        first = await active_price(client, owner_headers)
        await client.post(
            f"{BASE}/{first['id']}/supersede",
            json={
                "attributes": price("200"),
                "effective_from": LATER.isoformat(),
                "source_reference": "Price List 2027",
            },
            headers=owner_headers,
        )
        response = await client.get(f"{BASE}/{first['id']}/versions", headers=owner_headers)
        assert response.status_code == 200
        states = [row["lifecycle_state"] for row in response.json()]
        assert states == ["ACTIVE", "SUPERSEDED"]

    async def test_superseded_record_cannot_be_superseded_again(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        first = await active_price(client, owner_headers)
        body = {
            "attributes": price("200"),
            "effective_from": LATER.isoformat(),
            "source_reference": "Price List 2027",
        }
        await client.post(f"{BASE}/{first['id']}/supersede", json=body, headers=owner_headers)
        again = await client.post(
            f"{BASE}/{first['id']}/supersede", json=body, headers=owner_headers
        )
        assert again.status_code == 400


class TestOverlap:
    async def test_two_active_records_cannot_share_an_instant(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        # The contradiction the design exists to prevent. Blocked at
        # publish rather than discovered at resolve.
        await active_price(client, owner_headers, effective_from=NOW)
        second = await draft(client, owner_headers, effective_from=NOW + timedelta(days=1))
        response = await client.post(f"{BASE}/{second['id']}/publish", headers=owner_headers)
        assert response.status_code == 400
        assert "supersede" in response.text.lower()

    async def test_adjacent_periods_are_allowed(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        # Half-open periods: one ends exactly where the next begins, and
        # that is not an overlap.
        await active_price(client, owner_headers, effective_from=NOW, effective_until=LATER)
        second = await draft(client, owner_headers, effective_from=LATER)
        response = await client.post(f"{BASE}/{second['id']}/publish", headers=owner_headers)
        assert response.status_code == 200

    async def test_different_subjects_do_not_collide(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        await active_price(client, owner_headers, label="DIA 500 Mbps")
        second = await draft(client, owner_headers, label="DIA 200 Mbps")
        response = await client.post(f"{BASE}/{second['id']}/publish", headers=owner_headers)
        assert response.status_code == 200


class TestProvenance:
    async def test_publishing_without_a_source_is_refused(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        # An approved price whose origin nobody recorded is a number the
        # platform cannot defend in the audit it exists for.
        record = await draft(client, owner_headers, source=None)
        response = await client.post(f"{BASE}/{record['id']}/publish", headers=owner_headers)
        assert response.status_code == 400
        assert "provenance" in response.text.lower() or "source" in response.text.lower()

    async def test_drafting_without_a_source_is_allowed(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        # Demanding provenance before somebody has finished would push
        # them toward inventing one.
        record = await draft(client, owner_headers, source=None)
        assert record["lifecycle_state"] == "DRAFT"

    async def test_publish_records_who_approved_it(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        record = await active_price(client, owner_headers)
        assert record["approved_by_user_id"] is not None
        assert record["approved_at"] is not None
        assert record["created_from"] == "agent"


class TestArchive:
    async def test_archive_retains_the_row(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        record = await active_price(client, owner_headers)
        response = await client.post(f"{BASE}/{record['id']}/archive", headers=owner_headers)
        assert response.status_code == 200
        assert response.json()["lifecycle_state"] == "ARCHIVED"
        assert response.json()["archived_at"] is not None
        assert (
            await client.get(f"{BASE}/{record['id']}", headers=owner_headers)
        ).status_code == 200

    async def test_archived_record_stops_answering(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        record = await active_price(client, owner_headers)
        await client.post(f"{BASE}/{record['id']}/archive", headers=owner_headers)
        response = await client.get(
            f"{BASE}/resolve",
            params={"record_type": "PRICE", "subject_label": "DIA 500 Mbps"},
            headers=owner_headers,
        )
        assert response.json()["record"] is None

    async def test_there_is_no_delete_route(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        # Structural, not incidental. A price that was quoted must be
        # reproducible in an audit two years later.
        record = await active_price(client, owner_headers)
        response = await client.delete(f"{BASE}/{record['id']}", headers=owner_headers)
        assert response.status_code == 405


class TestTenantIsolation:
    async def test_one_company_cannot_read_another_companys_price(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        record = await active_price(client, owner_headers)

        other = await client.post(
            "/api/v1/auth/register",
            json={
                "company_name": "Rival Ltd",
                "owner_full_name": "Bob Rival",
                "owner_email": "bob@rival.example",
                "owner_password": "correct-horse-battery-9",
            },
        )
        assert other.status_code == 201
        rival_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

        # Not 403 — 404. The rival must not learn that the id exists.
        assert (
            await client.get(f"{BASE}/{record['id']}", headers=rival_headers)
        ).status_code == 404

    async def test_resolution_does_not_cross_companies(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        await active_price(client, owner_headers)

        other = await client.post(
            "/api/v1/auth/register",
            json={
                "company_name": "Rival Ltd",
                "owner_full_name": "Bob Rival",
                "owner_email": "bob2@rival.example",
                "owner_password": "correct-horse-battery-9",
            },
        )
        rival_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
        response = await client.get(
            f"{BASE}/resolve",
            params={"record_type": "PRICE", "subject_label": "DIA 500 Mbps"},
            headers=rival_headers,
        )
        # The same subject key exists in the other tenant. Resolution must
        # still find nothing.
        assert response.json()["record"] is None

    async def test_listing_is_scoped(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        await active_price(client, owner_headers)
        other = await client.post(
            "/api/v1/auth/register",
            json={
                "company_name": "Rival Ltd",
                "owner_full_name": "Bob Rival",
                "owner_email": "bob3@rival.example",
                "owner_password": "correct-horse-battery-9",
            },
        )
        rival_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
        response = await client.get(BASE, headers=rival_headers)
        assert response.json() == []

    async def test_cross_tenant_mutation_is_refused(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        record = await draft(client, owner_headers)
        other = await client.post(
            "/api/v1/auth/register",
            json={
                "company_name": "Rival Ltd",
                "owner_full_name": "Bob Rival",
                "owner_email": "bob4@rival.example",
                "owner_password": "correct-horse-battery-9",
            },
        )
        rival_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
        response = await client.post(f"{BASE}/{record['id']}/publish", headers=rival_headers)
        assert response.status_code == 404


class TestAuthorization:
    # 401 throughout, because every request in this class carries no
    # credentials at all. These asserted 403 until FastAPI 0.141, whose
    # ``HTTPBearer`` raises 401 for an absent Authorization header rather
    # than 403.
    #
    # The distinction is now the one RFC 9110 draws and is worth keeping
    # straight when reading the rest of the suite: 401 means "you sent no
    # credentials", 403 means "you sent credentials and they are not
    # enough". A tenant reaching a platform route still gets 403 — see
    # test_revenue_dashboard.py, which asserts both against the same
    # endpoint.
    async def test_anonymous_is_refused(self, client: AsyncClient) -> None:
        assert (await client.get(BASE)).status_code == 401

    @pytest.mark.parametrize(
        "suffix",
        ["", "/{id}/publish", "/{id}/supersede", "/{id}/archive"],
    )
    async def test_mutations_require_authentication(self, client: AsyncClient, suffix: str) -> None:
        path = BASE + suffix.replace("{id}", "00000000-0000-0000-0000-000000000000")
        assert (await client.post(path, json={})).status_code == 401

    async def test_reads_require_authentication(self, client: AsyncClient) -> None:
        assert (
            await client.get(
                f"{BASE}/resolve",
                params={"record_type": "PRICE", "subject_label": "DIA 500 Mbps"},
            )
        ).status_code == 401


class TestValidation:
    async def test_unknown_attribute_is_refused(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            BASE,
            json={
                "record_type": "PRICE",
                "subject_label": "DIA 500 Mbps",
                "attributes": {"amount": "180", "currency": "JOD", "discount": "10"},
                "effective_from": NOW.isoformat(),
            },
            headers=owner_headers,
        )
        assert response.status_code == 400

    async def test_price_without_currency_is_refused(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            BASE,
            json={
                "record_type": "PRICE",
                "subject_label": "DIA 500 Mbps",
                "attributes": {"amount": "180"},
                "effective_from": NOW.isoformat(),
            },
            headers=owner_headers,
        )
        assert response.status_code == 400

    async def test_effective_until_before_from_is_refused(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            BASE,
            json={
                "record_type": "PRICE",
                "subject_label": "DIA 500 Mbps",
                "attributes": price(),
                "effective_from": LATER.isoformat(),
                "effective_until": NOW.isoformat(),
            },
            headers=owner_headers,
        )
        assert response.status_code == 400
