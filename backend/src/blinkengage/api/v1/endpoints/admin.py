"""Administration console endpoints — plugin registry introspection. See
``docs/architecture/administration.md``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

# Registers every built-in WorkflowAction — normally only imported by the
# workflow-engine-consumer process; the API process needs it too, purely
# so this introspection endpoint can report what's registered (nothing
# else in the API process reads this registry today).
import blinkengage.application.workflow_actions  # noqa: F401
from blinkengage.api.deps import get_settings_dep, require_permission
from blinkengage.api.schemas.admin import PluginRegistryResponse
from blinkengage.core.auth_context import AuthContext
from blinkengage.core.config import Settings
from blinkengage.infrastructure.ai.registry import AiProviderRegistry
from blinkengage.infrastructure.channels.registry import ChannelRegistry
from blinkengage.infrastructure.channels.sms_gateway_registry import SmsGatewayRegistry
from blinkengage.infrastructure.workflow.action_registry import WorkflowActionRegistry

router = APIRouter(prefix="/admin", tags=["administration"])


@router.get("/plugins", response_model=PluginRegistryResponse)
async def list_plugins(
    auth: Annotated[AuthContext, Depends(require_permission("company.manage"))],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> PluginRegistryResponse:
    return PluginRegistryResponse(
        channel_types=sorted(ChannelRegistry.known_channel_types()),
        sms_gateways=sorted(SmsGatewayRegistry.known_gateways()),
        ai_providers=sorted(AiProviderRegistry.known_providers()),
        active_ai_provider=settings.ai_provider,
        workflow_actions=sorted(WorkflowActionRegistry.known_action_types()),
    )
