"""Per-channel-type credential shape validation — Phase 1: Channel
Experience. Validated at ``ChannelConfigService.create``/``update`` time
so a malformed ``credentials`` dict is rejected with a clear 400 instead
of silently accepted and only discovered later, indirectly, the first
time a provider tries to use a missing key. See
``docs/architecture/channel-integration-spec.md`` gap #4.

Only channels covered by Phase 1 (WhatsApp, Telegram, Email, Web Chat)
have a schema registered here — Messenger/Instagram/SMS keep today's
unvalidated behavior until they get the same treatment in a later phase.
"""

from pydantic import BaseModel, Field, ValidationError

from blinkengage.domain.exceptions import InvalidChannelCredentialsError


class WhatsAppCredentials(BaseModel):
    phone_number_id: str = Field(min_length=1)
    access_token: str = Field(min_length=1)
    # Optional here, not required: auto-generated server-side in
    # ChannelConfigService.create() when left blank, same as
    # webhook_secret — see AUTO_GENERATED_CREDENTIAL_FIELDS.
    verify_token: str | None = None
    graph_api_base_url: str | None = None
    api_version: str | None = None


class TelegramCredentials(BaseModel):
    bot_token: str = Field(min_length=1)
    api_base_url: str | None = None
    file_base_url: str | None = None


class EmailCredentials(BaseModel):
    smtp_host: str = Field(min_length=1)
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool | None = None
    from_address: str | None = None
    default_subject: str | None = None
    # IMAP is optional — a channel with no imap_host simply never polls
    # (infrastructure/tasks/email_imap_poll_task.py), it isn't an error.
    imap_host: str | None = None
    imap_port: int | None = None
    imap_username: str | None = None
    imap_password: str | None = None
    imap_use_ssl: bool | None = None
    imap_folder: str | None = None


class WebChatCredentials(BaseModel):
    """Web Chat needs no external credentials at all — this schema exists
    so it participates in the same validation path as every other
    channel (accepting an empty object), not because it enforces
    anything."""

    model_config = {"extra": "allow"}


_CREDENTIAL_SCHEMAS: dict[str, type[BaseModel]] = {
    "whatsapp": WhatsAppCredentials,
    "telegram": TelegramCredentials,
    "email": EmailCredentials,
    "web_chat": WebChatCredentials,
}

#: channel_type -> the one credentials field that gets a random value
#: filled in server-side when the operator leaves it blank, the same way
#: every channel's webhook_secret does (ChannelConfigService.create()).
#: WhatsApp's verify_token is the only such field today — a value the
#: operator must also paste into Meta's dashboard, so (like
#: webhook_secret) it needs to be surfaced back to them once, not just
#: silently generated.
AUTO_GENERATED_CREDENTIAL_FIELDS: dict[str, str] = {
    "whatsapp": "verify_token",
}


def validate_channel_credentials(channel_type: str, credentials: dict[str, object]) -> None:
    schema = _CREDENTIAL_SCHEMAS.get(channel_type)
    if schema is None:
        return
    try:
        schema.model_validate(credentials)
    except ValidationError as exc:
        detail = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise InvalidChannelCredentialsError(channel_type, detail) from exc
