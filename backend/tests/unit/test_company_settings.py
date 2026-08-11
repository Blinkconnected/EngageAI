from blinkengage.domain.company_settings import (
    DEFAULT_AUTOPILOT_CONFIDENCE_THRESHOLD,
    DEFAULT_MIN_PASSWORD_LENGTH,
    MAX_BUSINESS_PROFILE_FIELD_CHARS,
    autopilot_confidence_threshold,
    business_profile,
    format_business_profile,
    is_ai_enabled,
    is_autopilot_enabled,
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
    assert is_autopilot_enabled(settings) is False
    assert autopilot_confidence_threshold(settings) == DEFAULT_AUTOPILOT_CONFIDENCE_THRESHOLD
    assert is_notification_type_enabled(settings, "conversation.sla_breached") is True
    assert is_typing_indicator_enabled(settings) is True
    assert min_password_length(settings) == DEFAULT_MIN_PASSWORD_LENGTH


def test_reads_explicit_values() -> None:
    settings = {
        "onboarding": {"completed": True},
        "erp": {"enabled": True},
        "ai": {"enabled": False, "autopilot": {"enabled": True, "confidence_threshold": 0.9}},
        "notifications": {"conversation.sla_breached": False},
        "messaging": {"typing_indicator_enabled": False},
        "security": {"min_password_length": 14},
    }
    assert is_onboarding_completed(settings) is True
    assert is_erp_enabled(settings) is True
    assert is_ai_enabled(settings) is False
    assert is_autopilot_enabled(settings) is True
    assert autopilot_confidence_threshold(settings) == 0.9
    assert is_notification_type_enabled(settings, "conversation.sla_breached") is False
    assert is_notification_type_enabled(settings, "message.persisted") is True
    assert is_typing_indicator_enabled(settings) is False
    assert min_password_length(settings) == 14


def test_autopilot_confidence_threshold_ignores_an_out_of_range_value() -> None:
    settings = {"ai": {"autopilot": {"confidence_threshold": 1.5}}}
    assert autopilot_confidence_threshold(settings) == DEFAULT_AUTOPILOT_CONFIDENCE_THRESHOLD


def test_autopilot_confidence_threshold_ignores_a_non_numeric_value() -> None:
    settings = {"ai": {"autopilot": {"confidence_threshold": "high"}}}
    assert autopilot_confidence_threshold(settings) == DEFAULT_AUTOPILOT_CONFIDENCE_THRESHOLD


def test_autopilot_section_treats_a_null_autopilot_key_the_same_as_absent() -> None:
    settings = {"ai": {"enabled": True, "autopilot": None}}
    assert is_autopilot_enabled(settings) is False
    assert autopilot_confidence_threshold(settings) == DEFAULT_AUTOPILOT_CONFIDENCE_THRESHOLD


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
    assert is_autopilot_enabled(settings) is False
    assert autopilot_confidence_threshold(settings) == DEFAULT_AUTOPILOT_CONFIDENCE_THRESHOLD
    assert is_notification_type_enabled(settings, "conversation.sla_breached") is True
    assert is_typing_indicator_enabled(settings) is True
    assert min_password_length(settings) == DEFAULT_MIN_PASSWORD_LENGTH


def test_business_profile_is_empty_when_nothing_is_configured() -> None:
    assert business_profile({}) == {}
    assert format_business_profile({}) is None


def test_business_profile_reads_configured_facts_in_a_fixed_order() -> None:
    settings = {
        "business_profile": {
            "location": "Amman, Jordan",
            "legal_name": "Blink Connected",
        }
    }
    assert business_profile(settings) == {
        "legal_name": "Blink Connected",
        "location": "Amman, Jordan",
    }
    # Order follows BUSINESS_PROFILE_FIELDS, not insertion order — the
    # prompt should read the same way for every company.
    assert format_business_profile(settings) == (
        "Company name: Blink Connected\nLocation: Amman, Jordan"
    )


def test_hours_come_from_the_structured_schedule_not_a_second_free_text_field() -> None:
    """One source of truth. A free-text hours field beside the weekly
    schedule would let the AI quote one while the SLA engine honours the
    other."""
    settings = {
        "timezone": "Asia/Amman",
        "business_profile": {"legal_name": "Blink Connected"},
        "business_hours": {
            "enabled": True,
            "schedule": {
                "sunday": {"open": "09:00", "close": "17:00"},
                "friday": {"closed": True},
            },
        },
    }
    assert format_business_profile(settings) == (
        "Company name: Blink Connected\n"
        "Business hours (Asia/Amman): Friday: closed; Sunday: 09:00-17:00"
    )


def test_unconfigured_hours_are_stated_as_nothing_rather_than_the_schema_default() -> None:
    """The reported bug, in one assertion.

    ``resolve_schedule`` fills unconfigured days with 09:00-17:00 so an
    SLA clock always has something to calculate against. Reusing it here
    would have the AI announce a full Monday-Friday 9-to-5 week to a
    company that never configured hours — which is verbatim the invented
    "9 صباحًا حتى 5 مساءً" this feature exists to prevent.
    """
    # Enabled, but no day was ever filled in.
    assert format_business_profile({"business_hours": {"enabled": True, "schedule": {}}}) is None
    # A configured schedule that is switched off is not a statement of hours.
    assert (
        format_business_profile(
            {
                "business_hours": {
                    "enabled": False,
                    "schedule": {"monday": {"open": "09:00", "close": "17:00"}},
                }
            }
        )
        is None
    )
    # A day the administrator never named stays unnamed, rather than
    # appearing as open 9-to-5 by default.
    assert (
        format_business_profile(
            {
                "business_hours": {
                    "enabled": True,
                    "schedule": {"monday": {"open": "08:00", "close": "14:00"}},
                }
            }
        )
        == "Business hours: Monday: 08:00-14:00"
    )


def test_blank_and_non_string_fields_are_dropped_rather_than_emitted_empty() -> None:
    """A field the administrator never filled in must be *absent* from
    the prompt, not present and empty. ``Business hours:`` with nothing
    after it is an invitation for the model to complete the line — which
    is the invented "9am to 5pm" this whole feature exists to prevent."""
    settings = {
        "business_profile": {
            "legal_name": "Blink Connected",
            "location": "   ",
            "business_hours": None,
            "contact": 12345,
        }
    }
    assert business_profile(settings) == {"legal_name": "Blink Connected"}
    assert format_business_profile(settings) == "Company name: Blink Connected"


def test_an_overlong_field_is_truncated_rather_than_pasted_whole() -> None:
    settings = {"business_profile": {"about": "x" * (MAX_BUSINESS_PROFILE_FIELD_CHARS + 500)}}
    assert len(business_profile(settings)["about"]) == MAX_BUSINESS_PROFILE_FIELD_CHARS


def test_a_corrupted_business_profile_section_reads_as_absent() -> None:
    for corrupt in ("not a dict", [], 42, None):
        assert business_profile({"business_profile": corrupt}) == {}
        assert format_business_profile({"business_profile": corrupt}) is None
