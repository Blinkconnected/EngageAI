from blinkengage.domain.company_settings import (
    DEFAULT_MIN_PASSWORD_LENGTH,
    is_ai_enabled,
    is_erp_enabled,
    is_notification_type_enabled,
    is_onboarding_completed,
    is_typing_indicator_enabled,
    min_password_length,
)


def test_defaults_when_settings_is_empty() -> None:
    settings: dict = {}
    assert is_onboarding_completed(settings) is False
    assert is_erp_enabled(settings) is False
    assert is_ai_enabled(settings) is True
    assert is_notification_type_enabled(settings, "conversation.sla_breached") is True
    assert is_typing_indicator_enabled(settings) is True
    assert min_password_length(settings) == DEFAULT_MIN_PASSWORD_LENGTH


def test_reads_explicit_values() -> None:
    settings = {
        "onboarding": {"completed": True},
        "erp": {"enabled": True},
        "ai": {"enabled": False},
        "notifications": {"conversation.sla_breached": False},
        "messaging": {"typing_indicator_enabled": False},
        "security": {"min_password_length": 14},
    }
    assert is_onboarding_completed(settings) is True
    assert is_erp_enabled(settings) is True
    assert is_ai_enabled(settings) is False
    assert is_notification_type_enabled(settings, "conversation.sla_breached") is False
    assert is_notification_type_enabled(settings, "message.persisted") is True
    assert is_typing_indicator_enabled(settings) is False
    assert min_password_length(settings) == 14


def test_min_password_length_ignores_a_value_below_the_platform_floor() -> None:
    # The floor is enforced by validate_password_strength independent of
    # this setting; a stored value below it (e.g. from a bug or a direct
    # DB edit) must never make policy *weaker* than the platform default.
    settings = {"security": {"min_password_length": 4}}
    assert min_password_length(settings) == DEFAULT_MIN_PASSWORD_LENGTH


def test_min_password_length_ignores_a_non_int_value() -> None:
    settings = {"security": {"min_password_length": "not-a-number"}}
    assert min_password_length(settings) == DEFAULT_MIN_PASSWORD_LENGTH


def test_every_reader_treats_an_explicit_null_section_the_same_as_absent() -> None:
    # PATCH /company accepts an explicit JSON null for any section
    # (Pydantic's exclude_unset treats it as "provided"), which persists
    # a literal None under that key rather than omitting it. Every reader
    # must degrade to its normal default instead of raising AttributeError
    # on the next `.get(...)` call against that None.
    settings = {
        "onboarding": None,
        "erp": None,
        "ai": None,
        "notifications": None,
        "messaging": None,
        "security": None,
    }
    assert is_onboarding_completed(settings) is False
    assert is_erp_enabled(settings) is False
    assert is_ai_enabled(settings) is True
    assert is_notification_type_enabled(settings, "conversation.sla_breached") is True
    assert is_typing_indicator_enabled(settings) is True
    assert min_password_length(settings) == DEFAULT_MIN_PASSWORD_LENGTH
