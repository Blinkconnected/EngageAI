"""A production deployment must refuse to start on development defaults.

Every default in `config.py` is chosen so a laptop works with no
configuration. That is right for a laptop and wrong for anything holding
customer data, and until now nothing noticed the difference: a
production deployment inheriting `DEBUG=true` or MinIO's published
`minioadmin` credentials came up green, served traffic, and reported
healthy.

Each test below names the specific bad outcome, because a validator
without one is a rule somebody will delete the next time it is
inconvenient.
"""

import pytest
from pydantic import ValidationError

from blinkengage.core.config import Settings

#: Distinct, high-variety, placeholder-free — a plausible generated
#: secret rather than something that trips the checks under test.
GOOD_JWT = "Ky7pQz3XwR9tLmN4vB6hJ2cF8dS5aG1e"
GOOD_ENCRYPTION = "Zt4mW8xQ2rN6yB3vK9pL5cH7dJ1gS0fA"


def build(**overrides: object) -> Settings:
    """A minimal production configuration that passes, plus overrides."""
    base: dict[str, object] = {
        "environment": "production",
        "debug": False,
        "database_url": "postgresql+asyncpg://user:pw@db/blinkengage",
        "jwt_secret_key": GOOD_JWT,
        "credentials_encryption_key": GOOD_ENCRYPTION,
        "s3_access_key": "blinkengage",
        "s3_secret_key": "a-real-object-storage-secret",
        "cors_allow_origins": ["https://engage.example.com"],
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def message_of(caught: pytest.ExceptionInfo[ValidationError]) -> str:
    return str(caught.value)


class TestASafeProductionConfigurationStarts:
    def test_the_baseline_is_accepted(self) -> None:
        """Guards the guard. A validator that rejects everything is
        indistinguishable from a broken import, and would be 'fixed' by
        deleting it."""
        settings = build()

        assert settings.is_production

    def test_development_keeps_every_convenience_default(self) -> None:
        """The point is to stop a dangerous combination, not to make the
        stack tedious to run. A laptop still needs zero configuration."""
        settings = Settings(  # type: ignore[call-arg]
            environment="development",
            debug=True,
            database_url="sqlite+aiosqlite:///:memory:",
            jwt_secret_key="x" * 32,
            credentials_encryption_key="x" * 32,
        )

        assert settings.debug
        assert settings.s3_secret_key == "minioadmin"

    @pytest.mark.parametrize("environment", ["development", "test", "staging"])
    def test_only_production_is_policed(self, environment: str) -> None:
        settings = Settings(  # type: ignore[call-arg]
            environment=environment,
            debug=True,
            database_url="sqlite+aiosqlite:///:memory:",
            jwt_secret_key="x" * 32,
            credentials_encryption_key="x" * 32,
        )

        assert not settings.is_production


class TestUnsafeProductionIsRefused:
    def test_debug_is_refused(self) -> None:
        # Tracebacks and configuration exposed to whoever triggers a 500.
        with pytest.raises(ValidationError) as caught:
            build(debug=True)

        assert "DEBUG=true" in message_of(caught)

    @pytest.mark.parametrize("field", ["s3_access_key", "s3_secret_key"])
    def test_minio_published_defaults_are_refused(self, field: str) -> None:
        """`minioadmin` is in MinIO's own quickstart. Anyone who has read
        it can reach every customer attachment."""
        with pytest.raises(ValidationError) as caught:
            build(**{field: "minioadmin"})

        assert "minioadmin" in message_of(caught)

    def test_a_secret_of_one_repeated_character_is_refused(self) -> None:
        """`Field(min_length=32)` is satisfied by 32 identical characters.
        Length is not entropy."""
        with pytest.raises(ValidationError) as caught:
            build(jwt_secret_key="x" * 32)

        assert "variety" in message_of(caught)

    def test_placeholder_text_in_a_secret_is_refused(self) -> None:
        with pytest.raises(ValidationError) as caught:
            build(credentials_encryption_key="change-me-please-and-pad-this-out")

        assert "placeholder" in message_of(caught)

    def test_reusing_one_secret_for_both_is_refused(self) -> None:
        """They are separate settings so rotating one does not invalidate
        the other. Sharing a value removes that silently."""
        with pytest.raises(ValidationError) as caught:
            build(jwt_secret_key=GOOD_JWT, credentials_encryption_key=GOOD_JWT)

        assert "identical" in message_of(caught)

    def test_wildcard_cors_is_refused(self) -> None:
        with pytest.raises(ValidationError) as caught:
            build(cors_allow_origins=["*"])

        assert "CORS_ALLOW_ORIGINS" in message_of(caught)

    def test_an_unedited_localhost_origin_is_refused(self) -> None:
        # Not a threat by itself — evidence the list was copied from the
        # example and never read.
        with pytest.raises(ValidationError) as caught:
            build(cors_allow_origins=["https://engage.example.com", "http://localhost:5173"])

        assert "localhost" in message_of(caught)

    def test_statement_echo_is_refused(self) -> None:
        # Every statement and its bound values, into the logs.
        with pytest.raises(ValidationError) as caught:
            build(database_echo=True)

        assert "DATABASE_ECHO" in message_of(caught)


class TestTheRefusalIsUsable:
    def test_every_problem_is_reported_at_once(self) -> None:
        """Not one per restart. An operator fixing a bad deployment
        should get the whole list on the first attempt rather than
        discovering the next problem after each redeploy."""
        with pytest.raises(ValidationError) as caught:
            build(debug=True, s3_secret_key="minioadmin", database_echo=True)

        message = message_of(caught)
        assert "DEBUG=true" in message
        assert "minioadmin" in message
        assert "DATABASE_ECHO" in message

    def test_it_says_what_to_do_next(self) -> None:
        with pytest.raises(ValidationError) as caught:
            build(debug=True)

        assert "production-deployment-guide" in message_of(caught)
