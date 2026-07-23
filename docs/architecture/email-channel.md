# Email Channel

M15 of the roadmap, opening Phase 3 (Omnichannel Expansion) — the first
channel built after the plugin architecture (M11) had a second, harder
data point to prove itself against: unlike Web Chat (M12, first-party, no
external API), email is provider-agnostic infrastructure (SMTP/IMAP are
protocols, not one vendor) with genuine inbound identity to resolve.

## Outbound: SMTP via `aiosmtplib`

`send_message` builds a `email.message.EmailMessage` and calls
`aiosmtplib.send(...)` — async-native, no thread-pool wrapping needed
(unlike the synchronous `minio` client M12 had to wrap). SMTP connection
details (`smtp_host`/`port`/`username`/`password`/`use_tls`, plus
`from_address`) live in the same encrypted `ChannelConfig.credentials`
blob every channel already uses (M11) — no new column, no new encryption
mechanism.

## Inbound: one MIME parser, two entry points

Email inbound arrives one of two ways, and roadmap explicitly names both:

1. **Provider webhook** — some ESPs (or a customer's own MTA forwarding
   rule) POST the raw MIME message to our existing generic
   `POST /webhooks/{channel_config_id}` route (M11) — no new route needed.
2. **IMAP polling** — for setups with no webhook-capable relay in front,
   a Celery-beat task periodically fetches `UNSEEN` messages from the
   configured mailbox.

Both paths hand the same raw RFC822 bytes to `EmailProvider.receive_message`,
which uses Python's standard-library `email` module (not a bespoke
per-ESP-format parser) — this is deliberately provider-agnostic rather
than committing to one ESP's specific inbound-webhook payload shape
(SendGrid's Inbound Parse, Mailgun's routes, and a generic
MIME-forwarding webhook all differ in *transport*, but the underlying
*message* is the same RFC822 format `email` already parses). Building a
bespoke parser for a specific ESP's webhook JSON shape is a documented
future extension for whichever ESP a deployment actually needs, not
built speculatively now.

### IMAP polling and idempotency

`infrastructure/tasks/email_imap_poll_task.py` is a Celery-beat task
(runs every 60s, alongside the SLA sweep) that, for every active
`ChannelConfig` with `channel_type="email"`, connects via `imaplib`
(synchronous — wrapped in a worker thread via `anyio.to_thread.run_sync`,
the same pattern `AttachmentStore` already established for the
synchronous `minio` client), fetches messages flagged `UNSEEN`, publishes
one `message.received` event per message, then marks each `\Seen`. IMAP's
own read-flag **is** the idempotency tracker — no separate
"last processed UID" cursor table needed, the same "let existing state do
the idempotency work" instinct the M10 outbox's `dispatched_at` and M14's
SLA breach markers already apply.

## Thread and identity resolution

- **`external_thread_id`**: email threading uses the `References`/
  `In-Reply-To` headers, not a session token like Web Chat. `receive_message`
  uses the first `Message-ID` in `References` if present (the thread's
  root), falling back to `In-Reply-To`, falling back to the message's own
  `Message-ID` (starting a new thread) — a documented heuristic, not
  perfect for every mail client's threading quirks, but standard practice.
- **Customer identity**: unlike every other channel so far, email
  resolution is **real matching**, not deferred. M8 already built
  `CustomerRepository.get_by_email` for exactly this; the conversation-
  ingest consumer's `_resolve_customer_id` (M13) gets an `"email"` branch
  that gets-or-creates a `Customer` by the sender's address — the first
  channel where "multi-channel identity resolution" (deferred since M8)
  is actually implemented, because email addresses are already a
  first-class, unambiguous `Customer` field. WhatsApp/Messenger identity
  resolution (phone numbers, platform user IDs) remains deferred to M16/
  M17, which will need their own matching strategy, not this one.

## Methods with no email equivalent

`typing_indicator`, `mark_as_read`, `edit_message`, `delete_message` are
no-ops for `EmailProvider` — email has no live-typing signal, no
universal read-receipt mechanism worth building against (`Disposition-
Notification-To` is unreliable and inconsistently honored), and no
provider-side edit/delete. Implementing the method to satisfy the
`ChannelProvider` ABC and having it do nothing is the correct outcome for
a channel that genuinely doesn't support the capability — the same
non-choice `WebChatProvider.edit_message`/`delete_message` already made.

## Schema impact

None. `channel_type="email"` is just another value in the existing plain
`varchar` column (M11 decision #7 — new channel types are a registry
addition, never a migration), and `messages`/`message_attachments` (M13)
already had every column an email needs (`external_message_id`,
`reply_to_message_id`, provider-agnostic `metadata`). Zero migrations were
added for this milestone.

## Verification performed

27 new tests added (171 → 198 passing), all green under `pytest -q`,
`ruff check`/`ruff format --check`, and `mypy src`:

- `tests/unit/test_email_provider.py` (18 tests) — MIME parsing (plain
  text, multipart-with-attachment, thread resolution via `References`/
  `In-Reply-To`/neither, auto-generated `Message-ID` when absent),
  `verify_signature`'s HMAC check (valid, invalid, no-secret-fails-closed),
  `send_message` against a mocked `aiosmtplib.send` (headers, reply
  threading, attachment upload), the no-op methods, attachment
  upload/download round-trip, and `health_check` against a mocked
  `aiosmtplib.SMTP` (healthy and unreachable).
- `tests/unit/test_email_imap_poll_task_fetch.py` (3 tests) — the
  `imaplib` fetch-and-mark-`\Seen` loop against a fake IMAP client
  (SSL and plain, and the no-unseen-messages case).
- `tests/integration/test_email_imap_poll_task.py` (3 tests) — the poll
  task's orchestration (fetch → parse → publish `message.received` onto
  the outbox) against a real `ChannelConfig`/DB session, including the
  case where a config has no IMAP credentials configured (SMTP-only).
- `tests/integration/test_conversation_ingest_consumer.py` (+3 tests) —
  the email-address customer-resolution branch: first-contact
  get-or-create, case-insensitive re-match of an existing customer on a
  second message, and skipping a message with no usable sender address.

A real SMTP/IMAP round-trip against a live mailbox (or a local test relay
such as MailHog/GreenMail) is a manual verification step, the same bar
established for MinIO/RabbitMQ elsewhere in this codebase — not
practically assertable in an automated unit/integration suite without
standing up real mail infrastructure in CI.
