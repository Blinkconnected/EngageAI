"""Resolving the mail relay's configuration.

The rules that matter are all about *absence*: what a missing key, a
None password and an empty string each mean. Getting them wrong silently
erases a working credential, which is the kind of bug that only shows up
as "customers stopped receiving email".
"""

from blinkengage.domain.mail import MailConfig, MailSecurity, from_stored

DEFAULTS = MailConfig(
    host="mail.internal",
    port=25,
    security=MailSecurity.NONE,
    from_address="notifications@example.test",
    from_name="Example",
    username="env-user",
    password="env-password",
)


class TestResolution:
    def test_no_stored_configuration_uses_the_environment(self) -> None:
        """An installation that has never opened the console keeps
        working exactly as it did before this feature existed."""
        assert from_stored(None, defaults=DEFAULTS) == DEFAULTS
        assert from_stored({}, defaults=DEFAULTS) == DEFAULTS

    def test_stored_values_override(self) -> None:
        resolved = from_stored(
            {"host": "smtp.provider.test", "port": 587, "security": "starttls"},
            defaults=DEFAULTS,
        )
        assert resolved.host == "smtp.provider.test"
        assert resolved.port == 587
        assert resolved.security is MailSecurity.STARTTLS

    def test_absent_keys_fall_through_rather_than_blanking(self) -> None:
        """A row written before a field existed must not erase it."""
        resolved = from_stored({"host": "smtp.provider.test"}, defaults=DEFAULTS)
        assert resolved.from_name == DEFAULTS.from_name
        assert resolved.username == DEFAULTS.username

    def test_a_null_password_means_unchanged(self) -> None:
        """The API never sends the password back, so a naive round-trip
        of the form would otherwise erase it."""
        resolved = from_stored({"password": None}, defaults=DEFAULTS)
        assert resolved.password == "env-password"

    def test_an_empty_password_clears_it(self) -> None:
        """Unambiguous, unlike omitting the key."""
        assert from_stored({"password": ""}, defaults=DEFAULTS).password is None

    def test_an_unknown_security_mode_falls_back(self) -> None:
        """Rather than raising on read. A settings row that cannot be
        loaded takes outbound mail down entirely; falling back to the
        environment keeps it sending."""
        assert from_stored({"security": "quantum"}, defaults=DEFAULTS).security is (
            DEFAULTS.security
        )


class TestRedaction:
    def test_redacted_drops_the_password_and_nothing_else(self) -> None:
        redacted = DEFAULTS.redacted()
        assert redacted.password is None
        assert redacted.username == DEFAULTS.username
        assert redacted.host == DEFAULTS.host
