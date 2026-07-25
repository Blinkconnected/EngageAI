from blinkengage.domain.notification_types import (
    NOTIFICATION_TYPES,
    NotificationChannel,
    is_known_notification_type,
)


def test_notification_type_codes_are_unique() -> None:
    codes = [t.code for t in NOTIFICATION_TYPES]
    assert len(codes) == len(set(codes))


def test_is_known_notification_type() -> None:
    assert is_known_notification_type("conversation.assignment_changed")
    assert not is_known_notification_type("not.a.real.type")


def test_every_notification_channel_is_a_plain_lowercase_string() -> None:
    for channel in NotificationChannel:
        assert channel.value == channel.value.lower()
