"""Release notes in Arabic, with English as the spine.

Translation is additive and never authoritative. The English changelog
decides which releases exist and in what order; a translation may only
replace the prose of a release already there.

That asymmetry is the whole design. A translated file that falls behind,
or that somebody edits carelessly, must degrade to English rather than
misrepresent the release history — and the running version must never be
readable from it at all, because a mistranslated heading would then
change what the platform reports itself to be.
"""

import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

EN = """\
# Changelog

## [2.0.0] - 2026-01-02

English summary.

### Added

- English feature.

## [1.0.0] - 2026-01-01

### Added

- English original.
"""

AR = """\
# سجل التغييرات

## [2.0.0] - 2026-01-02

ملخص عربي.

### Added

- ميزة بالعربية.
"""


@pytest.fixture
def changelogs(tmp_path: Path, app) -> Iterator[Path]:
    """An English changelog with two releases; Arabic translates only one.

    Restores both paths afterwards. ``Settings`` is built once per
    application and shared by every test in the session, so leaving
    these pointed at a ``tmp_path`` pytest then deletes breaks every
    later test that reads the changelog — including ``/version``, which
    would start reporting the wrong build. The failure lands in an
    unrelated file, which is the most expensive kind to diagnose.
    """
    en = tmp_path / "CHANGELOG.md"
    en.write_text(EN, encoding="utf-8")
    ar = tmp_path / "CHANGELOG.ar.md"
    ar.write_text(AR, encoding="utf-8")

    settings = app.state.container.settings()
    original = (settings.changelog_path, settings.changelog_path_ar)
    settings.changelog_path = str(en)
    settings.changelog_path_ar = str(ar)
    try:
        yield tmp_path
    finally:
        settings.changelog_path, settings.changelog_path_ar = original


class TestLanguageSelection:
    async def test_defaults_to_english(self, client, changelogs) -> None:
        response = await client.get("/api/v1/releases")

        assert response.status_code == 200
        assert response.json()[0]["summary"].startswith("English")

    async def test_arabic_replaces_the_prose_of_a_translated_release(
        self, client, changelogs
    ) -> None:
        response = await client.get("/api/v1/releases", params={"lang": "ar"})

        assert response.status_code == 200
        assert response.json()[0]["summary"].startswith("ملخص")

    async def test_an_untranslated_release_falls_back_to_english(self, client, changelogs) -> None:
        """The reason this is a fallback and not an omission.

        `1.0.0` exists only in English. Dropping it would make the Arabic
        history shorter than the real one — a reader would conclude the
        release never happened.
        """
        releases = (await client.get("/api/v1/releases", params={"lang": "ar"})).json()

        versions = [release["version"] for release in releases]
        assert versions == ["2.0.0", "1.0.0"]
        assert releases[1]["added"] == ["English original."]

    async def test_an_unsupported_language_is_rejected(self, client, changelogs) -> None:
        # Rather than silently serving English: a client asking for a
        # language we do not have has a bug worth surfacing.
        response = await client.get("/api/v1/releases", params={"lang": "fr"})

        assert response.status_code == 422


class TestTranslationCannotDistortHistory:
    async def test_a_missing_translation_file_serves_english(self, client, changelogs, app) -> None:
        app.state.container.settings().changelog_path_ar = str(changelogs / "absent.md")

        response = await client.get("/api/v1/releases", params={"lang": "ar"})

        assert response.status_code == 200
        assert [r["version"] for r in response.json()] == ["2.0.0", "1.0.0"]

    async def test_a_malformed_translation_serves_english(self, client, changelogs, app) -> None:
        """A broken translation must not take the endpoint down.

        Release notes are the wrong thing to fail a request over, and the
        English text is right there.
        """
        broken = changelogs / "broken.ar.md"
        broken.write_text("## [2.0.0] - 2026-01-02\n\n### Nonsense\n\nnot a bullet\n")
        app.state.container.settings().changelog_path_ar = str(broken)

        response = await client.get("/api/v1/releases", params={"lang": "ar"})

        assert response.status_code == 200
        assert response.json()[0]["summary"].startswith("English")

    async def test_a_translation_cannot_add_a_release(self, client, changelogs, app) -> None:
        """The spine is English.

        An extra heading in the translated file is ignored rather than
        appended — otherwise a translator could invent a release.
        """
        extra = changelogs / "extra.ar.md"
        extra.write_text(
            textwrap.dedent("""\
                ## [9.9.9] - 2026-12-31

                ### Added

                - إصدار غير موجود.
                """)
        )
        app.state.container.settings().changelog_path_ar = str(extra)

        releases = (await client.get("/api/v1/releases", params={"lang": "ar"})).json()

        assert [r["version"] for r in releases] == ["2.0.0", "1.0.0"]

    async def test_the_running_version_is_never_read_from_the_translation(
        self, client, changelogs, app
    ) -> None:
        """`/version` has no language at all.

        It identifies the running build for status pages and support
        tooling. Sourcing any part of that from a translated file would
        let a mistranslated heading change what the platform reports
        itself to be.
        """
        wrong = changelogs / "wrong-version.ar.md"
        wrong.write_text("## [7.7.7] - 2026-06-06\n\n### Added\n\n- خطأ.\n")
        app.state.container.settings().changelog_path_ar = str(wrong)

        response = await client.get("/api/v1/version")

        assert response.status_code == 200
        assert response.json()["version"] == "2.0.0"
