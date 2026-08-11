from fastapi import APIRouter, Depends

# Registers every concrete ChannelProvider (@ChannelRegistry.register(...))
# at import time — see infrastructure/channels/providers/__init__.py.
import blinkengage.infrastructure.channels.providers  # noqa: F401
from blinkengage.api.deps import require_export_feature, require_feature
from blinkengage.api.v1.endpoints import (
    admin,
    agents,
    ai,
    ai_actions,
    audit_logs,
    auth,
    billing,
    channel_configs,
    channel_connect,
    company,
    conversation_deletion,
    conversations,
    csat,
    customers,
    departments,
    erp_configs,
    erp_webhooks,
    faqs,
    guide,
    health,
    inspector,
    knowledge,
    knowledge_records,
    learning,
    memory,
    message_redaction,
    notifications,
    ownership,
    payment_webhooks,
    platform,
    platform_billing,
    platform_health,
    platform_invoicing,
    platform_ledger,
    platform_payments,
    platform_pricing,
    platform_settings,
    platform_usage,
    platform_users,
    queues,
    quick_replies,
    realtime,
    reports,
    roles,
    routing_rules,
    search,
    services,
    sla,
    sla_clocks,
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
api_router.include_router(guide.router)
api_router.include_router(version.router)
api_router.include_router(auth.router)
api_router.include_router(platform.router)
# A company's user accounts, administered by platform staff. Its own
# router, registered alongside `platform.router` rather than merged into
# it, so the read-only gate and the tenant-content boundary are declared
# once per file instead of once per route.
api_router.include_router(platform_users.router)
api_router.include_router(platform_pricing.router)
api_router.include_router(platform_usage.router)
api_router.include_router(platform_billing.router)
api_router.include_router(ownership.router)
api_router.include_router(sla_clocks.router)
# The Conversation Black Box. Not feature-gated: explaining what the
# platform did to a conversation is not a paid extra.
api_router.include_router(inspector.router)
api_router.include_router(platform_health.router)
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
api_router.include_router(conversation_deletion.router)
api_router.include_router(message_redaction.router)
api_router.include_router(queues.router)
api_router.include_router(services.router)
api_router.include_router(routing_rules.router)
api_router.include_router(roles.router)
api_router.include_router(sla.router, dependencies=[Depends(require_feature("sla"))])
api_router.include_router(workflows.router, dependencies=[Depends(require_feature("workflows"))])
api_router.include_router(
    knowledge.router, dependencies=[Depends(require_feature("knowledge_base"))]
)
# Same entitlement as the articles it sits beside — the `knowledge_base`
# feature is already described as "Internal knowledge articles and FAQ
# search", so an FAQ router gated differently would split one product
# capability across two things a customer can buy.
api_router.include_router(faqs.router, dependencies=[Depends(require_feature("knowledge_base"))])
# Structured knowledge rides the same entitlement as the articles and FAQs
# beside it: a company that bought "internal knowledge articles and FAQ
# search" has bought the knowledge base, and a price list is knowledge.
# Gating it separately would split one product capability across two
# things a customer can buy.
api_router.include_router(
    knowledge_records.router, dependencies=[Depends(require_feature("knowledge_base"))]
)
# No `require_feature` gate. Memory is platform infrastructure that the
# Customer Timeline, CRM and Reporting read as ordinary product surface —
# not a purchasable add-on like AI or SLA — and gating it would 402 an
# agent looking at a customer's history.
api_router.include_router(memory.router)
# No `require_feature` gate: Learning is platform infrastructure whose
# read surface is an operator view, not a purchasable add-on.
api_router.include_router(learning.router)
api_router.include_router(quick_replies.router)
api_router.include_router(search.router)
api_router.include_router(notifications.router)
api_router.include_router(ai_actions.router)
api_router.include_router(realtime.router)
api_router.include_router(ai.router, dependencies=[Depends(require_feature("ai"))])
api_router.include_router(reports.router, dependencies=[Depends(require_export_feature)])
api_router.include_router(csat.router)
api_router.include_router(erp_configs.router, dependencies=[Depends(require_feature("erp"))])
api_router.include_router(erp_webhooks.router)
api_router.include_router(company.router)
api_router.include_router(admin.router)
