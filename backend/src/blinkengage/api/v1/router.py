from fastapi import APIRouter, Depends

# Registers every concrete ChannelProvider (@ChannelRegistry.register(...))
# at import time — see infrastructure/channels/providers/__init__.py.
import blinkengage.infrastructure.channels.providers  # noqa: F401
from blinkengage.api.deps import require_export_feature, require_feature
from blinkengage.api.v1.endpoints import (
    admin,
    agents,
    ai,
    audit_logs,
    auth,
    billing,
    channel_configs,
    channel_connect,
    company,
    conversations,
    csat,
    customers,
    departments,
    erp_configs,
    erp_webhooks,
    health,
    knowledge,
    notifications,
    payment_webhooks,
    platform,
    platform_billing,
    platform_invoicing,
    platform_ledger,
    platform_payments,
    platform_pricing,
    platform_settings,
    platform_usage,
    queues,
    quick_replies,
    realtime,
    reports,
    roles,
    routing_rules,
    search,
    sla,
    teams,
    version,
    web_chat,
    webhooks,
    workflows,
)

# Feature entitlements are applied here, at registration, rather than on
# each endpoint: one place to read, and a new endpoint added to a gated
# router inherits the gate instead of quietly shipping ungated. See
# `domain/features.py`.
api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(version.router)
api_router.include_router(auth.router)
api_router.include_router(platform.router)
api_router.include_router(platform_pricing.router)
api_router.include_router(platform_usage.router)
api_router.include_router(platform_billing.router)
api_router.include_router(platform_invoicing.router)
api_router.include_router(platform_ledger.router)
api_router.include_router(platform_payments.router)
api_router.include_router(platform_settings.router)
api_router.include_router(payment_webhooks.router)
# The tenant's own billing. Not feature-gated: every company is billed, and
# a customer must always be able to see what they are being charged.
api_router.include_router(billing.router)
api_router.include_router(departments.router)
api_router.include_router(teams.router)
api_router.include_router(agents.router)
api_router.include_router(customers.router)
api_router.include_router(audit_logs.router)
api_router.include_router(channel_configs.router)
api_router.include_router(channel_connect.router)
api_router.include_router(webhooks.router)
api_router.include_router(web_chat.router)
api_router.include_router(conversations.router)
api_router.include_router(queues.router)
api_router.include_router(routing_rules.router)
api_router.include_router(roles.router)
api_router.include_router(sla.router, dependencies=[Depends(require_feature("sla"))])
api_router.include_router(workflows.router, dependencies=[Depends(require_feature("workflows"))])
api_router.include_router(
    knowledge.router, dependencies=[Depends(require_feature("knowledge_base"))]
)
api_router.include_router(quick_replies.router)
api_router.include_router(search.router)
api_router.include_router(notifications.router)
api_router.include_router(realtime.router)
api_router.include_router(ai.router, dependencies=[Depends(require_feature("ai"))])
api_router.include_router(reports.router, dependencies=[Depends(require_export_feature)])
api_router.include_router(csat.router)
api_router.include_router(erp_configs.router, dependencies=[Depends(require_feature("erp"))])
api_router.include_router(erp_webhooks.router)
api_router.include_router(company.router)
api_router.include_router(admin.router)
