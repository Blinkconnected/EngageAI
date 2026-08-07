# Event Catalogue

Every domain event the platform emits, what emits it, and what reacts to
it. **99 event types**, generated from the source and cross-checked
against the live broker's bindings.

This exists because the RC1 audit found 92 of them undocumented. That is
worse than a missing reference page: the event bus is how every
asynchronous behaviour in the platform is triggered, and an undocumented
event is one nobody can reason about when deciding whether a new consumer
would double-handle it, or whether an existing one already covers a case.

For *how* the bus works — the transactional outbox, the relay, the
topic exchange, delivery guarantees — see
[`event-bus.md`](./event-bus.md). This page is the inventory.

## How to read this

**Emitted by** is the module that constructs the `DomainEvent`. Events
are written to the `event_outbox` table inside the same transaction as
the business change that caused them, then relayed to RabbitMQ by
`relay-event-outbox` (every 5 s). Nothing publishes directly to the
broker.

**Consumed by** lists the consumer queues bound to that routing key.

Two consumers are bound to `#` — every event — and are deliberately
omitted from the per-event column to keep it readable:

- **`audit-log`** consumes everything and writes the audit trail. Every
  event in this catalogue is audited.
- **`workflow-engine`** consumes everything, because a customer-defined
  workflow may trigger on any event type.

So an event marked *audit + workflow only* is not unused — it is
persisted to the audit trail and available as a workflow trigger. It
simply has no bespoke consumer of its own.

## Naming

`<aggregate>.<past-tense-verb>`. Events describe something that **has
happened**; a consumer may not refuse it. Anything that reads like a
command (`send.email`) belongs in a task queue, not here.

## Payloads

Payload shape is defined by the `DomainEvent` construction site listed in
each row, and is stored as JSON in `event_outbox.payload`. Consumers must
tolerate unknown fields: payloads are additive, and a consumer that
breaks on a new key would turn a routine change into an outage. Every
event also carries `company_id` (tenant), `aggregate_id`,
`actor_user_id`, `occurred_at`, and a `correlation_id` tying it back to
the request that produced it.

---

## Catalogue

### `agent.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `agent.created` | `agent_service` | *audit + workflow only* |
| `agent.deleted` | `agent_service` | *audit + workflow only* |
| `agent.password_reset` | `agent_service` | *audit + workflow only* |
| `agent.status_changed` | `agent_service` | *audit + workflow only* |
| `agent.updated` | `agent_service` | *audit + workflow only* |

### `ai.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `ai.completed` | `ai_service` | `reporting` |

### `billing.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `billing.credit_note_issued` | `invoice_service` | *audit + workflow only* |
| `billing.payment_recorded` | `invoice_service` | *audit + workflow only* |

### `channel_config.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `channel_config.created` | `channel_config_service` | *audit + workflow only* |
| `channel_config.deleted` | `channel_config_service` | *audit + workflow only* |
| `channel_config.test_connection_ephemeral` | `channel_config_service` | *audit + workflow only* |
| `channel_config.updated` | `channel_config_service` | *audit + workflow only* |

### `company.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `company.ai_config_updated` | `company_service` | *audit + workflow only* |
| `company.logo_removed` | `company_service` | *audit + workflow only* |
| `company.logo_updated` | `company_service` | *audit + workflow only* |
| `company.registered` | `auth_service` | *audit + workflow only* |
| `company.updated` | `company_service` | *audit + workflow only* |

### `conversation.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `conversation.assignment_changed` | `conversation_service|events/consumers/conversation_ingest_consumer` | `reporting`, `notifications` |
| `conversation.autopilot_handoff_needed` | `autopilot_service` | `notifications` |
| `conversation.autopilot_replied` | `autopilot_service` | `reporting`, `usage-metering` |
| `conversation.autopilot_stopped` | `conversation_service` | *audit + workflow only* |
| `conversation.created` | `events/consumers/conversation_ingest_consumer` | `reporting`, `usage-metering` |
| `conversation.deleted` | `conversation_service` | *audit + workflow only* |
| `conversation.picked` | `conversation_service` | *audit + workflow only* |
| `conversation.queued` | `events/consumers/conversation_ingest_consumer` | *audit + workflow only* |
| `conversation.released` | `conversation_service` | *audit + workflow only* |
| `conversation.reopened` | `conversation_service|events/consumers/conversation_ingest_consumer` | `learning-signals` |
| `conversation.transferred` | `conversation_service` | `learning-signals`, `notifications` |
| `conversation.updated` | `conversation_service` | `reporting` |

### `csat.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `csat.submitted` | `csat_service` | `learning-signals`, `reporting` |

### `customer.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `customer.created` | `customer_service|events/consumers/conversation_ingest_consumer` | `erp-sync` |
| `customer.deleted` | `customer_service` | *audit + workflow only* |
| `customer.updated` | `customer_service` | *audit + workflow only* |

### `customer_internal_rating.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `customer_internal_rating.created` | `customer_internal_rating_service` | *audit + workflow only* |
| `customer_internal_rating.deleted` | `customer_internal_rating_service` | *audit + workflow only* |
| `customer_internal_rating.updated` | `customer_internal_rating_service` | *audit + workflow only* |

### `department.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `department.created` | `department_service` | *audit + workflow only* |
| `department.deleted` | `department_service` | *audit + workflow only* |
| `department.updated` | `department_service` | *audit + workflow only* |

### `erp.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `erp.customer_synced` | `erp_sync_service` | *audit + workflow only* |

### `erp_config.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `erp_config.created` | `erp_config_service` | *audit + workflow only* |
| `erp_config.deleted` | `erp_config_service` | *audit + workflow only* |
| `erp_config.updated` | `erp_config_service` | *audit + workflow only* |

### `faq.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `faq.created` | `faq_service` | *audit + workflow only* |
| `faq.deleted` | `faq_service` | *audit + workflow only* |
| `faq.updated` | `faq_service` | *audit + workflow only* |

### `holiday.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `holiday.created` | `sla_policy_service` | *audit + workflow only* |
| `holiday.deleted` | `sla_policy_service` | *audit + workflow only* |
| `holiday.updated` | `sla_policy_service` | *audit + workflow only* |

### `internal_note.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `internal_note.created` | `internal_note_service` | *audit + workflow only* |
| `internal_note.deleted` | `internal_note_service` | *audit + workflow only* |
| `internal_note.updated` | `internal_note_service` | *audit + workflow only* |

### `knowledge_article.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `knowledge_article.created` | `knowledge_service` | *audit + workflow only* |
| `knowledge_article.deleted` | `knowledge_service` | *audit + workflow only* |
| `knowledge_article.updated` | `knowledge_service` | *audit + workflow only* |

### `knowledge_category.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `knowledge_category.created` | `knowledge_service` | *audit + workflow only* |
| `knowledge_category.deleted` | `knowledge_service` | *audit + workflow only* |
| `knowledge_category.updated` | `knowledge_service` | *audit + workflow only* |

### `learning.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `learning.thresholds_changed` | `learning_settings_service` | *audit + workflow only* |

### `memory.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `memory.subject_erased` | `memory_erasure_service` | *audit + workflow only* |

### `message.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `message.persisted` | `events/consumers/conversation_ingest_consumer` | `ai-autopilot`, `notifications`, `usage-metering` |
| `message.received` | `inbound_message_events` | `conversation-ingest` |
| `message.sent` | `conversation_service` | `reporting`, `usage-metering` |

### `platform.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `platform.company_features_changed` | `feature_service` | *audit + workflow only* |
| `platform.company_owner_transferred` | `platform_user_service` | *audit + workflow only* |
| `platform.company_status_changed` | `platform_service` | *audit + workflow only* |
| `platform.user_role_changed` | `platform_user_service` | *audit + workflow only* |
| `platform.user_status_changed` | `platform_user_service` | *audit + workflow only* |
| `platform.user_verification_resent` | `platform_user_service` | *audit + workflow only* |

### `queue.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `queue.created` | `queue_service` | *audit + workflow only* |
| `queue.deleted` | `queue_service` | *audit + workflow only* |
| `queue.updated` | `queue_service` | *audit + workflow only* |

### `quick_reply.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `quick_reply.created` | `quick_reply_service` | *audit + workflow only* |
| `quick_reply.deleted` | `quick_reply_service` | *audit + workflow only* |
| `quick_reply.updated` | `quick_reply_service` | *audit + workflow only* |

### `role.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `role.created` | `role_service` | *audit + workflow only* |
| `role.deleted` | `role_service` | *audit + workflow only* |
| `role.updated` | `role_service` | *audit + workflow only* |

### `routing_rule.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `routing_rule.created` | `routing_rule_service` | *audit + workflow only* |
| `routing_rule.deleted` | `routing_rule_service` | *audit + workflow only* |
| `routing_rule.updated` | `routing_rule_service` | *audit + workflow only* |

### `sla_policy.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `sla_policy.created` | `sla_policy_service` | *audit + workflow only* |
| `sla_policy.deleted` | `sla_policy_service` | *audit + workflow only* |
| `sla_policy.updated` | `sla_policy_service` | *audit + workflow only* |

### `team.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `team.created` | `team_service` | *audit + workflow only* |
| `team.deleted` | `team_service` | *audit + workflow only* |
| `team.updated` | `team_service` | *audit + workflow only* |

### `team_membership.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `team_membership.added` | `team_service` | *audit + workflow only* |
| `team_membership.removed` | `team_service` | *audit + workflow only* |

### `usage.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `usage.late_record_rejected` | `usage_service` | *audit + workflow only* |
| `usage.period_closed` | `usage_service` | *audit + workflow only* |

### `user.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `user.login` | `auth_service` | *audit + workflow only* |
| `user.logout` | `auth_service` | *audit + workflow only* |
| `user.password_changed` | `auth_service` | *audit + workflow only* |
| `user.role_changed` | `role_service` | *audit + workflow only* |

### `workflow.*`

| Event | Emitted by | Consumed by |
|---|---|---|
| `workflow.created` | `workflow_service` | *audit + workflow only* |
| `workflow.deleted` | `workflow_service` | *audit + workflow only* |
| `workflow.executed` | `workflow_engine` | *audit + workflow only* |
| `workflow.updated` | `workflow_service` | *audit + workflow only* |

---

## Consumers, and what each one is for

| Queue | Binds | Purpose |
|---|---|---|
| `audit-log` | `#` | Writes the immutable audit trail. Everything. |
| `workflow-engine` | `#` | Evaluates customer-defined workflow triggers. |
| `conversation-ingest` | `message.received` | Turns an inbound channel message into a conversation and message row. |
| `ai-autopilot` | `message.persisted` | Decides whether AI may answer, and answers. |
| `autopilot-sla` | `conversation.sla_warning`, `conversation.sla_breached` | Stops autopilot when a conversation is in SLA trouble. |
| `notifications` | assignment, transfer, handoff, breach, message | Fans out to email/push. Routing keys derive from the notification-rule registry, not a hand-kept list. |
| `reporting` | conversation, message, AI and CSAT events | Maintains reporting aggregates. |
| `usage-metering` | conversation/message/autopilot events | Records billable usage. Routing keys derive from the billable-event registry. |
| `csat-dispatch` | `conversation.resolved` | Sends the satisfaction survey. |
| `erp-sync` | `customer.created` | Pushes the customer into ERPNext. |
| `learning-observation` | `conversation.resolved`, `conversation.closed` | Records an observation for the intelligence layer. |
| `learning-signals` | `csat.submitted`, `conversation.reopened`, `conversation.transferred`, `conversation.sla_breached` | Records outcome signals. |

Each queue has a `.retry` and a `.dlq` sibling — see
[Reliability](./event-bus.md) and the
[DLQ runbook](../deployment/runbooks.md#drain-a-dead-letter-queue).

## Adding an event

1. Emit it via the outbox — never publish to the broker directly, or it
   will not be transactional and can be lost on rollback.
2. Add a row to this catalogue in the same commit.
3. If a consumer should react, bind the routing key there. Do **not**
   add a consumer that binds `#` — two already do, and a third would
   make every event three times as expensive.
4. Remember it is automatically audited and automatically available as a
   workflow trigger. That is often all a new event needs.

## See also

- [Event bus architecture](./event-bus.md) — outbox, relay, delivery guarantees
- [Operator runbook](../deployment/runbooks.md) — draining and replaying
- [V1.0 Baseline](../releases/v1.0-baseline.md)
