from pydantic import BaseModel


class PluginRegistryResponse(BaseModel):
    """A snapshot of every plugin registry this platform's registry-
    keyed-by-string architecture (channels, SMS gateways, AI providers,
    workflow actions) currently has registered — what an admin console's
    "integrations"/"plugin management" screen reads to show what's
    available versus what's actually turned on. See
    ``docs/architecture/administration.md``.
    """

    channel_types: list[str]
    sms_gateways: list[str]
    ai_providers: list[str]
    active_ai_provider: str
    workflow_actions: list[str]
