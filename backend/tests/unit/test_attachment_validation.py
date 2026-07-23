from blinkengage.application.services.attachment_validation import validate_attachment
from blinkengage.core.config import get_settings


def test_approves_an_allowed_content_type_within_size_limit() -> None:
    settings = get_settings()
    result = validate_attachment(content_type="image/png", size_bytes=1024, settings=settings)
    assert result.approved is True
    assert result.reason is None


def test_rejects_a_disallowed_content_type() -> None:
    settings = get_settings()
    result = validate_attachment(
        content_type="application/x-msdownload", size_bytes=1024, settings=settings
    )
    assert result.approved is False
    assert "not allowed" in (result.reason or "")


def test_rejects_an_oversized_file() -> None:
    settings = get_settings()
    result = validate_attachment(
        content_type="image/png",
        size_bytes=settings.attachment_max_size_bytes + 1,
        settings=settings,
    )
    assert result.approved is False
    assert "exceeds" in (result.reason or "")
