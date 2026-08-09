"""Every variable `.env.example` advertises must be one something reads.

Configuration that is advertised and ignored is worse than configuration
that is absent: the absent one prompts a question, the ignored one
produces confident silence.

The instance this exists to prevent, in full, because the shape matters
more than the keys: `.env.example` declared `PAYPAL_ENVIRONMENT=sandbox`
and nothing read it. The setting that actually chose live-versus-test was
`PAYPAL_SANDBOX`, a boolean. An operator who read this file, set
`PAYPAL_ENVIRONMENT=live`, restarted, and watched the service come up
healthy had every reason to believe they had switched to live payments.
They were still in sandbox. Taking no real money. With nothing reporting
an error.

It survived an RC1 audit that *found and named it* (TD-1) and a release
gate, because finding it and preventing the next one are different jobs.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
CONFIG = REPO_ROOT / "backend/src/blinkengage/core/config.py"

#: Keys consumed by the infrastructure rather than by `Settings` —
#: docker-compose, the Postgres/MinIO/Grafana images, the frontend build.
#: A prefix here means "something outside the application reads this",
#: which is a claim worth being deliberate about.
INFRASTRUCTURE_PREFIXES = (
    "POSTGRES_",
    "RABBITMQ_",
    "MINIO_",
    "GRAFANA_",
    "GF_",
    "LOKI_",
    "PROMETHEUS_",
    "REDIS_",
    "NGINX_",
    "BACKUP_",
    "ACME_",
    "CERTBOT_",
    "COMPOSE_",
    "VITE_",
    "TRAEFIK_",
    "TZ",
    "DOMAIN",
)


def _declared_keys() -> list[str]:
    keys = []
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.append(line.split("=", 1)[0].strip())
    return keys


def _settings_names() -> set[str]:
    source = CONFIG.read_text(encoding="utf-8")
    fields = set(re.findall(r"^\s{4}([a-z_][a-z0-9_]*)\s*:", source, re.M))
    # Explicit env names win over the field name when both exist.
    aliases = set(re.findall(r'(?:alias|validation_alias|env)\s*=\s*"([^"]+)"', source))
    return {name.lower() for name in fields | aliases}


def test_every_advertised_variable_is_read_by_something() -> None:
    names = _settings_names()
    dead = [
        key
        for key in _declared_keys()
        if not key.startswith(INFRASTRUCTURE_PREFIXES) and key.lower() not in names
    ]

    assert not dead, (
        "`.env.example` advertises variables nothing reads:\n"
        + "\n".join(f"  {key}" for key in dead)
        + "\n\nEither add the field to `Settings`, add its prefix to "
        "INFRASTRUCTURE_PREFIXES if something outside the application "
        "consumes it, or delete the line. An operator will set it and "
        "believe it took effect."
    )


def test_the_paypal_live_switch_is_the_one_that_works() -> None:
    """A named regression test, not a duplicate of the sweep above.

    This is the key that could cost money, so it is asserted by name: if
    `PAYPAL_ENVIRONMENT` ever comes back, the failure should say what it
    costs rather than reading as one more dead key.
    """
    declared = set(_declared_keys())

    assert "PAYPAL_ENVIRONMENT" not in declared, (
        "PAYPAL_ENVIRONMENT is back. Nothing reads it. Setting it to 'live' "
        "leaves the platform in sandbox, healthy, taking no real money. The "
        "switch is PAYPAL_SANDBOX."
    )
    assert "PAYPAL_SANDBOX" in declared, (
        "PAYPAL_SANDBOX has gone from .env.example. It is the live/test "
        "switch, and an operator cannot set what is not documented."
    )
