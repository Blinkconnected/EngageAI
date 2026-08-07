# Frequently Asked Questions

Short answers, grouped by who is asking. Where an answer is "no", it says
so plainly and points at where the limitation is recorded.

- [For agents](#for-agents)
- [For administrators](#for-administrators)
- [About AI](#about-ai)
- [About channels](#about-channels)
- [About SLA and reporting](#about-sla-and-reporting)
- [About data, privacy and security](#about-data-privacy-and-security)
- [For operators](#for-operators)
- [For developers](#for-developers)
- [Commercial and roadmap](#commercial-and-roadmap)

---

## For agents

**Why is my menu shorter than my colleague's?**
It shows only what your role permits and what your company's plan
includes. Both filters are invisible — you see the result, not the
reason. Ask your administrator which of the two it is.

**A conversation I was working on disappeared from "mine".**
Ownership expires if a conversation goes untouched, and it returns to the
queue so it is not stranded on somebody who has gone home. Pick it up
again.

**What does the "Unrouted" warning mean?**
The conversation reached no queue at all, so nobody is watching it. This
is the one badge to escalate — it means routing configuration is broken,
not that the conversation is merely waiting.

**Can the customer see my internal note?**
No. Notes are never delivered. They are permanent and auditable, so write
them as though a colleague will read them a year from now — because one
might.

**I replied but the customer says nothing arrived.**
Check **Status** for that channel. An expired token is the usual cause,
and it fails silently from the agent's side. Give your administrator the
time and the conversation id.

**Can I edit or delete a message I sent?**
No. Messages delivered to a channel cannot be recalled — the platform
does not control the customer's device. Send a correction.

**Why did a resolved conversation come back?**
A customer replying to a resolved conversation reopens it rather than
starting a new one, so the history stays in one place.

**Can I work on mobile?**
Through the browser, yes — the interface is responsive. There is no
native app ([L-8](../releases/v1.0-known-limitations.md)).

## For administrators

**What is the minimum to go live?**
Connect one channel. Everything else has a working default: your
workspace is created with a queue, a catch-all routing rule and a
service, so nothing can arrive with nowhere to go.

**Do I need departments and teams?**
No. Create them when you have a reason. An empty hierarchy is overhead.

**Why can I not set a user's password?**
You cannot set one on someone's behalf — you trigger a reset and they
choose it. Nobody should be able to sign in as somebody else.

**I deleted the catch-all routing rule. What happens?**
Conversations matching no other rule are recorded as `LEFT_UNROUTED` and
wait where nobody is looking. Recreate a rule with empty conditions at
the lowest priority.

**Should I delete or deactivate a departing agent?**
Deactivate. It preserves their conversation history and audit trail and
removes them from assignment.

**Can I import my existing customers?**
Not through a bulk import screen. The API can create customers, and ERP
sync brings them in if you use ERPNext.

**Can I change the company timezone later?**
Yes, but it does not retroactively correct reports already generated. Set
it before you start, not after.

## About AI

**Will the AI answer customers on its own?**
Only if you enable autopilot, and only when confidence clears your
threshold. Otherwise it drafts and an agent sends.

**What happens when the AI is unsure?**
It stops and marks the conversation **handoff needed** rather than
guessing. It also stops automatically when a conversation is in SLA
trouble.

**Can I use it without sending data to OpenAI or Anthropic?**
Yes. Ollama runs locally. This is the configuration for customers who
cannot send conversation content to a third party.

**The AI gives wrong answers.**
It answers from your knowledge base. An out-of-date article produces a
confidently wrong answer. Check what it drew on before changing the
threshold.

**Does the AI learn from our conversations?**
Not in this release. The intelligence layer observes and reports patterns
but writes nothing back — no memory, no knowledge suggestions, no change
to handling ([L-7](../releases/v1.0-known-limitations.md)).

**How much does AI usage cost?**
Provider charges are yours. The platform meters usage per company and
reports it under Billing.

## About channels

**Which channels are supported?**
WhatsApp, Facebook Messenger, Instagram, Telegram, Email, SMS and Web
Chat, plus a plugin architecture for others.

**Do I choose which channel to reply on?**
No. The reply goes back the way the customer came in.

**A channel stopped working.**
Check **Status**. Almost always an expired token. Reconnect and use
**Test connection**.

**Why did my channel never receive anything, from the start?**
Credentials were saved but never tested. Saved is not verified — a typo'd
token reports no error and silently receives nothing. Always test.

**Can one customer reach us on two channels?**
Yes, and the platform merges them into one customer record where it can
tell it is the same person.

## About SLA and reporting

**Our SLA numbers look wrong.**
Business hours are almost certainly unconfigured, so every hour counts as
a working hour and an overnight message breaches before anyone is back.
This is the most common configuration mistake in the platform.

**What are the four clocks?**
First response, next response, resolution, and idle. See the
[User Guide](./user-guide.md#9-sla).

**Can I export reports?**
PDF and Excel, if your plan includes Report Export.

**Are reports real-time?**
The Live dashboard is near-real-time. The rest are built from aggregates
refreshed hourly.

**Why does the AI report show fewer conversations than the AI handled?**
Check whether the reporting consumer is keeping up — your operator can
see queue depth. A backlog shows as under-reporting, not as an error.

## About data, privacy and security

**Can one company see another's data?**
No. Tenant isolation is enforced on every query in the application layer,
not by convention, and there is no cross-tenant read path.

**Where are credentials stored?**
Channel and ERP credentials are encrypted at rest. Platform secrets come
from the environment and are never in version control. Backup archives
containing secrets are AES-256 encrypted.

**Is there an audit trail?**
Yes — every domain event, append-only, never pruned, with the correlation
id tying it back to the originating request.

**Can we delete a customer's data on request?**
Customer records can be erased, and there is a memory erasure path for
the intelligence layer. Conversation history is retained by default —
whether it should be is a jurisdiction question, recorded as
[L-4](../releases/v1.0-known-limitations.md).

**How long is data kept?**
Business data indefinitely by default. Operational telemetry is pruned:
scheduler runs after 30 days, dispatched outbox rows after 7. Audit logs
are never pruned. Full table-by-table statement in the
[Data Register](../releases/v1.0-baseline.md#data-register).

**Is the platform GDPR/HIPAA compliant?**
The platform provides the technical controls — tenant isolation,
encryption at rest, audit trail, erasure paths, access control.
Compliance is a property of your whole operation, not of software alone,
and no certification is claimed.

## For operators

**How do I know backups are working?**
```bash
systemctl list-timers 'blinkengage-*'
ls -lt backups/ | head
```
The newest set should be under 24 hours old. Silence is the failure mode
— check rather than assume.

**How much data would we lose in a disaster?**
Up to 24 hours ([L-1](../releases/v1.0-known-limitations.md)). Backups are
nightly.

**How long would recovery take?**
Plan for 30–60 minutes. The measured restore phase is 4.8 seconds, but
that excludes detection, decision, provisioning and cutover
([L-6](../releases/v1.0-known-limitations.md)).

**Has the restore actually been tested?**
Yes. `scripts/dr_rehearsal.sh` restores all four asset classes into
scratch resources and was executed and passed. A weekly drill runs
automatically.

**A dead-letter queue alert fired.**
A message failed five times over about five minutes of backoff and was
quarantined. Nothing is lost. See the
[DLQ runbook](../deployment/runbooks.md#drain-a-dead-letter-queue) —
inspect first, fix the cause, then replay.

**How do I trace one request?**
Every request carries a correlation id through the outbox, queues,
consumers and Celery tasks:
```
{job="blinkengage"} |= "<correlation-id>"
```

**Do alerts actually reach anyone?**
`./scripts/verify_alerting.sh` fires a real alert through the real
routing and confirms it arrives. Run it before go-live and after any
alerting change.

**Is the monitoring stack itself monitored?**
Not yet — recorded as [TD-2](../releases/v1.0-technical-debt.md#td-2). If
Prometheus or Grafana stops, dashboards go quiet and that currently looks
like a healthy platform.

## For developers

**Where is the API reference?**
Generated OpenAPI at `/docs`, `/redoc` and `/api/v1/openapi.json` —
**disabled in production**. Conventions in
[API Reference](../api/README.md).

**How many endpoints are there?**
330 across 256 paths, all documented with a summary or description.

**Is there a WebSocket?**
Yes — `/api/v1/ws/agent` for agents and `/api/v1/ws/{channel_config_id}`
for web chat. Neither appears in the OpenAPI schema, because FastAPI does
not document WebSocket routes.

**Can I build a mobile app against this?**
Yes. Auth with refresh, device registration, FCM push and the agent
WebSocket all exist. Read the
[Mobile Integration Guide](../api/mobile-integration-guide.md) first —
it lists the real gaps.

**Are there webhooks?**
The workflow engine can call a webhook on any of the 99 event types.

**How do I add an event?**
Emit it through the outbox — never publish to the broker directly — and
add it to the [Event Catalogue](../architecture/event-catalogue.md) in
the same commit.

**Why is `domain/` not allowed to do I/O?**
So business rules are testable without a database and cannot quietly
acquire a second implementation. It is the most load-bearing rule in the
codebase ([Baseline §4](../releases/v1.0-baseline.md#invariants)).

**Is delivery exactly-once?**
No — at-least-once. Consumers must be idempotent. A redelivered message
must not double-charge or double-notify.

## Commercial and roadmap

**Is there a mobile app?**
No ([L-8](../releases/v1.0-known-limitations.md)).

**Can it run on Kubernetes?**
Not as shipped. Docker Compose on a single host is the only topology
built, tested and rehearsed ([L-10](../releases/v1.0-known-limitations.md)).

**Is there a high-availability configuration?**
No standby or replica in this release
([L-2](../releases/v1.0-known-limitations.md)).

**Is the interface available in Arabic?**
Yes, including right-to-left layout. Documentation is English only.

**What is coming next?**
See the [Roadmap](../releases/v1.0-roadmap.md).

---

## Still stuck?

Give whoever helps you three things: **when** it happened, the
**conversation or customer id**, and what you **expected**. Every request
carries a correlation id, and those facts turn an afternoon of guessing
into a single log query.

## See also

- [User Guide](./user-guide.md)
- [Administrator Guide](./administrator-guide.md)
- [Known Limitations](../releases/v1.0-known-limitations.md)
