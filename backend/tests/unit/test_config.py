from blinkengage.core.config import get_settings


def test_settings_load_from_environment() -> None:
    settings = get_settings()
    assert settings.jwt_secret_key
    assert settings.database_url.startswith("sqlite")
    assert settings.environment == "test"


def test_cors_origins_split_from_comma_separated_string() -> None:
    from blinkengage.core.config import Settings

    settings = Settings(
        jwt_secret_key="x" * 32,
        database_url="sqlite+aiosqlite:///:memory:",
        cors_allow_origins="http://a.test, http://b.test",
    )
    assert settings.cors_allow_origins == ["http://a.test", "http://b.test"]
