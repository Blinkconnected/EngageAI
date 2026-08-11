# Architecture Index

Sixty-eight architecture documents, organised by what you are trying to
find out. Start here rather than with the file listing — the listing is
alphabetical, which is not how anybody thinks about a system.

**If you read only one thing:** [Platform Handbook](./platform-handbook.md)
(4,889 lines) is the deep reference — bounded contexts, invariants,
diagrams.

**If you are new:** [SYSTEM.md](../SYSTEM.md) explains what every feature
does, from the product's point of view, before you meet the code.

**If you are about to build something:**
[V1.0 Baseline](../releases/v1.0-baseline.md) states the invariants your
change must not contradict.

---

## Start here

| Document | What it gives you |
|---|---|
| [Platform Handbook](./platform-handbook.md) | The whole architecture, in depth |
| [SYSTEM.md](../SYSTEM.md) | Every feature, functionally |
| [V1.0 Baseline](../releases/v1.0-baseline.md) | Invariants, registers, what is settled |
| [Backend](./backend.md) | Layering, patterns, conventions |
| [Frontend](./frontend.md) | React structure and state |
| [Infrastructure](./infrastructure.md) | Containers, networking, storage |

## Foundations

| Document | Covers |
|---|---|
| [Account & identity](./account-identity.md) | Users, companies, registration |
| [Auth & RBAC](./auth-rbac.md) | JWT, permissions, enforcement |
| [Execution context](./execution-context.md) | Tenant and actor propagation |
| [Policy engine](./policy-engine.md) | Configuration resolution |
| [Domain ownership](./domain-ownership.md) | Which context owns which concept |
| [Audit logging](./audit-logging.md) | The append-only trail |

## Conversations and channels

| Document | Covers |
|---|---|
| [Conversations](./conversations.md) | The core aggregate |
| [Deleting a conversation](./conversation-deletion.md) | Request, approval, and the record that outlives it |
| [Redacting a message](./message-redaction.md) | Removing what was said, keeping that it was said |
| [Inbox](./inbox.md) · [Inbox 9am](./inbox-9am.md) | Agent working surface |
| [Channels](./channels.md) | Channel abstraction |
| [Channel connectors](./channel-connectors.md) | Plugin architecture |
| [Channel integration spec](./channel-integration-spec.md) | Adding a channel |
| [WhatsApp & Telegram](./whatsapp-telegram.md) · [Messenger & Instagram](./messenger-instagram.md) · [Email](./email-channel.md) · [SMS](./sms.md) · [Web chat](./web-chat.md) | Per-channel detail |
| [Outbound delivery](./outbound-delivery.md) | Sending, and what degrades |

## Routing, queues and SLA

| Document | Covers |
|---|---|
| [Queues & routing](./queues-routing.md) | The model |
| [Queue architecture](./queue-architecture.md) · [Queue lifecycle](./queue-lifecycle.md) | Structure and states |
| [Routing rules](./routing-rules.md) | Evaluation and precedence |
| [Assignment logic](./assignment-logic.md) | Queue → agent |
| [Ownership consistency](./ownership-consistency.md) | Expiry and reclaim |
| [SLA](./sla.md) · [SLA engine](./sla-engine.md) | The four clocks |
| [Service-centric migration](./service-centric-migration.md) | Why Service anchors policy |

## AI and intelligence

| Document | Covers |
|---|---|
| [AI engine](./ai-engine.md) | Providers, prompts, operations |
| [AI eligibility model](./ai-eligibility-model.md) | When AI may act |
| [AI queue/worker validation](./ai-queue-worker-validation.md) | Autopilot safety |
| [Knowledge, memory & intelligence](./knowledge-memory-intelligence.md) | How they relate |
| [Memory platform](./memory-platform.md) | Conversation memory |
| [Company Intelligence Engine](./company-intelligence-engine.md) | The engine |
| [Company Knowledge and Adaptive Voice](./company-knowledge-and-voice.md) | M2 — structured knowledge, ingestion, voice |
| [Intelligence platform](./intelligence-platform.md) | Observation → pattern |

### Learning Platform

Read the [charter](./learning-platform-charter.md) first — it states what
the platform is **forbidden** to do, and every later document assumes it.

[Charter](./learning-platform-charter.md) ·
[Overview](./learning-platform.md) ·
[Phase 1 review](./learning-platform-phase-1-review.md) ·
[Phase 2](./learning-platform-phase-2.md) ·
[Phase 2 review](./learning-platform-phase-2-review.md) ·
[Shadow validation](./learning-platform-shadow-validation.md) ·
[Operator handbook](./learning-platform-operator-handbook.md) ·
[Dashboard](./learning-platform-dashboard.md) ·
[Pilot checklist](./learning-platform-pilot-checklist.md) ·
[Production readiness](./learning-platform-production-readiness.md)

## Content and knowledge

[Knowledge, quick replies & notes](./knowledge-quick-replies-notes.md) ·
[FAQ](./faq.md) ·
[Global search](./global-search.md)

## Events and asynchronous work

| Document | Covers |
|---|---|
| [Event bus](./event-bus.md) | Outbox, relay, delivery guarantees |
| [**Event catalogue**](./event-catalogue.md) | **All 99 event types** |
| [Workflow engine](./workflow-engine.md) | Customer-defined automation |
| [Notifications](./notifications.md) | Email and push delivery |
| [Real-time](./realtime.md) | The agent WebSocket contract, presence, reconnect |
| [AI tool calling](./ai-tool-calling.md) | How an AI may change a workspace, and what stops it |

## Customers and CRM

[Core CRM](./core-crm.md) ·
[Customer activity](./customer-activity.md) ·
[ERP integration](./erp-integration.md)

## Commercial

[Billing](./billing.md) ·
[Platform admin](./platform-admin.md) ·
[Administration](./administration.md) ·
[Reports & analytics](./reports-analytics.md)

## Operations and quality

| Document | Covers |
|---|---|
| [Observability](./observability.md) | Metrics, logs, alerting, backups |
| [Performance](./performance.md) | Query and index work |
| [Release & changelog](./release-changelog.md) | How releases are cut |
| [Navigation IA](./navigation-information-architecture.md) | Proposed menu structure |

## Architectural reviews

Point-in-time assessments. Useful for *why* something is as it is; not
current-state references.

[V1 architecture freeze](./v1-architecture-freeze.md) ·
[Freeze review](./architecture-freeze-review.md) ·
[Freeze review 2](./architecture-freeze-review-2.md)

---

## Other documentation

| Area | Index |
|---|---|
| **Guides** | [User](../guides/user-guide.md) · [Administrator](../guides/administrator-guide.md) · [FAQ](../guides/faq.md) |
| **API** | [Reference](../api/README.md) · [Mobile](../api/mobile-integration-guide.md) |
| **Deployment** | [Production](../deployment/production-deployment-guide.md) · [Runbooks](../deployment/runbooks.md) · [DR](../deployment/disaster-recovery.md) |
| **Release** | [Notes](../releases/v1.0-release-notes.md) · [Baseline](../releases/v1.0-baseline.md) · [Audit](../releases/v1.0-engineering-audit.md) · [Limitations](../releases/v1.0-known-limitations.md) · [Debt](../releases/v1.0-technical-debt.md) · [Roadmap](../releases/v1.0-roadmap.md) |
| **Product** | [Onboarding wizard spec](../product/tenant-onboarding-wizard.md) |
| **Security** | [`docs/security/`](../security/) |
| **Database** | [`docs/database/`](../database/) |

## Conventions

**Documents explain why, not just what.** A document that only restates
the code is a document that will drift and nobody will notice. If you
cannot say why a decision was made, that is worth recording too.

**Reviews are dated and kept.** They are not updated in place — a review
is a snapshot of a judgement, and rewriting it destroys the record of
what was known at the time.

**Outdated documentation is a defect.** When a change affects
architecture, workflows, APIs, schema, permissions, configuration or
deployment, the corresponding document is updated in the same commit.
