"""The upload allow-list, against what the console can actually show.

Two separate concerns that have to agree: the allow-list is *security
policy* (what may enter the system) and ``domain/media.py`` is
*presentation* (what a browser can render). Deriving one from the other
would mean adding a playable format silently widened what can be uploaded,
so they are declared independently — and this checks they have not drifted.

Drift in either direction is a real defect. An allowed type the console
cannot render shows a broken player; a renderable type that is not allowed
is silently discarded on the way in, which is how customer voice notes went
missing.
"""

from blinkengage.core.config import Settings
from blinkengage.domain.media import MediaKind, is_inline_renderable, kind_for


def _allowed() -> list[str]:
    return Settings(
        jwt_secret_key="a" * 40,
        credentials_encryption_key="b" * 40,
        database_url="sqlite+aiosqlite:///:memory:",
    ).attachment_allowed_content_types


def test_every_allowed_audio_or_video_type_can_actually_be_played() -> None:
    """An allowed type the console cannot render is a broken player in a
    conversation."""
    unplayable = [
        content_type
        for content_type in _allowed()
        if content_type.startswith(("audio/", "video/")) and not is_inline_renderable(content_type)
    ]
    assert unplayable == []


def test_voice_notes_are_accepted() -> None:
    """The specific regression: WhatsApp voice notes were rejected by the
    ingest consumer, so an agent never saw the message at all."""
    allowed = _allowed()
    assert "audio/ogg" in allowed
    assert kind_for("audio/ogg; codecs=opus") is MediaKind.AUDIO


def test_iphone_video_is_accepted() -> None:
    assert "video/quicktime" in _allowed()


def test_svg_is_still_not_accepted() -> None:
    """An SVG is an image by MIME type and an executable document in
    practice. It must not become uploadable just because the media work
    touched this list."""
    assert "image/svg+xml" not in _allowed()


def test_the_list_has_no_duplicates() -> None:
    allowed = _allowed()
    assert len(allowed) == len(set(allowed))
