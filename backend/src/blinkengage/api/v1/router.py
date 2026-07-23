from fastapi import APIRouter

# Registers every concrete ChannelProvider (@ChannelRegistry.register(...))
# at import time — see infrastructure/channels/providers/__init__.py.
import blinkengage.infrastructure.channels.providers  # noqa: F401
from blinkengage.api.v1.endpoints import (
    agents,
    ai,
    audit_logs,
    auth,
    channel_configs,
    conversations,
    csat,
    customers,
    departments,
    health,
    knowledge,
    notifications,
    queues,
    quick_replies,
    realtime,
    reports,
    routing_rules,
    teams,
    web_chat,
    webhooks,
    workflows,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(departments.router)
api_router.include_router(teams.router)
api_router.include_router(agents.router)
api_router.include_router(customers.router)
api_router.include_router(audit_logs.router)
api_router.include_router(channel_configs.router)
api_router.include_router(webhooks.router)
api_router.include_router(web_chat.router)
api_router.include_router(conversations.router)
api_router.include_router(queues.router)
api_router.include_router(routing_rules.router)
api_router.include_router(workflows.router)
api_router.include_router(knowledge.router)
api_router.include_router(quick_replies.router)
api_router.include_router(notifications.router)
api_router.include_router(realtime.router)
api_router.include_router(ai.router)
api_router.include_router(reports.router)
api_router.include_router(csat.router)
