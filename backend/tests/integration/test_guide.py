"""The product guide, served to the application.

The guide exists as a Markdown file in the repository. Serving that same
file — rather than re-typing it into the frontend — is the point: a copy
drifts, and the copy that drifts is the one customers read.

Two properties matter. It must require a session, because the guide
describes screens, permissions and configuration in detail and that is
reconnaissance for anybody who is not a customer. And an unavailable
translation must fall back to English rather than fail, because somebody
who opened help has a question now.
"""

from pathlib import Path

import pytest


@pytest.fixture
def guides(tmp_path: Path, app) -> Path:
    english = tmp_path / "guide.md"
    english.write_text("# Inbox\n\nEnglish guide.\n", encoding="utf-8")
    settings = app.state.container.settings()
    settings.guide_path = str(english)
    settings.guide_path_ar = str(tmp_path / "guide.ar.md")
    return tmp_path


class TestAccess:
    async def test_requires_a_session(self, client, guides) -> None:
        response = await client.get("/api/v1/guide")

        assert response.status_code in (401, 403)

    async def test_a_signed_in_user_can_read_it(self, client, owner_headers, guides) -> None:
        response = await client.get("/api/v1/guide", headers=owner_headers)

        assert response.status_code == 200
        assert response.json()["content"].startswith("# Inbox")

    async def test_no_permission_is_required(self, client, owner_headers, guides) -> None:
        # Help gated behind a role is help the person who needs it most
        # cannot reach. Anybody who can sign in can be stuck.
        assert (await client.get("/api/v1/guide", headers=owner_headers)).status_code == 200


class TestLanguage:
    async def test_arabic_is_served_when_it_exists(self, client, owner_headers, guides) -> None:
        (guides / "guide.ar.md").write_text("# صندوق الوارد\n\nدليل عربي.\n", encoding="utf-8")

        body = (
            await client.get("/api/v1/guide", params={"lang": "ar"}, headers=owner_headers)
        ).json()

        assert body["language"] == "ar"
        assert body["fell_back"] is False
        assert "دليل عربي" in body["content"]

    async def test_a_missing_translation_falls_back_to_english_and_says_so(
        self, client, owner_headers, guides
    ) -> None:
        """The flag is the point.

        Serving English silently would leave an Arabic reader unable to
        tell a missing translation from a broken page.
        """
        body = (
            await client.get("/api/v1/guide", params={"lang": "ar"}, headers=owner_headers)
        ).json()

        assert body["language"] == "en"
        assert body["fell_back"] is True
        assert body["content"].startswith("# Inbox")

    async def test_english_is_not_reported_as_a_fallback(
        self, client, owner_headers, guides
    ) -> None:
        body = (await client.get("/api/v1/guide", headers=owner_headers)).json()

        assert body["fell_back"] is False

    async def test_an_unsupported_language_is_rejected(self, client, owner_headers, guides) -> None:
        response = await client.get("/api/v1/guide", params={"lang": "fr"}, headers=owner_headers)

        assert response.status_code == 422


class TestMissingFile:
    async def test_an_unreadable_guide_is_a_deployment_fault(
        self, client, owner_headers, guides, app
    ) -> None:
        # 503 rather than 404: the client asked for the right thing and
        # the file is simply not mounted, which is an operator problem.
        app.state.container.settings().guide_path = str(guides / "absent.md")

        response = await client.get("/api/v1/guide", headers=owner_headers)

        assert response.status_code == 503
