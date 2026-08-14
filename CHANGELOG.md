# Changelog

This page lists every notable update to Blink Engage, newest first. We follow
a widely used style for writing changelogs called
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and we number our
releases using [Semantic Versioning](https://semver.org/), a common
version-numbering system. You can tell how ready a release is just by
looking at its version number: a plain number like `1.0.0` means a finished,
stable release; a version ending in `-beta.N` means it's a beta (out for
testing); `-rc.N` means a release candidate (almost final); and `-dev.N` or
`-alpha.N` means it's still early and under active development. See
[`docs/architecture/release-changelog.md`](docs/architecture/release-changelog.md)
for more detail on how this page is put together.

## [Unreleased]

### Added

- **Extraction now actually runs.** The 4D job pipeline and the 4E extractor
  existed side by side and never called each other, so nothing moved past
  `EXTRACTED`. The bridge is that call: a job at `EXTRACTED` runs extraction,
  drafts what survives, and advances to `PROPOSED`.

  Drafts are created **before** the job advances. A crash between the two costs
  a repeat, and the repeat finds its drafts already present and creates none;
  advancing first would leave a job claiming work that never happened, which is
  the one outcome no later phase could detect.

  Failures are classified rather than collapsed: provider errors and
  unparseable output are retryable, an all-invalid extraction and an empty
  document are terminal, and a document stating no facts still reaches
  `PROPOSED` because the work was done. No provider configured leaves the job
  exactly where it was rather than settling it with an empty extraction that
  never happened. `CrossTenantAccessError` propagates and is never converted
  into a retry — a leak recorded as "we will try again later" is a leak nobody
  investigates.

  Building it exposed a defect in the 4D state table: `EXTRACTED →
  FAILED_RETRYABLE` was missing, so every transient failure during fact
  extraction would have raised an invalid-transition error instead of settling
  the job. Fact extraction runs after the document has been read, so a provider
  timeout there is transient even though the text is already in hand. The
  transition was added; recovery re-enters through `EXTRACTING`.

- **The Brain can propose facts from a document, and can do nothing else with
  them.** Extracted document text is read by the company's configured AI
  provider (platform default as fallback) and returned as candidate facts:
  record type, subject, attributes, a **verbatim source passage**, a confidence
  tier and any effective date the document actually stated. Surviving
  candidates become DRAFT records. Nothing else.

  This is the first component that asks a model for anything, and the boundary
  it sits on is why the earlier phases were built as they were. The only write
  is `create_draft`; `publish`, `supersede` and `archive` are not called, and a
  structural test fails the build if they ever are. A DRAFT never answers a
  question, so the best outcome a poisoned document achieves is a wrong
  proposal in a review queue with its own source passage attached, waiting for
  a human who holds `knowledge_records.publish`.

  What the model is not allowed to decide: the subject key is computed by
  `canonical_subject_key()`, never taken from the answer, because a
  model-generated key is not reproducible and forks a product's history.
  Attributes naming `lifecycle_state`, `access_level`, `approved_by_user_id` or
  `company_id` are stripped — a document naming its own lifecycle is one trying
  to promote itself. An unrecognised confidence label reads as LOW, never HIGH.
  A date that will not parse is dropped rather than guessed, because an
  invented effective date silently schedules a price change. No tools are ever
  offered, so no sentence in a document can reach one.

  Failures are classified rather than collapsed: unparseable output and
  provider errors are retryable; a document whose every candidate failed
  validation is terminal; and **a document stating no facts is a success**, not
  a failure — distinguished by counting what was rejected.

- **Ingestion work is now durable, resumable and safe to run twice.** The
  inputs already survived a crash — the message and the document outlive a
  restart. What did not survive was the knowledge that work had been *started*
  and abandoned. `knowledge_ingestion_jobs` is that fact.

  Two guarantees, both enforced by the database rather than by care. One job
  per unit of work, under `UNIQUE(company_id, job_key)`, so a replay or a
  second worker finds the existing job instead of creating a rival. And every
  transition is a conditional UPDATE naming the state it expects to find: two
  workers racing to claim the same job both issue it, one matches a row and one
  matches nothing, and the loser is told rather than proceeding on a stale
  read. Without that they would both parse the same document and both write the
  result.

  The legal moves are a table, not a chain of `if`s, and an illegal move raises.
  `EXTRACTING → RECEIVED` is deliberately absent: a job whose worker died is not
  a job nobody has touched, and erasing the difference would lose the only
  signal that something is stuck. Attempts are counted on claim rather than on
  failure, because a worker that dies recording nothing has still consumed one —
  otherwise a crash loop runs forever against the same file.

  Retries are bounded and terminal failures state a reason. A parser refusal is
  terminal by construction: an encrypted PDF is encrypted on the second attempt
  too. And no job state grants authority — work completing is not approval, and
  publication remains a human act behind `publication_gate()`.

- **The Brain can now read what was attached.** PDF, DOCX, XLSX, CSV and TXT
  attachments arriving at a knowledge mailbox are extracted to text and stored
  against the company. Text only: no model sees them, and nothing becomes
  knowledge — that is a later phase.

  **The extension is a claim, not a fact.** The kind is sniffed from the
  leading bytes, so `pricing.pdf` containing a ZIP is read as the ZIP. The
  filename decides exactly one thing, CSV versus TXT, and can never promote a
  file to something it is not.

  **Refusals are the feature.** An encrypted PDF fails closed rather than being
  opened with an empty password. A PDF with pages and no text layer is refused
  as a scan rather than yielding an empty string — half-reading a price list
  fails invisibly, and "the document said nothing" is indistinguishable from
  "we could not read it". A ZIP that expands beyond its size is refused from
  its own directory listing, never unpacked. Every refusal is a row with a
  reason, because "your Q3 price list arrived and we cannot read it" is
  answerable and silence is not.

  Limits run before parsing, where they are cheap: 10 MiB per document, 300 PDF
  pages, 50 sheets, 20,000 spreadsheet rows. Spreadsheets are read with
  `data_only=True`, so a formula's cached value is read and the expression is
  never evaluated; a CSV cell beginning `=` is a string here and stays one. No
  office runtime is invoked, so a macro has nothing to execute in, and nothing
  in this path fetches a URL or a remote image.

  No OCR, deliberately. The parser is resolved by kind, so an OCR reader can
  register for the scanned case later without the pipeline changing.

- **A company can give its Brain a mailbox, and only the people it named can
  use it.** A company points `ai@theirdomain.com` at Blink and its own staff
  send price lists, policies and service descriptions to it. The mail becomes
  *source material* — durable, attributable, stored exactly once — and nothing
  else. It creates no customer, no conversation, no knowledge record and no
  reply; attachments are counted and never opened, and no model reads anything.

  **Knowledge mail is not customer mail.** `ChannelConfig` gains a `purpose`,
  and the branch happens before an inbound message is parsed at all — earlier
  than strictly required, because the customer parser uploads every attachment
  on its way through and discards the headers that authorise the sender. Every
  existing configuration is CUSTOMER_SUPPORT and behaves exactly as before. An
  unrecognised purpose routes nowhere: defaulting one way manufactures customer
  records from a price list, and the other way silently stops answering
  customers.

  **The database decides what has already been seen, not IMAP.** The poll used
  to mark each message `\Seen` as it read it and call that idempotency — so a
  crash between reading and persisting lost the message permanently, with
  nothing anywhere recording it had arrived. For a customer that costs a
  resend; for a knowledge mailbox it is a price list that silently never came.
  Now the row is written first, under a unique constraint on
  `(company_id, channel_config_id, message_id, content_hash)`, and `\Seen` is
  an optimisation applied afterwards. Two pollers racing on one message produce
  one row and one duplicate outcome — an application-level existence check
  cannot do that, because both readers see "absent" before either writes.

  **A company domain proves nothing.** Three conditions, all required: the
  address is on the company's own allowlist, which starts empty; a verifier the
  company named stamped Authentication-Results that pass; and sensitive
  knowledge will still need human approval later. A departed employee keeps
  their address, and `CEO@company.com` is the most attractive spoof target in
  the building, not the most trusted sender.

  On authentication, plainly: the header is added by whichever server ran the
  checks, and anyone can put one in mail they send. Only the header stamped by
  the `authserv-id` the company configured is read; everything else is ignored.
  With none configured there is no evidence and ingestion refuses, rather than
  inventing confidence. It performs no DNS lookup against the sender's domain —
  "the domain publishes a DMARC record" is a fact about the domain, not about
  this message.

  Refusals are rows, not silence: an unauthorised sender who tried is exactly
  what an operator needs to see. Rejected mail keeps its envelope and reason and
  loses its body, and a message carrying an obvious private key or bearer token
  is refused rather than redacted — filtering fails open and cannot be verified
  afterwards; an absent row can.

- **A company figure nobody approved no longer reaches a customer.** Phase 2
  handed the model the approved records and asked it to quote them; asking has
  an unmeasured failure rate. Given an absence signal, a model usually says "I
  don't have that on record" and occasionally says "I believe it's around 120
  JOD" — fluently, at high confidence, in the customer's own dialect. Nothing
  downstream could tell those apart. The grounding verifier can.

  It sits at the one place it can: on the generated reply, after every existing
  gate, immediately before the single autonomous `send_reply`. Not *inside*
  that call — agents send through it too, and a human's sentence is not the
  platform's to verify. After the confidence threshold rather than before, so
  it can only ever subtract from what was already permitted.

  Six outcomes, and two pairs that must never collapse. A reply whose figures
  all trace to an approved record is allowed; one quoting a figure that does
  not is blocked. Records that disagree escalate and state nothing — never the
  higher-scoring one, never an average. And "we checked and have no record" is
  kept distinct from "we could not check", because those are different
  sentences to a customer and different problems to an operator.

  **Deterministic, and deliberately narrow.** It verifies figures about
  subjects whose record type requires approval — prices, SLA terms, policy
  parameters. No keyword list, no second model. Supported figures come from the
  approved record's attributes and its subject label, so "our 500 Mbps DIA
  costs 180 JOD" passes; they are never taken from the customer's message, or
  "is it 120 JOD?" → "yes, 120 JOD" would authorise itself. Digits fold through
  Unicode, so `١٨٠` and `180.00` and `180` are one figure.

  One subtlety worth stating because it looks backwards: subject detection runs
  over *every* record, including drafts and archived ones. Whether a question is
  about a priced subject is a property of the question, not of whether an
  approved answer exists — and filtering first meant a company whose only price
  record was still a draft looked like a company that sells nothing priced, so
  the verifier never engaged. Authority is still granted in exactly one place,
  and draft, archived, out-of-period, restricted and other tenants' records all
  fail it.

  Refusals route through the existing hand-off with their own reasons on the
  timeline, so the Story says *why* rather than recording nothing. No second
  send path, no new escalation mechanism, no migration, and Autopilot's
  eligibility, thresholds and hand-off rules are untouched — the verifier can
  only withhold.

- **Autopilot now answers from the company's approved records, not just its
  prose.** `knowledge_records` shipped with lifecycle, approval, provenance and
  deterministic resolution — and nothing on the path to a customer had ever
  read it. Autopilot grounded on FAQs and article passages only, so publishing
  a price change through the API altered precisely nothing about what the
  platform told a customer.

  The Brain now resolves the structured record and hands it to Autopilot as
  grounding. Matched by **identity, not resemblance**: a subject matches when
  its key's tokens appear contiguously in the question, canonicalised through
  the same function the record was written with — so `خدمة ٥٠٠` finds the
  record stored as `خدمه-500`, and "is DIA available at 500 sites, in mbps
  terms" does not match `dia-500-mbps`. Resemblance answers "what does DIA 500
  Mbps cost?" with the 200 Mbps row at a respectable score, which is a wrong
  number delivered confidently.

  Three outcomes stay three behaviours. One record becomes an authoritative
  section the model is told to quote exactly and never paraphrase. None becomes
  an explicit absence signal — the company has nothing on record, do not recall
  a value from anywhere else — because an empty context invites the model to
  fill it. Two becomes an escalation that states no value at all.

  **Autopilot's authority is unchanged.** The Brain supplies grounding and
  nothing else: the confidence threshold, eligibility gates and hand-off logic
  are untouched, and a Brain failure degrades to ungrounded rather than costing
  a reply. One exception, deliberately: a cross-tenant row raises instead of
  degrading, because the broad handler that makes a dead database survivable
  would otherwise turn a tenant leak into a quiet "no grounding today" that
  nobody looks at. A semantic-retrieval failure also no longer discards an
  approved value — the weakest retriever should not be able to veto the
  strongest one.

  Still advisory: nothing yet *blocks* a reply that states a price while the
  absence signal is set. That is the verifier's job, and it remains deferred.

- **Company AI Brain — the foundation, and the audit that shrank it.** Every
  company gets a private Brain: what it knows, what it has observed, how it
  speaks, and what it may do. The first finding was that most of it already
  exists. Structured knowledge with lifecycle, provenance, access levels and
  deterministic Arabic-aware resolution shipped with M2A; hybrid RRF retrieval
  and tenant-isolated vector search shipped in engine stage 1; evidence-based
  memory, the nine-provider abstraction and the audited tool executor are all
  in place. Building a Brain that re-modelled any of that would have produced a
  second vocabulary for concepts that already have one.

  So the Brain is **not a new knowledge stack**. It is the orchestration layer
  the existing documents name and neither builds — the one missing piece.
  `ToolExecutor` has been production-ready since M2B with no caller but the
  endpoint a human uses to confirm an action it parked, and
  `AutopilotService` grounds on articles and FAQs while the authoritative
  structured store that exists to answer exactly those questions has no path to
  a customer reply.

  This phase adds contracts and the guards that hold them, with no pipeline, no
  UI and no migration: Brain vocabulary and audiences, a request type whose
  `company_id` has no default so tenant scope is a signature rather than a
  filter somebody remembers, `publication_gate()`, conflict detection as pure
  functions, the retrieval visibility boundary, the ingestion boundary and its
  durable identity, the admin-assistant proposal contract, response strategy,
  and the de-escalation policy.

  **De-escalation is a function, not prompt text.** "Do not mirror abuse" is a
  brand guarantee, and a prompt directive has an unmeasured failure rate — the
  same argument this codebase already makes about grounding prices. Language
  and register are mirrored; hostility is not, and `mirror_hostility` is typed
  `Literal[False]` so enabling it fails the type check.

  **The Brain advises; it does not send.** `AutopilotService` remains the only
  autonomous path to a customer, unchanged, and a static guard fails the build
  if anything under the Brain acquires a channel provider, a connector or a
  send function. Better grounding constrains what may be said; it does not
  widen permission.

  One deliberate deviation from the brief is recorded in the tests rather than
  buried: SUPERSEDED knowledge stays resolvable. Publishing a price change
  effective next month supersedes today's record immediately while the
  replacement does not yet cover today, so excluding superseded rows would
  leave a subject unpriced for a month because somebody scheduled a change
  correctly. The property actually wanted — stale knowledge must never answer
  as current — is guaranteed by the effective period, and that is what the
  guard asserts, for every lifecycle state including ACTIVE.

  See [`docs/architecture/company-ai-brain.md`](docs/architecture/company-ai-brain.md)
  for the audit, the five real gaps it found, and the phase order.

- **`scripts/seed_company_faqs_from_profile.py` — publish a company's
  FAQ set from the facts it has already verified.** A company that fills
  in its business profile but publishes no FAQs is still answered
  narrowly by Autopilot: the profile reaches the prompt, but a customer
  who phrases the question differently, or asks in another language,
  matches nothing and is handed to a human for a fact the platform holds.

  The script writes only what the company's own
  ``settings.business_profile`` and ``settings.business_hours`` support,
  and skips any FAQ whose field is absent rather than filling it with a
  plausible value. It states hours only when every open day shares one
  open/close pair — a company with per-day hours gets no sentence rather
  than a wrong one, and the structured schedule stays the source of truth.

  **It seeds Arabic alongside English**, restating the same verified
  fields. Not decoration: retrieval is hybrid, and with no embedding
  provider configured it degrades to lexical matching, at which point an
  Arabic question cannot match English text at all. A company whose
  customers write in Arabic would otherwise get a handoff for every
  question it demonstrably has the answer to.

  Dry run by default, idempotent, and it never overwrites an existing
  answer — a human may have edited it, and this content is a starting
  point rather than a source of truth.

- **Business profile: what AI Autopilot is allowed to say about the
  company.** A new ``business_profile`` section on company settings
  holding the facts customers ask for by name — trading name, location,
  contact details, website, a short description — settable through
  ``PATCH /company`` and injected into every Autopilot reply prompt.

  Deliberately not columns on ``companies``. ``Company.name`` is a tenant
  label chosen at signup and is not necessarily the name a customer
  should be told, and what the AI may state about a business is editable
  content rather than part of the tenancy record. No migration: settings
  is already a schemaless JSON blob for exactly this reason.

  **Opening hours are not part of it**, and that omission is the design.
  A structured weekly schedule already exists under ``business_hours``,
  and a second free-text field for the same fact would let the AI quote
  one while the SLA engine honours the other. The hours line is derived
  from the existing schedule — reading the *raw stored* days rather than
  ``resolve_schedule``, because that helper fills unconfigured days with
  a 09:00–17:00 default so an SLA clock always has something to
  calculate against. Reasonable there, catastrophic here: it would have
  the AI announce a full Monday-to-Friday 9-to-5 week to a company that
  never configured hours at all.

  **Settings → Business Profile** is the screen for it, placed directly
  before Business Hours because the two together are the whole of what
  Autopilot may say about a company. Blank fields are dropped on save
  rather than stored as empty strings — the same rule as the reader, for
  the same reason. The panel states plainly that anything left blank will
  be handed to a human rather than guessed, and points at the Business
  Hours tab for hours. English and Arabic.

  A cleared field is sent as an explicit `null`, never omitted. Company
  settings merge one level deep, so an omitted field keeps whatever was
  stored — which would have made *clearing* impossible: an administrator
  could delete the address, be told it saved, and have AI carry on
  quoting the old one. The backend reader drops non-string values, so a
  nulled field is absent from the prompt, which is the state a blank is
  meant to produce.

- **Structured knowledge: the prices a company looks up rather than
  searches for.** The first build phase of the M2 architecture below. A
  price, an SLA term or a product attribute is now a typed record with an
  effective period, a version chain and a named approver — not a paragraph
  somebody hopes the search finds.

  The reason it is not a knowledge article is the failure it prevents.
  "What does DIA 500 Mbps cost?" answered by similarity is a lookup
  answered by resemblance, and resemblance returns the 200 Mbps row with a
  respectable score. So a lookup that finds no current record answers *we
  don't have a current price for that* and stops. It never falls back to
  the nearest-looking passage, because that fallback is exactly how last
  year's price gets quoted this year.

  Records are found by a canonical key derived from the product's name by
  a fixed rule — never by a model, because a key that came out differently
  on two runs would fork one product's history into two chains nothing
  joins back together. The rule folds the things that are the same
  product: `DIA/500 Mbps` and `dia 500 mbps`, `الخدمة` and `الخدمه`,
  `٥٠٠` and `500`. Arabic-Indic digits needed handling of their own —
  Unicode normalisation leaves them alone, so without it a price typed on
  an Arabic keyboard was a different product from the same price typed on
  a Latin one.

  **Nothing is ever deleted.** Withdrawing is archiving and replacing is
  superseding, and both keep the row, because a price that was quoted has
  to be reproducible in an audit two years later. Superseding closes the
  old period at the exact instant the new one opens — no moment where both
  are true, none where neither is — and both halves happen in one
  transaction, since a half-applied replacement leaves two current prices,
  which is the thing the design exists to prevent. Two prices covering one
  instant is reported as a contradiction rather than resolved by picking
  one.

  A scheduled price rise does not blank out today's price while it waits,
  which sounds obvious and was not: superseding marks the current record
  replaced immediately, so a change dated next month would have left the
  product unpriced for a month. Found by a test, fixed in the resolution
  rule.

  Publishing requires provenance — an approved price whose origin nobody
  recorded is a number that cannot be defended when somebody asks. Drafting
  does not, because demanding a source before somebody has finished
  pushes them toward inventing one. Reading, drafting and publishing are
  three separate permissions: an agent reads prices all day, and making a
  price official is not the same authority as proposing one.

- **The M2 architecture: company knowledge, and how the platform sounds.**
  Design only — no behaviour changes, no schema, no data. A companion to
  the Company Intelligence Engine covering the two things that document
  does not: knowledge that must be looked up rather than resembled, and
  the voice a company answers in.

  The audit that preceded it is most of the value. Nearly everything the
  brief asked for already existed or was already designed — provenance and
  confidence on `memory_facts`, hybrid retrieval, tenant-isolated vector
  search verified at zero cross-tenant rows, the AI tool pipeline, and
  inbound email with attachment extraction. Company DNA already split
  brand voice into constraints that are enforced and characteristics that
  are asked for, and had already worked out that Arabic register does not
  map onto English formality. Writing those again would have produced a
  second vocabulary for the same concepts, so the document names what
  exists and adds only what does not.

  What is genuinely new is **structured knowledge**: a price is not a
  passage, and a question about one answered by semantic similarity
  returns the 200 Mbps row with a respectable score. Records are typed,
  carry an effective period and a version chain, and resolve by a
  canonical key computed deterministically — Unicode-normalised, with
  Arabic orthographic folding, so `الخدمة` and `الخدمه` are one product
  and `٥٠٠` is `500`. No model generates that key: a key that changes
  between runs silently forks a product's history in two.

  Three rules the rest of the design hangs from. A structured lookup that
  finds nothing **never falls back to semantic search**, because that
  fallback is exactly how an expired price gets quoted a year later. Two
  overlapping active prices is a contradiction the platform surfaces
  rather than resolves, because picking the better-scoring one turns a
  data problem into a quotation. And there is no delete anywhere in the
  design — archive, deprecate, supersede — because a price that was quoted
  must be reproducible in an audit two years later.

  A trusted sender does not mean auto-publish. Pricing, SLA, billing,
  legal and security knowledge always require human review before
  publication, whatever the sender and whatever the extraction confidence:
  a trusted sender is a statement about a mailbox, and mailboxes are
  compromised.

  Dialect adaptation ships behind a flag defaulting to off. Language
  matching, tone and company voice all stay on; what waits is guessing
  which Arabic someone speaks. Four safety properties can be asserted in
  tests — language is matched, dialect only above confidence, toxicity is
  never mirrored, the classification is never leaked — but dialect
  *quality* cannot be, and no automated result will be reported as
  verifying it. That needs a held-out corpus graded by native speakers of
  each dialect, and until it exists the honest default is neutral
  language: a badly-produced dialect reads as mockery.

- **AI tool calling: the foundation an AI administrator will stand on.**
  Not the administrator itself — nothing conversational ships here, and
  nothing calls this in production yet. What ships is the machinery any
  such feature must go through, built first and on its own so it could be
  reviewed on its own.

  An AI that can *change* a workspace is a different proposition from one
  that suggests replies. A wrong suggestion is ignored; a wrong mutation
  moves an agent out of a department or changes who can see billing. Two
  assumptions shape everything: the model is untrusted input — it may be
  confused, or steered by text a customer wrote into a conversation it
  later reads — and a system prompt is a preference, not a control.

  So every AI-initiated change passes one pipeline: registry allowlist →
  strict schema validation → the authenticated user's identity → tenant
  scope → permission check → confirmation policy → an existing
  application service → audit. Handlers get four named services and
  nothing else: no session, no repository, no lookup-by-name. A handler
  that wanted to issue its own SQL has no expression available to do it
  in.

  **There are no destructive tools, and that is structural.** None is
  registered, and the registry refuses to register a name containing
  `delete`, `remove`, `purge`, `drop`, `reset` or `truncate` — so the
  guarantee covers the delete tool nobody has thought of yet. The model
  also cannot supply its own identity: `company_id`, `user_id` and
  `permission` are refused as argument *names* at registration, which is
  why a tool acting on somebody else says `target_agent_id`.

  **High-impact actions park rather than run.** A role change is
  validated, priced as a before/after diff, and written to
  `pending_ai_actions`; approval is an authenticated request consuming
  that row exactly once. Confirming re-checks everything — permissions
  may have changed, and so may the entity — and refuses if the workspace
  moved underneath the diff the human read. Bulk escalates automatically:
  any list argument over five items needs a human whatever the tool says.

  Tool calling is implemented for OpenAI and Claude. The other six
  providers refuse explicitly; there is no fallback that prompts a model
  for JSON and parses the reply, because that puts a guesser in front of
  a mutation pipeline. `complete()` and the twelve existing AI
  capabilities are untouched.

  See [`docs/architecture/ai-tool-calling.md`](docs/architecture/ai-tool-calling.md).

- **A record of what the AI did, and why.** `ai_action_logs` sits
  alongside the existing audit trail rather than replacing it: tools run
  through ordinary services, so the usual domain event is audited as
  always. What the new table adds is what only matters when a machine
  acted — the before and after state, the sentence the user actually
  typed, and which model turned one into the other. Refusals are recorded
  too; a model repeatedly attempting something it may not do is the
  pattern worth being able to find.

  Secrets cannot reach it. Secret-shaped argument names are refused at
  registration, so the declared schema *is* the allowlist — the failure
  mode of a denylist is that the new credential is the one nobody
  remembered to add.

- **Safe retries when a reply is sent over a bad connection.** Sending a
  message accepts an `Idempotency-Key` header. Present the same key again
  and the original reply comes back rather than a second one being sent.

  The problem is specific to phones and unavoidable without this: an agent
  sends a reply, the connection drops before the confirmation arrives, and
  neither the app nor the person holding it can tell whether the customer
  received it. Retrying risks the customer seeing the same reply twice;
  not retrying risks it never arriving. Neither is acceptable, so the
  server now takes responsibility for the ambiguity.

  A key is scoped to one conversation, so reusing one elsewhere cannot
  replay a reply into the wrong thread. Reusing a key with different
  wording is refused outright rather than quietly answered with the first
  message — returning a plausible response to a request that was never
  performed is the failure this exists to prevent, not a form of it.
  Replayable for 24 hours.

- **Delta sync on the conversation list.** `?updated_since=` returns only
  what has changed. A client returning after hours offline previously had
  to re-page the entire Inbox to discover what it had missed — the
  slowest request, on the worst connection, at the exact moment somebody
  is waiting to start work.

  A conversation deleted while a client was away is absent from the delta
  rather than reported as removed; there is no tombstone feed, and a
  client that must not display deleted conversations still needs a
  periodic full reconcile.

- **Cursor pagination on the conversation and message lists** — the two
  that are read while they are being written. `?cursor=` returns a
  `next_cursor` to follow; `page`/`page_size` are untouched and behave
  exactly as before.

  Offset paging asks "skip the first N rows", and N means something
  different by the time the next page is requested. The duplicate that
  causes is recoverable — a client keying by id drops it. The row that
  appears on *no* page is not, and on the conversation list that row is
  somebody's unanswered customer.

  Cursor mode orders conversations most-recently-active first rather than
  worst-SLA-health first, and that is a limit rather than a preference:
  health is computed from the clocks at query time, so a keyset over it
  would point at a position that no longer exists. The health-ordered
  Inbox stays offset-paged.

- **The real-time contract is written down** —
  [`docs/architecture/realtime.md`](docs/architecture/realtime.md). Every
  frame type, the presence model, and what a client must do on reconnect.
  FastAPI does not document WebSocket routes, so the platform's real-time
  support was invisible to anyone reading the generated OpenAPI schema,
  and had been concluded absent more than once.

- **Server migration tooling** — `scripts/migrate_export.sh`,
  `scripts/migrate_import.sh` and
  [`docs/deployment/server-migration-runbook.md`](docs/deployment/server-migration-runbook.md).
  `backup_all.sh` captures what is needed to rebuild the *product* —
  database, objects, config, secrets, source. Moving a *deployment* is a
  larger job: the Prometheus TSDB, Grafana's own users and annotations,
  Loki's history and the TLS material are none of them in a backup set,
  and all of them are things somebody notices the loss of the morning
  after a cutover. The export wraps `backup_all.sh` and adds them.

  Two passes, because the alternative is a long outage: `--warm` moves the
  bulk against a live stack, `--cold` quiesces first and is the
  authoritative one. The cold pass stops the stateful services *before*
  archiving their volumes — Grafana's SQLite and Prometheus's TSDB cannot
  be tarred safely while being written, and a torn copy fails at open
  rather than at restore, which is the wrong end of a migration to find
  out. Redis is deliberately excluded: it holds refresh tokens, web-chat
  sessions, presence and rate-limit counters, all reconstructible, and a
  fresh volume costs one re-login.

- **TLS renewal is now reproducible from a clean checkout** —
  `deploy/letsencrypt/`. Two pieces of certificate renewal previously
  existed only on the host that issued the certificate and were in no
  repository: the deploy hook that reloads nginx after a renewal, and the
  webroot recorded in the renewal configuration.

  Neither absence is visible when it happens. Without the hook, renewal
  succeeds and nginx carries on presenting the certificate it read at
  startup until that one expires. Without the right webroot — certbot
  stores it as an absolute path at issuance — renewal writes its challenge
  somewhere nginx does not serve, and fails quietly for up to 90 days.
  `install.sh` derives both from wherever the checkout actually is, and
  corrects a renewal configuration migrated from another host rather than
  leaving it to fail.

  The challenge webroot itself (`docker/nginx/acme/`) is now part of the
  repository. Compose bind-mounts it, so Docker would otherwise create it
  implicitly on first `up` — which works, and hides that a load-bearing
  path is not version controlled.

### Changed

- **Locking your phone no longer takes you out of routing.** Closing the
  last agent WebSocket now starts a grace period (90 seconds by default)
  instead of marking the agent offline immediately; reconnecting inside it
  cancels the transition entirely.

  The old behaviour was correct for a browser tab and wrong for everything
  else. A phone closes its socket every time the screen locks, so an agent
  working from one was dropped from assignment several times an hour and
  put back only when they next happened to open the app.

  The same change fixes a defect that predates any mobile client: closing
  one of two open tabs used to mark an agent offline while they were still
  sitting in front of the other. Presence is now derived from how many
  connections an agent holds, not from the most recent one to close.

  Configurable via `PRESENCE_OFFLINE_GRACE_SECONDS`. A new sweep,
  `blinkengage.agents.sweep_presence_offline`, performs the transition
  every 30 seconds.

- The Mobile Integration Guide's gap audit is updated: four of its six
  recorded gaps are now closed. What remains is no APNs sender (iOS goes
  through Firebase) and no aggregate conversation endpoint.

- **The production overlay now asserts the production posture instead of
  inheriting it.** `docker-compose.prod.yml` previously left
  `ENVIRONMENT` and `DEBUG` to the base file's
  `${ENVIRONMENT:-development}` / `${DEBUG:-true}` defaults, so a host
  whose `.env` was missing, partial, or copied from a developer's machine
  came up in development mode — returning tracebacks to unauthenticated
  callers on error. Both are now set in the overlay on all fifteen
  application services, making the posture a property of the file you
  deploy with rather than of a file deliberately kept out of version
  control.

  **Published ports are bound to loopback.** The base file publishes the
  backend (8000), Grafana (3000) and Prometheus (9090) on `0.0.0.0` for
  local development, and the overlay did not override them — putting the
  API beside nginx on the public internet, bypassing the edge that
  terminates TLS and applies rate limiting, and exposing an entirely
  unauthenticated Prometheus whose `/api/v1/query` answers anyone who
  asks. Production now publishes nginx's 80 and 443 and nothing else.

  A host firewall would not have closed these: Docker inserts its rules
  into the `DOCKER` chain, which iptables traverses before the `INPUT`
  chain ufw manages, so `ufw deny 3000` leaves a published port reachable.
  The binding is the control; verify with `ss -tulpn`, not `ufw status`.

  **Application images carry an explicit production tag.** All fifteen
  services building from `docker/backend/Dockerfile` now resolve to
  `blinkengage-backend:prod`. The `dev` and `runtime` targets previously
  produced the same derived `:latest` name, so the tag alone could not
  tell you which you had — and starting production from a dev image is
  exactly the failure recorded in the edge-cutover runbook.

  **GreenMail is excluded by profile rather than scaled to zero.** Both
  stop the container starting, but `replicas: 0` left the service in the
  resolved configuration still carrying its `0.0.0.0` port publications,
  so auditing what production exposes meant reasoning about whether a
  scaled-to-zero service can bind a port. Under a profile there is nothing
  to reason about.

### Fixed

- **Request metrics were wrong whenever more than one worker was
  running, and the 5xx alert cried wolf on a healthy backend.** Two
  defects that fed each other, both found while verifying the v1.2.0
  deployment.

  Production runs `uvicorn --workers 4`, and `prometheus_client` keeps
  counters in each process's own memory. `/metrics` is answered by
  whichever worker the connection reaches, so a scrape returned one
  worker's quarter of the traffic: eight consecutive scrapes of an idle
  backend read 51, 40, 51, 40, 51, 12, 51, 51 for the same counter.
  Nothing errors — the series simply moves backwards, which `rate()`
  reads as a counter reset and compensates for by adding the value again.
  Every rate built on those series was wrong in both directions at once,
  and a 5xx recorded on one worker was invisible to a scrape answered by
  another. The backend now runs in `prometheus_client`'s multiprocess
  mode: workers write to shared memory-mapped files and exposition sums
  them. The directory is emptied once by the entrypoint before the
  workers start, because the files are keyed by pid and pids are
  recycled — files surviving a restart are read as live workers, and a
  rate spanning the restart would be fabricated.

  `/metrics` is now mounted directly rather than by
  `Instrumentator.expose()`. In multiprocess mode the exposition registry
  is assembled fresh from the workers' files, and `expose()` has no way
  to be told about a collector that lives in memory — so the outbox and
  scheduler gauges would have disappeared, taking the two alerts that
  read them with them. Both are silent-failure alerts, so the symptom
  would have been coverage that looked intact and could not fire.

  **The 5xx rule reported DatasourceNoData critical whenever the backend
  was healthy.** `sum()` over a selector matching no series returns an
  empty vector rather than zero, and arithmetic on an empty vector is
  empty — so a backend serving thousands of requests with no errors at
  all produced no data, which Grafana escalates to critical. It fired
  that way after every deploy, because a restart resets the counters and
  no worker has served a 5xx yet. The rule now falls back to 0 and gates
  on a minimum request rate, so a ratio is only computed where a ratio
  means something. The 5% threshold and the 5-minute `for` are unchanged.

  **Absence became two alerts of its own.** The old rule answered "are
  there errors", "is anything being scraped" and "do the series exist"
  with one number and one severity, so a healthy idle backend, a dead
  backend and a broken exporter were indistinguishable. `Backend is not
  answering Prometheus` (critical) now owns scrape failure, and `Backend
  request metrics are missing` (warning) owns the case `up` cannot see —
  the scrape succeeds and the counters are simply not in the payload,
  which is exactly what the worker defect above produced. The ratio rule
  answers only what share of traffic is failing.

  Both `or vector(0)` fallbacks aggregate before the `or`, for the reason
  recorded against `blinkengage-nginx-down`: `or` returns right-hand
  samples for label sets absent on the left, and `vector(0)` carries no
  labels, so against a labelled selector it adds a permanent extra series
  instead of substituting for one. `tests/unit/test_alert_rules.py` now
  enforces that shape across every rule in the file.

- **Read-only platform operators were refused the three previews that
  exist for them.** Pricing resolve, pricing quote and the credit-note
  preview are POSTs that write nothing, and the read-only gate allowlists
  them by name. It matched on `request.scope["route"].path` against
  absolute templates — correct until FastAPI 0.141 changed
  `include_router` to nest routers rather than flatten their routes into
  the application. After that, `route.path` is the path a route was
  registered with, relative to its own router, so the comparison could
  never match and every allowlisted preview was refused.

  The gate now matches on the **endpoint function** rather than on any
  form of the URL. A function identity cannot be crafted from a request
  path and does not move when a router is remounted, so this keeps the
  property the old implementation claimed — "an id in the path can never
  be crafted to look like an allowlisted route" — without depending on
  how paths are assembled.

  It failed closed, which is the right direction to fail and also why it
  was invisible from outside: a silent denial is indistinguishable from a
  working permission check. `verify_read_only_allowlist` now runs at
  start-up and refuses to boot if an allowlisted endpoint resolves to no
  route, so the next routing change is a crash rather than a permission
  that quietly stopped being granted.

- **A security sweep over every mutating platform route was grading
  nothing and passing.** `test_a_read_only_operator_is_refused_all_of_them`
  walks each mutating `/api/v1/platform` route and asserts a read-only
  operator is refused. It discovered routes by walking `app.routes`, which
  the same FastAPI change emptied of those routes — so it iterated zero of
  them and passed. Its companion guard, written for exactly this
  ("a discovery test that discovers nothing passes silently forever"), is
  what caught it.

  Route discovery now reads the OpenAPI schema: public API, absolute
  templates, and the same source the published schema comes from.

- **The Autopilot start-up guard did not check the grounding it was given.**
  `critical_services()` names the collaborators whose absence must stop
  the AI queue worker booting. Knowledge and FAQ retrieval were wired into
  `AutopilotService` without being named there, and the repository's own
  test for that omission was failing: *"AutopilotService has optional
  collaborators the start-up guard does not check: ['faqs', 'knowledge']."*

  Ungrounded is the quietest way for Autopilot to be wrong. It keeps
  answering, fluently, using none of the company's approved wording, and
  looks exactly like a company that has published nothing.

- **"Pick up" was offered on conversations that had already been dealt
  with, and failed when clicked.** The Inbox decided a conversation was
  free to claim by asking whether anybody was on it. A resolved or closed
  conversation has no assigned agent and keeps its queue for reporting, so
  it answered yes — the row and the conversation header both showed a
  green Pick up, and pressing it produced "Could not pick up this
  conversation." The server had always been right; only the interface
  disagreed. Both screens now share one rule that mirrors it, so they
  cannot drift apart again.

- **A finished conversation reported its owner as "Nobody" and its wait
  as "—".** Neither is a fact about a conversation that is over. It now
  says when it finished instead.

- **The Inbox printed a raw queue id where the queue name belongs** —
  `queue 3842287b-9dfe-4b12-949f-08d5c6c89aea` on the row that should
  have read `General`. The queue's name is denormalised onto the
  ownership record when ownership is taken, and for queue owners it was
  not always captured; the label then fell through to a debug string. The
  Inbox query now resolves the name, the way the Conversation Inspector
  already did for the same fall-through.

- **AI Autopilot invented facts about the company it works for.** Asked
  in Arabic for the company's name and address, it replied with the
  bracketed placeholders ``[اسم الشركة]`` and ``[عنوان الموقع]``. Asked
  its opening hours and what it sells, it invented both — "9 صباحًا حتى 5
  مساءً", and a product range of clothing, electronics and homeware that
  nobody had ever told it about. Every one of those was auto-sent to a
  customer, because Autopilot has no human reviewing its replies.

  The prompt had said *"using only information present in the
  conversation history"* and was then handed nothing but the transcript.
  So a customer asking the company's name was asking for something the
  model had no way to know and no instruction to decline — and a model
  with a reply to compose and a missing fact composes around it. The
  brackets were never an unsubstituted template; they are what a model
  writes when it is holding a sentence open for a fact it does not have.

  Three changes, because none of them is sufficient alone:

  **The model is now told what it knows.** The company's business profile
  and, for each inbound message, retrieval against its own Knowledge Base
  and FAQs are passed into the prompt — the same hybrid retrieval,
  approved-answers-before-reference-material ordering, and published-only
  corpus that ``/ai/knowledge-search`` already used. Autopilot had never
  called it. Two retrieval systems existed side by side and the
  autonomous one used neither.

  **The refusal rule is unconditional.** Retrieval alone would not have
  fixed this: a knowledge base can be empty, or simply not contain the
  answer, and the failure being prevented is precisely what the model
  does when a fact is *absent*. The prompt now states, whether or not
  anything was retrieved, that the facts given are the complete set, that
  guessing a business fact is forbidden, that a placeholder is never an
  acceptable output, and that a question it was not given the answer to
  is a handoff rather than an attempt.

  **A placeholder in a reply now forces a handoff mechanically**,
  whatever confidence the model scored itself. A prompt rule is a strong
  tendency, not a guarantee, and this is the one failure mode that
  reaches a customer looking like a finished answer — ``اسم الشركة هو
  [اسم الشركة]`` is fluent, well-formed, confidently self-scored and
  worthless. The check distinguishes a placeholder, which names a
  concept, from a genuine reference like ``[#12345]`` or ``[REF-2024]``,
  which carries a number; holding back real replies would have traded
  this bug for a quieter one.

  Retrieval failure degrades to a handoff rather than an error: an
  embedding provider that is down leaves the model with the profile
  alone, still forbidden from inventing beyond it. The grounded and
  ungrounded prompts differ in what they contain, never in what they
  permit.

- **The CSAT survey link was not clickable.** The message put the URL on
  the same line as the sentence introducing it, immediately after a
  colon. Channel clients — WhatsApp, Messenger, SMS — autolink by finding
  a URL and extending to the next whitespace, so a link sharing a line
  with prose is routinely detected short or not detected at all, and the
  customer is left with a long string they cannot tap. The URL now sits
  alone on its own line, with nothing before or after it, which is the
  one form every channel linkifies identically.

  Worth separating from the deployment problem found alongside it: the
  links customers received also pointed at a bare IP rather than the
  configured domain. That was not this template, and not
  `CsatService.build_survey_url`, both of which were correct. Eleven
  consumer containers were still running with a `PUBLIC_BASE_URL` from
  before the domain was set, because Compose reads the environment when
  a container is created and editing `.env` does not reach a container
  already running. Recreating them fixed it. The survey links already
  sent keep the IP until they expire — a token is signed over the
  conversation, not the host, so they still work, but they will show a
  certificate warning.

- **The conversation list had no index for "changed since".** Not a
  regression — the column was never queried before — but the Mobile
  Integration Guide recorded delta sync as needing no migration on the
  grounds that `conversations.updated_at` was already indexed, and it was
  not. Every index on the table covered `last_message_at`, a lifecycle
  column, or the channel thread. Migration `c7d1e4b93a58` adds
  `ix_conversations_company_updated_at`; the guide's §8.1 has been
  corrected rather than quietly amended.

### Security

- **An unauthenticated request now answers 401 rather than 403.** FastAPI's
  `HTTPBearer` refuses a request carrying no `Authorization` header with
  401 as of 0.141, where it previously used 403. This is the distinction
  RFC 9110 draws and the platform now makes it: **401** means "you sent no
  credentials", **403** means "you sent credentials and they are not
  enough". A tenant reaching a `/platform/*` route still gets 403.

  Recorded here as a **contract change**, not a bug fix. It has been the
  live behaviour since the dependency upgrade was built into the running
  image; only the test suite still described the old shape. Any client
  that treats 403 as "not logged in", or that triggers a token refresh on
  401, should be checked against the new split — an anonymous request now
  produces the same status as an expired token.

- **The starlette advisories are closed, and the pins that close them are
  now in the tree.** `HTTP_422_UNPROCESSABLE_ENTITY` was renamed to
  `HTTP_422_UNPROCESSABLE_CONTENT` across nine call sites in an earlier
  commit, but the dependency pins that rename depends on were left in the
  working tree — so the committed source used a constant the pinned
  starlette did not define, and a clean build from that commit would have
  failed at import. Both halves now land together.

  `starlette>=1.3.1` is pinned explicitly, above what FastAPI's own floor
  would pull in. The version that resolved carried three advisories
  needing three different fixed versions — CVE-2025-62727 (denial of
  service via Range header merging, 0.49.1), CVE-2026-48818 (SSRF/NTLM via
  UNC paths in `StaticFiles`, 1.1.0) and CVE-2026-54283
  (`request.form()` limits silently ignored, 1.3.1) — and only `>=1.3.1`
  closes all three. FastAPI could not reach it until it dropped its upper
  bound on starlette, so `fastapi` moves to 0.141.1.

  `prometheus-fastapi-instrumentator` moves to 8.1.0 because 7.0.2 pinned
  `starlette<1.0.0`. A transitive cap in an instrumentation library was
  the actual thing holding the API framework below its own security fixes,
  which is worth recording: the blocker was not the framework.

  `msgpack>=1.2.1` is pinned directly, though it arrives transitively via
  kombu/celery, because the version that resolved (1.1.2) is
  GHSA-6v7p-g79w-8964 — an out-of-bounds read when an `Unpacker` is
  reused.

- **The production image no longer ships a package installer.** The
  `runtime` stage receives an already-built virtualenv and never installs
  anything, so `pip` in a production container is only attack surface. It
  is also what the image scan was reporting: pip *vendors* its own
  dependencies, pinning `msgpack==1.1.2` and `setuptools==70.3.0` in
  `pip/_vendor/vendor.txt`, and Trivy reads those as installed packages.
  They were never the application's — no change to our own pins could have
  cleared those findings, which is worth knowing before somebody spends an
  afternoon trying.

  `setuptools` in the interpreter's system site-packages is upgraded past
  CVE-2025-47273 (path traversal in `PackageIndex`); `python:3.13-slim`
  carried 70.3.0. Nothing at runtime imports it — the application runs from
  `/opt/venv` — but "unused" is not a property a scanner can verify.

  Both changes are image composition only. The application never imports
  `pip`, `setuptools` or `pkg_resources`; the one runtime dependency that
  references `pkg_resources` (`aiormq`) does so in an `except ImportError`
  fallback behind stdlib `importlib.metadata`, and `pkg_resources` remains
  present regardless — only `pip` is removed, and only from the `runtime`
  stage.

## [1.2.0] - 2026-08-08

### Added

- **Message redaction.** Removing what a single message said, keeping
  that it was said. A message sent over WhatsApp or email cannot be
  unsent — the customer keeps their copy — so deleting ours would
  destroy our half of a record they can still produce. The message stays
  in the thread, in order, marked redacted, with a permanent record of
  who removed it and why.

  It removes the text, the copy the channel provider stored alongside
  it, any attached files from object storage, and every citation of the
  message in Memory and Learning. Future analysis excludes it at source,
  so a redacted message can never become evidence for anything.
  Administrators and the Owner; never agents, because a redaction cannot
  be undone by whoever notices the mistake a minute later.

  New permission `messages.redact`. `conversations.delete` is untouched
  and remains Owner-only.

### Changed

- **Production configuration now refuses to start when it is unsafe.**
  Every default in the platform is chosen so a laptop works with no
  configuration, which is right for a laptop and wrong for anything
  holding customer data. A production deployment inheriting `DEBUG=true`
  or MinIO's published `minioadmin` credentials used to come up green
  and serve traffic. It now fails at startup, listing every problem at
  once rather than one per restart.

- **Every third-party container image is pinned to a content digest.**
  `:latest` meant a `docker compose pull` could change MinIO, Prometheus
  or Grafana underneath a deployed release. Pinned to the versions
  already running; nothing was upgraded.

- **nginx and the monitoring stack are now monitored.** The edge — which
  every customer request passes through — had no scrape target and no
  alert, so its failure was indistinguishable from a total outage and
  nothing would have paged. Grafana and Loki are watched too, and an
  always-firing heartbeat makes the alerting path itself observable:
  if it stops arriving, alerting is broken, whatever the dashboards say.

### Fixed

- **The CI vulnerability scan had stopped running at all.** It pinned an
  action version upstream deleted when it re-tagged its releases, so the
  job failed while setting itself up — before scanning anything. A scan
  that never starts looks the same in the run list as a scan that found
  nothing. Repinned; every other action reference was checked too.

- **`PAYPAL_ENVIRONMENT` was advertised and read by nothing.** Setting it
  to `live` left the platform in sandbox — healthy, and taking no real
  money. The switch is `PAYPAL_SANDBOX`, which is now what the example
  file documents. A test refuses any future variable that nothing reads.

- **A scheduled task had not run for three days** and nothing but the
  staleness alert noticed. The worker process predated the code that
  registers it: Celery builds its task registry once, at start, so a
  deploy that does not recreate the worker silently loses every
  scheduled task added since. Documented in the deployment guide with a
  command to confirm it.

- **156 MB pgvector index on a table with no rows.** HNSW indexes do not
  return their pages on delete; rebuilt to 16 kB.

- **The new nginx exporter shipped without production hardening** — no
  memory limit, no log rotation, no healthcheck. Caught by the existing
  overlay-completeness test, which is exactly the kind of thing that
  test exists for.

- **Deleting a conversation now takes two people.** Until now one
  person could remove a conversation on their own, quietly, with no
  reason recorded and nothing to consult afterwards — and only the
  company Owner could do it at all, so in practice nobody could.

  A conversation is the record of what your company said to a customer:
  evidence in a dispute, an input to every report, and in some
  industries something you are obliged to keep. So an agent now **asks**,
  and an administrator decides.

  **Asking** is a bin icon on the conversation and a sentence explaining
  why. Nothing is deleted at that point, and the dialog says so. Once a
  request is open, everybody who opens that conversation sees who asked
  and why — a colleague about to write a long reply should know it may
  be on its way out, and nobody should ask twice.

  **Deciding** is a new **Deletion requests** queue under Work, visible
  only to people who can actually decide. Approving deletes the
  conversation there and then. Rejecting keeps it and requires a note,
  because the person who asked only ever sees what you write.

  **Nobody decides their own request.** Not because it would be unsafe —
  anybody who can approve can already delete outright — but because an
  approval showing one name on both halves is not an approval. An
  administrator who does not want a second opinion can still delete
  directly, and the record will show that is what they did.

  **The record outlives the conversation.** Long after the messages are
  gone, it still shows the customer's name, the reason, who asked, who
  agreed and when. A deletion nobody can account for later is
  indistinguishable from a mistake.

  Administrators are told the moment a request arrives; whoever asked is
  told the outcome. Nobody has to go looking.

  New permission: `conversations.delete_request`, held by every agent.
  `conversations.delete` — which decides, and still deletes directly —
  now belongs to Administrators as well as Owners, since the tenant
  administrator is exactly who a request is addressed to.

- **The Inbox is one screen now, not two.** Opening a conversation used
  to replace the whole page. An agent working through a queue went list →
  conversation → Back → list → conversation, losing their place in the
  list every single time and paying a page load for each one — and the
  queue they had deliberately chosen did not survive the round trip
  either.

  The list and the conversation are now side by side. Your place in the
  list is kept, the row you are reading is marked, and a link to a
  single conversation still opens that conversation — the list simply
  comes with it. On a phone there is not room for both, so you get one at
  a time and a back arrow, which is the only place the old behaviour was
  ever right.

  **Everything you need before replying is now on screen.** Who the
  customer is, what the conversation is waiting on, whether it has missed
  a target, who owns it, which queue it is in — and, the part that was
  missing entirely, **how long**. Waiting, since the last message, since
  it opened, and since the customer first got an answer. Those figures
  keep counting while you watch them, because a duration that was written
  once and never updated is not out of date, it is wrong.

  All of it used to be behind a **⋮** menu that opened a drawer.

- **Pick up is where you can see it.** Claiming a conversation is the
  most common thing anybody does on this screen and it was three clicks
  deep. It is now the first button on an unclaimed conversation, and it
  is on unclaimed rows in the list too — so an agent working a pickup
  queue can take several without opening each one first.

  Ask AI to reply, Take over from AI, Transfer and Release moved out with
  it. They are in one place now rather than two: status and queue stayed
  in the details panel, because re-filing a conversation is not the same
  job as answering it.

- **Saved replies, finally reachable from the reply box.** The wording a
  team agrees on — the refund policy, opening hours, the apology legal
  signed off — has been in Blink Engage since the beginning with no way
  to reach it from the one screen where it gets used. People retyped it,
  which is slower and means the wording drifts a little every time.

  Press **/** in an empty reply box, or select the lightning icon. Search
  by shortcut, by title, or by any words in the reply itself — the
  distinguishing phrase is often in the body. Arrow keys and Enter, or
  the mouse. The wording lands in the box for you to edit before sending;
  nothing is ever sent on your behalf.

  A slash only opens the picker when it is the first thing in an empty
  box, so "12/05" and "and/or" stay typeable. Replies an administrator
  has turned off are never offered, so withdrawn wording cannot go back
  out to a customer.

- **Search now finds everything in your account, not just the inbox.**
  The search box covered conversations, customers, agents, knowledge and
  the routing objects — and not one single thing on a settings page. An
  administrator asked to change *the Platinum SLA* or *the Riyadh
  department* arrived knowing a name and nothing else, and the only way
  there was remembering which of a dozen pages it lived on.

  It now also searches **FAQs, services, departments, channels, SLA
  policies and roles**, grouped after the day-to-day results so an agent
  looking for a customer never has to scroll past a queue that happens
  to share a word.

  **It matches the name things are actually known by.** A channel is
  found by its type as well as the name you gave it, so hunting for the
  WhatsApp channel by typing "whatsapp" works even though somebody
  called it "Main line". A service is found by its code, which is what
  routing rules refer to and therefore what you arrive with when tracing
  where a rule points. An FAQ is found by words in its **answer**, not
  only its question — the question reads "Do you deliver?" and what
  makes it the right one is the city in the answer.

  **Permissions are unchanged.** Each new type is filtered by the same
  permission that already governs its own page, so search still never
  shows you a kind of thing you could not open yourself, and it still
  reports which types it looked in. Roles are the strictest of them:
  only somebody who can manage roles can find one, because a list of
  role names describes how a company delegates authority.

- **Frequently asked questions are now a real thing you can write, not
  just something search was named after.** Until now everything went into
  a knowledge article: written as a document, kept internal by default,
  and handed to the AI as raw material it then had to put into its own
  words. A company that spent a week wording its refund policy would
  watch the platform paraphrase it.

  You can now write a **question and its answer**, put them in the order
  you want customers to read them, tag and categorise them alongside your
  articles, and mark each one as Arabic, English, or neither where the
  answer applies whatever the customer speaks.

  **Publishing is a decision, not a side effect.** A new entry starts
  unpublished, because unlike an article — which only your own people see
  — this is written to be shown to customers. Unpublishing does not just
  hide it: it takes the answer back out of search, so nothing can quote
  something you have taken down.

  **Searching them understands meaning, not just wording.** The same
  two-method search the knowledge base uses now covers these too, and it
  matches on the answer as well as the question — so a customer typing a
  product name that only appears in the answer still finds it. Each
  result says which method found it.

  **And the AI now treats them as approved answers.** When it answers
  from your material, published entries are given to it first and
  labelled as answers you have already approved, with articles offered
  separately as background. Wording you signed off on is reused rather
  than rewritten.

  New: `/api/v1/faqs` for writing, ordering, publishing and searching
  them. No new permission — anyone who can already manage your knowledge
  base can manage these.

- **Complete system documentation.** A single document describing every
  feature the platform has and how each one works — written for anybody
  joining, supporting a customer or writing a proposal, not only for
  engineers. It includes what is deliberately *not* built, so a gap is
  something you can read rather than something you discover.

- **An operational readiness review of the whole platform, and an
  eight-week pilot plan.** The platform was audited as if it went live
  tomorrow — deployment, operations, performance, reliability and
  security — against the running stack and the code rather than against
  the documents describing them.

  The verdict is **not ready**, and not because the software is unsound:
  the parts that are hardest to add later are the parts that are done
  well. It is not ready because six operational capabilities a live
  system cannot run without are missing, four of them in ways that would
  be discovered during an incident rather than before one. Nobody gets
  paged. Backups have never run and a restore has never been tested. A
  malformed message would loop forever without raising any alarm. The
  metrics endpoint is publicly reachable.

  None of it is large work — roughly two to three days, none of it in the
  application, plus one rehearsal. Every finding is ranked by severity
  and probability with a recommended fix, and the pilot plan that follows
  has weekly goals, rollback criteria and gates that can each send it
  back for another fortnight.

- **The platform now knows whether a customer is waiting.** Until now it
  could not tell: the "last message" time moved whenever *anybody* wrote,
  including your own agents, so a conversation somebody had just replied to
  looked exactly like one nobody had touched. Every part of the product that
  needed to know guessed differently.

  Each conversation now records who is waiting and since when — separately
  from when the customer last wrote, because a customer who sends four
  messages in a minute has been waiting since the first one, and that is the
  wait people ask about. It also records who answered last and whether that
  was a person or AI, how many messages are still unanswered, and how long
  the customer waited for the answer they actually got.

  **A reply that failed to send does not count as an answer.** If the channel
  rejected it, the customer never saw it — so they are still waiting, and the
  platform now says so instead of quietly marking them as dealt with.

  Nothing in the product reads this yet. It is being built underneath first
  so the numbers are correct and provably correct before anything shows them
  to you; a checker recomputes every conversation's figures from its own
  messages and reports any disagreement.

- **Response time targets are edited in one place, not two.** When a service
  handles a queue, that service decides the queue's response time targets —
  so the queue's own target fields are now shown read-only, with a link to
  the service that sets them. Trying to change them through the API is
  refused rather than quietly saved.

  This closes a trap rather than removing a feature: the queue's numbers
  were already being ignored in that situation. The screen accepted them,
  said nothing, and every clock went on measuring the service's.

  **Nothing changes for a company without services.** Their queue is still
  the only place their targets live, and it stays fully editable. Everything
  else about a queue — its name, its assignment strategy, AI Autopilot —
  stays editable in both cases.

- **A daily check for settings that are saved but not obeyed.** While
  Services are being introduced, a queue can still hold response-time
  targets that no longer take effect, because a Service now owns that queue
  and the Service decides. Editing them looks like it worked: the screen
  saves, nothing complains, and the platform goes on measuring the
  Service's numbers.

  A check now runs once a day and reports every queue in that state, naming
  the company, the queue, the service, what applies and what is being
  ignored. **It only reports.** It never changes a value — a disagreement
  means somebody reached an old setting through a route that should no
  longer exist, and quietly overwriting it would destroy the evidence of
  which route that was.

  It also counts the two things that say when this transition can end: how
  many companies still have no Service, and how many queues still carry old
  response-time settings at all. Both are on the scheduled-jobs health page
  after every run.

- **A new company now starts with a Service, not an empty Services screen.**
  Registering a company creates the whole chain it needs to work — the
  company, a **General** service, a general queue, and a rule that sends
  everything to it — instead of leaving the Services screen blank for
  somebody to guess at. The service is marked as the company default, so
  anything no other service claims lands there.

  It arrives configured the way the product describes itself. **AI waits 30
  seconds before answering**, so a person genuinely gets first refusal on
  every conversation rather than finding AI already replied. **Response time
  targets are left unset**, which keeps whatever your queue already promises
  — a new service does not quietly stop the clocks.

  **AI stays off until you turn it on**, and the switches that turn it on
  are the ones you already know: the company-wide AI setting and the
  queue's. The new service does not add a third one you would have to find —
  it says this company's work may use AI, and your existing settings still
  decide whether it does. Nothing automated reaches a customer on the day
  you register.

  Existing companies are untouched by this and keep working exactly as they
  do today; they are moved separately, from the settings they already run
  on.

- **A dashboard for the pattern detection, and a dial you are allowed to
  turn.** Owners and administrators get a Pattern detection page showing
  what the platform is grouping and whether it is working: how many
  conversations it has summarised, how many are settled enough to group,
  how many groups exist and what sizes they are, how much they move
  between runs, how many conversations it could not group, how long the
  last run took and whether any failed.

  The page opens with an unmissable statement that **nothing here acts on
  what it finds** — no memory written, no articles suggested, nobody
  notified, nothing sent onward — because somebody reading a
  pattern-detection screen should not have to take that on trust.

  Numbers the platform cannot honestly compute are shown as **empty with
  a reason**, never as zero. "Stability: 0" would say the groups are
  churning; the truth on a new installation is that nothing has settled
  yet, and those need opposite responses.

  The similarity threshold — how alike two conversations must be to land
  in the same group — can now be set per company instead of being fixed
  in code, because the right value depends on how the company's
  conversations actually read. The slider stops at the range that has
  been measured to work: below it distinct problems merge into one, above
  it a single problem shatters into fragments the platform can no longer
  see. Values outside the range are refused rather than quietly adjusted.

  **Every change is recorded** — the old value, the new value, who made
  it, why, and how many groups were built under the previous setting.
  That last number matters: existing groups are kept rather than deleted,
  and without knowing they predate the change somebody would read the
  next run as a change in the business.

  New: `/api/v1/intelligence/shadow`, `/api/v1/intelligence/thresholds`,
  and a Pattern detection page in the sidebar.

- **Every company can be given a Service built from what it already runs on.**
  Services are becoming where a company states what it promises — SLA targets,
  AI policy, business hours — while queues stay the runtime that work waits in.
  Companies that predate Services had none, so a migration creates one per
  queue, copying the configuration each company *effectively* uses today.

  Nothing changes on the day it runs. A company answering instantly keeps
  answering instantly; one measuring a 3-minute first response keeps measuring
  it; one with AI switched off keeps it off. Copying model defaults instead
  would have switched AI off and stopped SLA clocks without raising a single
  error, which is why the migration reports what it would do and writes
  nothing until you tell it to.

  You can also now say **which Service catches conversations nothing else
  claimed**, instead of the platform picking whichever one happens to sort
  first — so reordering the Services screen no longer changes routing.

- **You can now inspect what the pattern detection is doing, and what it
  is not.** Three operator pages: a shadow summary of everything the
  detection pipeline measured about itself, a list of completed
  conversations it could not group — with the reason for each — and, for
  any group, the other groups most similar to it and whether the platform
  would have merged them.

  The last one exists because judging a grouping is a human job. Two
  groups that a person reads as the same thing, sitting just below the
  threshold that would have combined them, is the clearest possible
  evidence that the threshold is wrong — and no summary figure can show
  it.

  Numbers that cannot honestly be computed are reported as **empty with
  a reason**, never as zero. "Stability: 0" on an installation with
  nothing settled yet would read as churn where the truth is newness, and
  somebody would eventually act on it.

  New: `/api/v1/intelligence/shadow`, `/api/v1/intelligence/unclustered`
  and `/api/v1/intelligence/clusters/{id}/neighbours`, for owners and
  administrators.

- **The platform now notices when the same problem keeps coming back.**
  Completed conversations that are alike are grouped together, and each
  group is measured over time: how many customers it involves, how many
  separate days, whether it is growing or fading, whether it has gone
  quiet and returned, and whether it behaves unlike its own history —
  taking far longer than usual, being escalated far more often, or being
  rated far worse.

  **It tells nobody and changes nothing.** No alert, no ticket, no
  suggested article, no note added to what the platform remembers. The
  groups and the findings are pages an operator can open, and that is
  deliberate: a detector wired to alerting before anybody has checked
  whether it is right teaches people to mute it, and the mute outlasts
  the fix.

  Two rules keep the findings quiet enough to be worth reading. A group
  has to involve **at least two different customers** before it counts as
  a pattern at all — one person asking the same thing six times is one
  person. And a trend has to hold for **two consecutive weeks** and
  survive a statistical correction that accounts for how many things were
  checked; without that correction, testing three hundred topics would
  report about fifteen false trends every single week.

  Grouping is repeatable by design: the same conversations always produce
  the same groups, so the results can be rebuilt from scratch and
  compared. Re-running creates nothing — verified at three thousand
  conversations, where a second pass wrote no new groups, no duplicate
  memberships and no additional storage.

  New: `/api/v1/intelligence/clusters`,
  `/api/v1/intelligence/clusters/{id}`, `/api/v1/intelligence/trends`,
  `/api/v1/intelligence/anomalies` and `/api/v1/intelligence/metrics`,
  for owners and administrators.

- **A message that cannot be processed is now set aside instead of
  blocking everything behind it.** Previously a single event the platform
  could not handle — a change in an integration's format, a record
  deleted at the wrong moment — was retried immediately and forever. It
  never got through, it consumed the machine trying, and everything
  queued behind it waited. Nothing raised an alarm, because from the
  outside the queue looked like it was moving.

  Now such a message is retried a few times with a growing pause between
  attempts — one second, then four, then sixteen — which is enough for
  the things worth waiting for, like a database restarting. If it still
  fails, it is moved to a holding area with the reason recorded, an alert
  is raised, and everything else carries on. Nothing is discarded: once
  the cause is fixed, held messages can be put back.

- **Backups now cover everything needed to bring the platform back, and
  they leave the machine.** Previously only the database was backed up,
  by hand. A backup that stays on the same computer as the thing it
  protects does not survive that computer failing.

  Every night the platform now saves its database, its uploaded files,
  its configuration and its credentials — the credentials encrypted — and
  copies the whole set to a separate machine. Old copies are cleared out
  on a schedule so backups cannot fill the disk.

- **The recovery plan has been rehearsed rather than just written.** A
  restore that has never been performed is a hope. The full recovery is
  now a script that anybody can run: it rebuilds the database, the files,
  the configuration and the credentials into a scratch copy, checks each
  one, and times the whole thing — without touching the live system. It
  was run, it passed, and the measured times are published.

- **Alerts now reach a person.** The platform's alerting had a stand-in
  destination that went nowhere. Worse, none of the alert rules could
  actually run — each pointed at its data source by name where an
  internal identifier was required, so every one silently did nothing.
  Alerts now go to a real destination, urgent ones separately from
  routine ones, and there is a command that fires a genuine alert and
  confirms it arrives.

- **Anything you do can be followed from end to end.** Each request now
  carries a reference that travels with it through every queue,
  background worker and log entry it touches. When something goes wrong,
  the whole story can be pulled up at once instead of pieced together.

- **Two record-keeping tables no longer grow forever.** Internal logs of
  scheduled jobs and already-delivered events are now cleared out after a
  set period. Events still waiting to be delivered are never removed,
  however old.

- **A complete documentation set.** Until now the written material
  explained how the platform was built; there was very little explaining
  how to *use* it. New: a User Guide covering every feature task by task,
  an Administrator Guide covering every setting and what happens when it
  is wrong, and an FAQ grouped by who is asking.

  Also new for the first production release: a deployment guide that ends
  in a verification checklist rather than a "you're done", a catalogue of
  all 99 events the platform emits, an index over the sixty-eight
  architecture documents, and a baseline document recording what is
  settled so future work has something to be measured against.

- **The left menu is grouped instead of being one long list.** Seventeen
  entries sat side by side, mixing work somebody does hourly with
  settings they touch once a year — and an administrator had no way to
  tell which was which.

  Related destinations now sit under **Work**, **Insights**, **Routing**,
  **Connections** and **Organisation**, with Dashboard, Billing, Settings
  and Guide staying where they are. Groups remember whether you left them
  open, the one containing the page you are on opens itself, and a group
  you have no access to shows nothing at all rather than an empty heading
  listing what you cannot reach. Services and Queues also stop sharing an
  icon.

- **The guide reads in Arabic.** The in-product manual was English only,
  so an Arabic-speaking agent opening **Guide** got a notice telling them
  the translation was missing. All fifteen chapters are now translated —
  every screen, the callouts, the troubleshooting tables and 88 of the
  most-asked questions.

  English remains the fuller version and the one to trust if the two ever
  disagree, and the page still says so rather than leaving anybody
  guessing which they are reading.

- **The guide is now inside the product.** Until now the manual explaining
  how to use Blink Engage was a document everybody except the customer
  could read. There is a **Guide** entry in the menu that opens it, with
  a contents list and a search box that looks inside the text as well as
  the headings — so searching "business hours" finds the section on
  response targets even though the heading does not say it.

  It is the same document, fetched rather than copied. A second copy
  would drift, and the copy that drifts is the one customers read. It is
  available to everybody who can sign in, because help behind a
  permission is help the person who needs it most cannot reach.

- **The changelog now reads in Arabic.** Arabic-speaking users opened
  "What's new" and got English. Release notes are now served in the
  language the person is reading the product in.

  English stays the spine: it decides which releases exist and in what
  order, and a translation may only replace the prose of a release
  already there. A translation that falls behind shows that release in
  English rather than hiding it, a broken one is ignored rather than
  breaking the page, and the version the platform reports itself to be is
  never read from a translated file at all.

- **The front door is now a website, not a login form.** Visiting the
  platform's address used to send anybody without an account straight to
  a sign-in box, which told somebody evaluating Blink Engage nothing at
  all about what it is.

  The address now opens a page explaining the product: the channels it
  covers, how a customer's message becomes a measured reply, what you get,
  and who uses it — in English and Arabic, light and dark, and readable on
  a phone. Signing in is one click away in the top corner, and anyone who
  is already signed in still lands on their dashboard exactly as before.

  The page shows the product rather than only describing it: an
  illustration of the inbox drawn from the live theme (so it follows
  light, dark and right-to-left, and cannot show a layout the product no
  longer has), figures you can check, longer sections on the AI, response
  targets and the intelligence layer, what the security controls actually
  are, and the questions people ask before signing up.

  It also has a short section on **what the product does not do yet**,
  which is unusual on a landing page and deliberate: somebody who finds
  out after buying asks for a refund, and somebody who finds out here
  either does not mind or was never a good fit.

- **Help now knows who is reading it.** The same content is delivered to
  three audiences — the public site anyone can read without signing in, a
  customer's own workspace, and the provider's admin area — from one
  source rather than three copies that drift apart.

  Three things never cross the line. Help describing how to manage *other
  companies* never reaches a customer. Internal error names never reach
  the public site. And no real customer data appears anywhere, including
  in screenshots.

  The provider's own screens — companies, billing, invoices, pricing,
  platform health — now have their own help, including the six questions
  customers ask most and what the honest answer to each one is.

- **A complete Help Center content set** — the words the product shows
  you without leaving it. Context help for every screen, one-line
  explanations for 88 fields, friendly messages for 30 empty screens, 47
  error messages rewritten into plain English, a guided first-run tour,
  and a search index built around the words people actually type rather
  than the official feature names.

  Two ideas run through it. Errors say what happened, why, and what to do
  next — and never blame the reader. And an empty screen explains *why*
  it is empty: "no conversations yet" and "no conversations match these
  filters" are different problems that send you in opposite directions.

  Every screen and feature now has a permanent identifier, so a future
  interface can open the right help automatically and keep doing so after
  screens are renamed or moved.

- **The official Blink Engage User Guide.** A complete product manual
  written for people who have never used the platform, rather than for
  the people who built it. Fifteen chapters covering every screen, every
  button and every field, with worked examples, best practices, the
  mistakes teams actually make, and a 135-question FAQ.

  It is deliberately honest about what is not there. Six things people go
  looking for — conversation tags, knowledge version history, API keys, a
  dedicated escalation screen, a mobile app, and the platform acting on
  what it learns — are each named as unavailable in the place you would
  expect to find them, so nobody spends an afternoon hunting for a button
  that does not exist.

- **A post-launch roadmap.** Everything still outstanding, grouped into
  the first month, the quarter, and later — each item stating what it is
  worth, what it costs, what could go wrong while doing it, what it
  depends on, and **why it was deliberately left until now**. That last
  point is the useful one: it turns a list of unfinished work into a
  record of decisions, so the same argument does not get had twice.

  A pattern runs through it. Most of the intelligence work is waiting not
  because it is difficult but because it is unearned — the platform has
  not yet seen enough real conversations to draw conclusions from, and
  building inference on top of that would produce confident output with
  nothing behind it.

- **A specification for a stricter onboarding wizard.** The wizard that
  exists walks an administrator through four steps but requires nothing —
  it is possible to finish setup for a workspace with no channel
  connected, which no customer can reach, and be told setup is complete.
  The specification makes each step's completion derive from what is
  actually configured rather than from which screens were visited.

### Fixed

- **The left menu's group headings were smaller than the items inside
  them**, which read as a caption under its own list rather than as the
  heading that opens it. Headings and items are now the same size, and
  weight and colour do the separating.

- **Channel badges were invisible to screen readers.** The badge carried
  its name in a way browsers are required to ignore, so the channel a
  conversation arrived on was announced as nothing at all. Every list and
  every conversation header is affected.

- **The user guide described two screens that do not exist.** It gave
  step-by-step instructions for a Knowledge screen and a Workflows
  screen — opening menus, selecting buttons, saving articles. Neither
  exists in the interface. Both capabilities are real and working in the
  platform, and both are maintained through the API by your provider,
  but there is nothing to open.

  Checking this is what the Help Center work turned up. Every section of
  the guide is now verified against the running product, and all six
  things people go looking for and will not find are named in the place
  they would look.

- **None of the platform's alert rules could run.** All twelve referred
  to their data source by its display name where an internal identifier
  was required. Each was listed, looked correctly configured, and quietly
  failed every time it was evaluated — so the monitoring appeared healthy
  while covering nothing. The identifiers are now fixed values, and the
  verification command fails if this ever recurs.

- **Several alerts had nothing to measure.** Warnings about the disk
  filling up, about storage being unreachable, and about messages piling
  up in a holding queue were all written against readings the platform
  never actually collected. It now collects them: host disk and memory,
  storage health, and per-queue depth. Writing the warning is not the
  same as being able to see the thing it warns about.

- **The "a scheduled job has stopped" warning compared everything to one
  deadline.** Jobs here run anywhere from every five seconds to once a
  day, so a single deadline meant the daily ones always looked overdue —
  it would have raised a false alarm every morning until somebody turned
  it off. Each job is now judged against its own schedule. It also no
  longer reports on jobs that are not scheduled at all.

- **The log dashboards showed nothing**, for the same reason: they
  pointed at an identifier the log store did not have.

- **A retired alert destination was still selectable.** Renaming it had
  removed it from the configuration but not from the system, leaving a
  stand-in that pointed nowhere available to anyone editing an alert. It
  has now been removed properly.

- **Every service running in production now has a memory limit, a
  restart policy, a health check and log rotation.** Three were missing
  from the production configuration entirely — including the one that
  records billable usage — which meant an unbounded process could have
  taken the machine down with it.

### Security

- **Internal metrics are no longer reachable from the public internet.**
  The metrics endpoint exposes request volumes and timings — useful to
  the monitoring system, and an unnecessary disclosure to anybody else.
  It is now restricted to the monitoring network, with the block
  confirmed from outside it.

- **Backed-up credentials are encrypted.** The file holding the
  platform's secrets is stored encrypted within each backup set, so a
  copy of a backup is not a copy of the credentials.

## [1.1.0] - 2026-08-05

The first stable release. Everything built and tested through the beta
programme, released together: the operational platform, the AI Autopilot,
billing and invoicing, and the first three stages of the company
intelligence layer — knowledge search that understands meaning, a memory
that can show its evidence and be erased on request, and an observation
layer that measures how work actually finishes before anything is built
on top of it.

### Fixed

- **A customer writing back after a conversation was closed no longer
  leaves it on record as solved.** Reopening a conversation — whether
  because the customer replied, or because somebody moved it back out of
  a finished state — was never passed on to the part of the platform that
  records how work finishes. A conversation the customer had to chase
  again therefore stayed recorded as resolved, and as resolved on first
  contact, which is the most flattering thing it could wrongly say.
  Reopening now cancels that record, and the conversation is measured
  again from its next real ending.

  Nothing about this was visible from the outside: every figure involved
  looked healthy, because the record simply never received the news. So a
  safeguard was added alongside the fix — the platform now checks
  automatically that every signal any part of it waits for is actually
  sent by something else. A part waiting on something that never happens
  is now caught before it can ship, rather than sitting quiet.

- **The platform no longer learns from its own paperwork.** Before the
  observation layer was let near real traffic it was run against it, and
  two things came back wrong.

  The satisfaction survey the platform sends after a conversation was
  being counted as though a person had written it. Its wording — "share
  your feedback", "take a moment" — was being recorded as what the
  conversation was *about*, on every conversation that received one. It
  is now marked as what it is: a message the platform sent on nobody's
  behalf, and not evidence of anything.

  Links were worse. A survey link contains a long unique code, and the
  pieces of that code were being recorded as subjects of the
  conversation. Six of the twenty subjects kept per conversation were
  fragments of a web address, crowding out the words that actually
  described the problem — on one real conversation, "wrong", "twice" and
  "want" only appeared once the noise was removed.

  Both are fixed, and everything observed before the fix has been
  re-observed rather than overwritten, so the old and new readings can be
  compared side by side.

- **A background job that failed could report success.** The job that
  finalises observations runs every fifteen minutes but recorded its
  result once an hour, so three runs in four left no trace — including
  their failures. The health page could therefore show no failures
  through a job that was failing every time. Each run is now recorded.

- **What the platform remembers can no longer become more certain on its
  own.** An internal review found that re-delivering the same observation
  — which happens routinely, because the message system guarantees
  at-least-once delivery — made a remembered fact look freshly observed. A
  fact nobody had seen in months could be pushed back to full confidence
  by a duplicate that carried no new information at all, measured at more
  than four times its correct value.

  Confidence now moves only when genuinely new evidence arrives. A
  duplicate is recognised as a duplicate and changes nothing.

  Three related corrections came with it. Something contradicting a fact
  is now recorded once however many times the notification arrives, so a
  true fact is no longer marked down repeatedly for the same
  disagreement. The "rising / falling" indicator can now actually report
  *falling* and *contested* — both were unreachable before, meaning the
  signal designed to tell you a fact is going out of date could never
  do so. And evidence claiming to come from an agent or a connected
  system must now identify which, so nothing can claim a stronger source
  than it has.

- **Memory ages evenly across every company.** The job that keeps
  confidence current worked through a single global queue, so one company
  with a very large history could consume it entirely and every other
  company's memory would stop ageing. It now serves each company in turn,
  sizes its own workload to the amount of history it has to get through,
  and gives up on an individual record that keeps failing instead of
  retrying it forever.

  Confidence you read is now correct at the moment you read it rather
  than at the moment it was last recalculated, and `GET /memory/status`
  reports how much of your history is waiting to be recalculated.

- **Erasure now proves it finished.** Erasing everything held about a
  customer clears their live conversation memory too — previously it did
  not, and the response said so incorrectly — and every part of the
  platform holding data about them must confirm before the erasure is
  reported as complete. Anything that cannot confirm is named in the
  response rather than quietly omitted.

### Added

- **The platform has started paying attention to how work actually
  finishes.** A new background layer records one summary per completed
  conversation: what it was about, which language it was in, any order
  numbers or amounts mentioned, how it ended, how long it took, and
  whether the customer rated it. Nothing is copied — each summary points
  back at the messages it came from, so you can always see exactly what
  it was drawn from.

  **It only observes.** It does not answer anything, suggest anything,
  change anything you have written, or decide anything. That is
  deliberate: this is the stage that measures whether the platform is
  seeing what we think it is seeing, before anything is built on top of
  it.

  Two things it refuses to do are worth stating plainly. It does not
  learn from its own replies — a conversation the AI handled end to end
  is recorded as *not learnable* rather than treated as experience, and
  the share of observed content the platform itself wrote is reported to
  you as a number, because that figure quietly rising is the one way a
  system like this goes wrong invisibly. And it does not treat an
  automatic closure as a success: a conversation closed by a rule is
  closed, but only a person deciding a conversation is finished counts as
  evidence that anything worked.

  Nothing is treated as final straight away. A summary waits until its
  outcome can no longer change — a satisfaction rating arriving, or a
  reopened conversation — and settles by itself after three days if
  nothing arrives. Otherwise a conversation the customer went on to rate
  badly would be recorded as a neutral one.

  Learning is on by default and switched off per company from the same
  place as memory, and switching it off stops it before a single message
  is read — the refusal itself is recorded, so you can show that the
  platform saw a conversation and chose not to learn from it. Erasing a
  customer removes their summaries along with everything else, and the
  erasure response now counts them.

  New: `/api/v1/intelligence/observations`,
  `/api/v1/intelligence/observations/{conversation_id}`,
  `/api/v1/intelligence/runs` and `/api/v1/intelligence/health`, for
  owners and administrators.

- **Blink Engage now remembers, and can tell you why.** A new platform
  layer records what the system has observed — about your business, about
  each customer, and about what has historically worked — with the evidence
  behind every fact, a confidence that is calculated rather than asserted,
  and an age.

  Nothing here guesses. Every remembered fact must arrive with evidence
  pointing at where it was observed, and the platform refuses to store one
  without it. Confidence is computed from how much support a fact has, how
  broadly that support is spread across different customers and different
  agents, how the conversations behind it turned out, and how long ago it
  was last seen — so a claim repeated forty times by one person is not
  treated as the same thing as one six people arrived at independently.

  Facts age. One nobody has seen for months goes quiet; one nobody has seen
  for a year and a half leaves the working set; and one that goes quiet and
  then comes back returns with the standing it had earned rather than
  starting again. You can confirm a fact, correct its wording, or mute one
  that is wrong — a muted fact stays muted rather than being quietly
  re-learned next week.

  **Erasing is separate from forgetting, and it completes.** Erasing a
  customer removes every fact about them and every trace of their
  contribution, and tells you exactly what it removed. Company-wide
  patterns their conversations helped establish are kept — those are facts
  about your business, not about them — but recalculated, so nothing is
  left claiming support it no longer has.

  Live conversations get a short-term memory of their own: the order
  number, the question still unanswered, what was promised. It expires with
  the conversation rather than being kept.

  Memory is on by default and can be switched off per company, separately
  from AI — turning AI off does not empty your customer history. Reading is
  available to agents, changing facts to administrators, and erasing to
  owners only.

  New: `/api/v1/memory/*` for facts, subjects, status and conversation
  memory.

- **Knowledge search now understands what people mean, not just the words they
  typed.** Searching your knowledge base used to be a plain "does this article
  contain this text?" check, so a customer asking *"can I get my money back"*
  found nothing in an article titled *"Refund policy"* — and the AI, reading
  from that same search, correctly and uselessly replied that it could find no
  relevant articles.

  Search now combines two methods and merges their results: the original
  text matching, which is still what finds an order number, a plan name or a
  product code exactly; and semantic matching, which finds articles that
  answer the question in different words, including across Arabic and English
  in the same sentence. Each result shows which method found it.

  AI answers are grounded in the specific passage that matched rather than the
  whole article, so a question answered on page four of a long manual no
  longer arrives buried in four pages of unrelated text.

  This is off until you turn it on. Choose an embedding provider in your
  environment configuration — a hosted one, or a self-hosted model for
  installations where customer text may not leave the network — and your
  articles are indexed in the background within a few minutes. Until then,
  search behaves exactly as it did, and says so rather than quietly returning
  less.

  New: `GET /api/v1/knowledge/search` (hybrid search) and
  `GET /api/v1/knowledge/index-status` (how much of your knowledge base is
  indexed, what is still queued, and what failed). The existing article list
  and its `search` parameter are unchanged.

### Changed

- **The observation layer now shows an operator what it is doing.** One
  page reports how many observations are waiting, how many are final, how
  many runs failed, how many have been re-observed after a change to how
  observation works, and how many have been erased at a customer's
  request — alongside the figure that matters most: how much of what the
  platform observed the platform itself wrote.

  Erasures are counted from the audit trail rather than from the
  observations, because after an erasure there is nothing left to count.
  The erasure record now also lists what each part of the platform
  removed, so the trail says the same thing the erasure report said.

- **Your configuration now has one answer, and every screen gives the same
  one.** Settings resolve down a single chain — the service, then the queue,
  then company-wide, then a platform default — for SLA targets, AI policy and
  the AI confidence threshold alike. Before this each of those resolved
  differently, and which answer you got depended on which screen you opened.

  Nothing you have configured changes. What changes is that the platform can
  now tell you *where* a setting came from: a conversation's deadline says
  whether it was set by a service, by the queue it is waiting in, company-wide,
  or by a platform default because nothing is configured for it. A due time you
  cannot trace is a due time you cannot act on.

### Fixed

- **When AI hands a conversation back, it now says why.** The timeline showed
  that AI had given a conversation to a human and never what prompted it —
  whether the model asked for help, whether it was not confident enough,
  whether it produced nothing usable, or whether Autopilot was configured not
  to run at all. Those are four different problems with four different fixes,
  and the platform knew which one it was every time.

  Where the reason is not one the platform recognises, nothing is recorded
  rather than a guess: an invented explanation on this screen is worse than a
  missing one, because a missing one sends you looking.

- **AI decisions are now explained for every company, not just those using
  Services.** Whether AI may answer was decided by the policy engine on one
  path and by five hidden conditions on another — and the second recorded
  nothing. Companies on that path enforced every rule correctly and could never
  answer "why did AI reply to this conversation and not that one".

  Every company now gets a recorded decision naming the switch that decided it.
  Nothing about who AI answers has changed; only whether you can find out why.


- **A conversation's history never shows you an internal identifier.** Where
  the timeline said who took a conversation over, it could print something like
  `human_agent 93b777f2-c048-4c10-9d84-5b17c6813d63` instead of the person's
  name — on the one screen whose entire purpose is explaining what happened.

  Names are stored on each entry as they were at the time, so a history still
  reads correctly after somebody leaves. Two places could not afford that
  lookup while an agent was waiting and stored nothing instead, and the display
  fell back to the identifier. Those entries now resolve the name when the
  history is read, and entries that recorded a name keep it — so a queue
  renamed since is still described the way it was on the day.

- **Your SLA policy now actually measures conversations.** Deadlines were read
  only from the service directory, so a company that had built an SLA and
  attached it to a queue measured nothing at all: an empty Breached list, no
  SLA ordering in the Inbox, and no SLA events on any conversation's history —
  with nothing anywhere saying why.

  Targets now resolve from the service, then the queue's own policy, then a
  conservative platform default, and each conversation records which of the
  three it used.

- **Conversations no longer disappear when nothing matches a routing rule.**
  Every existing company now has a catch-all rule and a queue for it to point
  at, so a message that matches none of your specific rules lands somewhere an
  agent is looking instead of reaching nothing at all.

  Before this, a conversation that matched no rule was recorded accurately —
  "it reached no queue, so nothing will pick it up" — on a screen nobody had a
  reason to open, and was then invisible everywhere else. AI never saw it
  either: Autopilot works a queue, so a conversation in no queue is one AI is
  never offered. The symptom people actually hit was configuring AI, sending a
  test message, and waiting for a reply that was never coming.

  New companies have had this since registration started seeding a queue; this
  brings every company that existed before that in line. The seeded rule has
  the lowest possible priority, so every rule you have already written still
  wins — it only claims what nothing else claimed — and it is ordinary
  configuration you can rename, edit or delete.

- **Assignment and ownership can no longer disagree about who has a
  conversation.** Assigning a conversation through an automation rule, an SLA
  escalation, or by taking one back from AI updated who it was assigned to
  without recording the handover — so the Inbox could show a conversation as
  owned by its queue while it was in fact assigned to an agent, and nothing
  reported the contradiction.

  Every way a conversation can change hands now writes one entry to its
  history, and who it is assigned to follows from that entry rather than being
  set separately. The conversation's timeline gains the transitions that were
  previously missing, including a human taking a conversation off AI — the one
  that matters most, because it is what tells AI to stop.

  Releasing a conversation that belongs to no queue is now recorded as
  genuinely unowned rather than silently leaving the previous owner's name on
  it.

### Changed

- **The default queue every company starts with is named "General".** New
  companies already got this; installations carrying an older default now
  match. It is ordinary configuration — rename, edit or delete it like any
  other queue.

### Added

- **AI now waits, so your agents get first refusal.** When a conversation
  arrives on an Autopilot queue, AI no longer answers instantly. The
  conversation sits in its queue for the service's pickup delay — 30 seconds
  by default — where an agent can see it and take it. AI picks it up only if
  nobody does.

  This is what the "AI pickup delay" setting always said it did. Nothing was
  reading it, so AI replied the moment a message landed and the chance it
  describes was never actually offered.

  Set the delay to zero on queues where waiting only makes the customer wait —
  an FAQ line, or an after-hours line with nobody behind it — and AI answers
  immediately, exactly as before.

  Every outcome is on the conversation's timeline in plain language: that AI
  is waiting and for how long, that it took the conversation because no agent
  did, or that it stood down because somebody got there first. A conversation
  where nothing has visibly happened can now say why.

  The decision is re-checked when the delay runs out, not made in advance. If
  AI is switched off during those thirty seconds, AI does not answer.

  The delay and the confidence threshold are now editable per service, under
  Services → AI. Both governed real behaviour and neither could be reached
  from any screen — a setting the platform obeys and nobody can change is a
  setting nobody can trust.

  AI also only takes a conversation once it actually has an answer to give.
  If the model is unavailable or unsure, the conversation stays in the queue
  for a human instead of being taken away from the people who could help.

### Added

- **The Inbox is becoming an operations screen rather than a message list.**
  Conversations can now be opened as work queues — what needs attention, what
  is waiting for pickup, what is assigned to you, what AI is working on, what
  is waiting on the customer, what is at risk, what has breached, what was
  resolved today — instead of building a filter out of three controls.

  A single request now answers how many conversations are in each queue across
  the whole company, so "how busy am I" can be read before opening anything.

  Every row now carries what it needs to explain itself: the customer's name,
  what the conversation is waiting on, who is answerable for it, and how long
  it has been that way. Previously the customer's name — the thing an agent
  scans for — was fetched one conversation at a time, so it appeared last and
  in a staggered trickle.

  The Inbox says what is true and leaves the decision to the agent. It reports
  that a conversation is waiting for pickup; it does not instruct anybody to
  pick it up.

  The screen itself is now built in three layers, in the order the questions
  are actually asked: what does my day look like, what requires my attention,
  and only then which conversation to open. Opening the Inbox lands on what
  needs attention rather than on an undifferentiated list.

  Each conversation explains itself before showing its content — who the
  customer is, what the conversation is waiting on, who is answerable, how
  urgent it is, how long it has been that way, and what most recently changed.
  The message text comes after all of that, because an agent should know why
  something is in front of them before reading a word of it.

  Empty queues stay visible with their zero. "Nothing has breached" is one of
  the most useful things this screen can say.

### Fixed

- **Conversations no longer vanish in companies created before this
  release.** Registration seeds a `General` queue and a catch-all routing rule
  so a new company is operable the moment it exists — but companies that
  already existed never got one. Any message that matched none of their
  specific rules reached no queue at all: invisible to agents, and never
  offered to AI, because Autopilot only picks up from a queue.

  On this installation that was **every existing company**. A one-off upgrade
  step now gives each of them a catch-all rule at the lowest possible
  precedence, pointing at their oldest existing queue — or a new `General` one
  if they had none. Routing that already worked is untouched: the new rule
  only claims what nothing else claimed.

  The queue and the rule are ordinary configuration from that point on —
  rename, edit or delete them like any other.

- **The Inbox can be scrolled again when a queue is fuller than the
  window.** Any work queue holding more conversations than fitted on screen
  simply cut off at the bottom, with no scrollbar and no way to reach the rest
  — the conversations were loaded and rendered, and unreachable.

- **"Assigned to me" no longer shows work that belongs to nobody.** For a
  supervisor or owner without an agent profile, it returned every unassigned
  conversation in the company as though it were theirs personally.

- **You can now see everything that happened to a conversation, on one
  screen.** Open a conversation's story and read it top to bottom: the
  customer's message arriving, which service and queue it went to and why, who
  became responsible at each point, when AI stepped in and how sure it was,
  every SLA clock starting, pausing and settling, and every business rule that
  was asked along the way.

  Each event says what happened, why it happened, and what happened next
  because of it. Search covers the whole story, not just event names — looking
  for "threshold" finds the moment AI decided it was confident enough. Filters
  narrow by type and show how many of each there are, so "were any policies
  evaluated?" is answered without clicking through.

  Events are marked Success, Warning, Error or Critical by the platform
  itself, so the same event looks the same everywhere it is shown.

  A collapsible Technical section carries the identifiers an engineer needs,
  out of the way of everyone else. Support teams should rarely need database
  access to answer "what happened with this customer".

  The platform had been recording all of this for months. None of it could be
  read anywhere until now.

- **The application now refuses to start if a critical service is missing
  something it needs.** Several defects have shared one cause: a component
  that works correctly on its own, connected through an optional dependency
  that the running system was never actually given. Nothing errors — the
  platform just quietly stops doing one of the things it promises, and it
  shows up months later as a wrong number in a report.

  Start-up now checks the real wiring and refuses to run, naming what is
  missing and what would have silently stopped working. A missed connection
  becomes a service that will not start rather than a figure nobody can
  explain.

### Fixed

- **Your billing page, estimate and invoice now always agree on the rate.**
  The unit price shown is the one that actually billed that period: the
  invoice's own frozen figure once a bill exists, and what the billing engine
  would charge for the usage so far while the month is still open.

  Previously the page took the rate from the most recent day that had one. A
  day on which no price was in effect stores none — so a single such day
  showed a blank rate for the whole month while charges kept accruing, on the
  one page a customer goes to check what they are paying.

  A price edited after a bill is issued no longer changes what that bill's
  page says you were charged.

- **The AI confidence threshold on the Services screen is now the one that
  decides.** It was displayed per service and enforced company-wide, so an
  administrator could set a number, watch it save, and have the platform
  ignore it. The service's threshold now governs; the company-wide setting
  applies only where a service does not define one.

  Leaving a service's threshold empty means "use our company setting", and
  that is now a real, storable state rather than an invisible default — a
  company that had deliberately chosen 0.9 will keep it instead of silently
  inheriting a service default nobody picked.

- **Picking up, releasing and transferring a conversation now show in its
  history.** Only the platform's own automatic actions were recorded, so a
  conversation an agent was holding still displayed whoever the system had
  last given it to. Every human action now appears with the person and the
  reason.

- **AI replies now stop the SLA clock.** A conversation answered by AI in
  seconds still had its first-response timer running, so it would go on to be
  reported as a missed target the customer had in fact already been answered
  on. This affected every AI-handled conversation, not only new ones.

- **AI now shows as handing a conversation back.** When Autopilot hands off to
  a human — because it is not confident enough, or no AI provider is
  available — the conversation's history now records it returning to its
  queue. Previously the history showed AI taking conversations and never
  letting go: "who is responsible for this?" answered "AI", about a
  conversation AI had explicitly given up on.

- **The Inbox now opens on the work that needs doing.** Every conversation
  carries an SLA health reading — 🟢 healthy, 🟡 attention, 🟠 at risk,
  🔴 breached — and the list is sorted by it, worst first, before priority.

  A breached ordinary conversation now sits above a healthy urgent one. The
  urgent one still has time to be handled; the other has already run out, and
  only one of the two can be fixed by acting now.

  The health badge appears only on the three bands that need action. Most
  rows, most of the time, show nothing — including a conversation paused
  waiting for the customer to reply, which is healthy rather than neglected. A
  badge on every row is the same as a badge on none.

  The ordering is across the whole company, not the page being viewed. A
  breached conversation cannot be sitting quietly on page four.

### Changed

- **A conversation is reported as breached the moment its target passes**,
  rather than when the background sweep next runs. The sweep still records the
  breach; it no longer decides it. Previously a conversation could show as
  merely "at risk" for up to a minute after it had already missed its target.

### Fixed

- **The checks that guard code quality can now pass.** Two of the project's
  automated gates — code formatting and linting — had been failing for some
  time across 134 backend files, which meant nobody could tell a new problem
  from the existing noise. The formatting is behaviour-neutral and was
  verified file by file to change nothing but layout. Two genuine lint
  findings were fixed alongside it.

  The migration scripts still fail both gates and were deliberately left
  alone; several of them have uncommitted edits in progress, and reformatting
  work someone is in the middle of is not a fair trade for a green check.


- **When AI does not answer, the platform now says which setting stopped
  it.** The decision is recorded with the exact switch and the screen it
  lives on — the company-wide AI switch, the Autopilot switch, the
  activation mode, or a missing AI provider. Previously all four produced
  the same silence.

  They are reported in the order that helps: a missing provider comes
  before "Autopilot is switched off", because AI that cannot work at all is
  a different problem from AI a company chose not to use here — and an
  administrator told the second, who switches it on and finds AI still
  silent, has been sent the wrong way.

  Companies that have not set up services are unaffected and behave exactly
  as before.

### Added

- **Response-time targets now describe the customer's experience.** Four
  clocks, each answering a question a customer would recognise: how long
  they waited before someone took responsibility, how long until they got a
  first real reply, how long they are waiting for the next one, and how long
  until the problem was solved.

  Each service sets its own targets, and any of them can be left unmeasured
  — a back-office queue that answers when it answers is a real way to work,
  and inventing a deadline for it would put a red row in front of an agent
  for a promise nobody made.

  **A clock never just stops — it always says why.** Waiting for the
  customer, outside business hours, paused by an agent or a supervisor,
  waiting on something outside the conversation, or maintenance. Time a
  customer spends thinking is not time the business was late, and the
  deadline moves out by exactly that much and no more. A note can add
  detail; it can never replace the reason.

  Every conversation shows a single **SLA health** indicator — healthy,
  attention, at risk, or breached — rather than four timers to interpret.
  Four timers is a report; one indicator is a decision, and the timers stay
  available underneath. A conversation waiting on the customer is *healthy*,
  not neglected: an agent needs to be able to skip it without wondering
  whether they should. The worst clock decides, never an average.

  Each timer also says **who it is waiting on** — the queue, an agent, AI, a
  supervisor, or the customer. The customer never owns a conversation and is
  still the honest answer while the ball is with them; saying otherwise
  blames an agent for a delay that is not theirs.

  The clocks now run from real events: they start when a conversation is
  queued, the queue clock is answered the moment somebody takes
  responsibility, a reply settles what the customer was waiting for, and
  marking a conversation as waiting on the customer pauses them.

  A missed target stays missed. A late reply does not erase the lateness,
  and a conversation that ended before a clock could be met or missed is
  recorded as exactly that rather than counted as a success.

  A target that runs out is now marked as missed within a minute, and
  appears in the conversation's history like every other change. A
  conversation paused waiting on the customer is never marked missed for
  the customer's silence.

  Every start, pause, resume, achievement and breach is recorded in the same
  history as the routing decisions, so a conversation can be explained by
  reading one story in order — including why a deadline moved.

### Changed

- **A conversation's status now says one thing.** There were four statuses
  and "open" meant two different things — waiting in a queue for somebody
  to pick up, and being actively worked by somebody. Those need different
  responses from a supervisor, so they are now different statuses.

  Eight states: **not yet routed**, **waiting in queue**, **being
  handled**, **waiting for customer**, **waiting internally**,
  **resolved**, **awaiting rating**, **closed**.

  Existing conversations were migrated. Anything that was "open" became
  *being handled* if somebody was assigned to it and *waiting in queue*
  otherwise; "pending" became *waiting for customer*.

  Queue counts get more honest as a result. "How many are waiting" now
  means conversations nobody has picked up, and no longer includes ones
  where the business is waiting on the customer to reply — those made
  queues look like they were drowning when they were idle.

### Added

- **Every conversation now has an owner, and the platform records every
  time it changes hands.** Ownership is who holds responsibility, which is
  not the same as who it is assigned to:

  - A conversation waiting in a queue is owned by **the queue** — nobody
    is assigned, but it is not nobody's problem.
  - One AI is handling is owned by **AI**, not by nobody.
  - An agent who goes offline mid-conversation may keep owning it, so a
    customer who replies twenty minutes later reaches the person who
    already knows them.

  You can see the whole history: who has it, why, since when, who had it
  before, and why it moved. "Support queue → AI → Support queue → John"
  reads as what actually happened.

  Ownership rules are configurable — an owner can keep a conversation for
  a window after they stop working it (24 hours by default), release it
  the moment they stop, release on resolve, or hold it through to close.
  When a window runs out the conversation goes back to its queue
  automatically, and the history records that it was the window and not a
  person who let it go.

  Every owner is responsible for something specific — a queue for somebody
  picking the conversation up, an agent for talking to the customer, AI for
  answering within the service's policy, a supervisor for whatever the
  escalation was about. "Nobody" is an exceptional state rather than a
  resting one: every route hands a conversation to its queue instead, so a
  conversation with no owner means something went wrong that was not
  caught.

  Reasons for a change of hands come from a fixed list — arrived, picked up
  by an agent, AI engaged, AI released, customer replied, ownership
  expired, resolved, closed, escalated, transferred, supervisor override.
  A note can add detail; it can never stand in for the reason, because a
  reason has to be countable.

  Status, queue and owner are now three independent things. A conversation
  can be resolved and still owned, waiting and owned by its queue, being
  handled and owned by nobody. None of those are contradictions, and
  treating them as one fact is what made the old statuses ambiguous.

- **The billing scheduler is now visible.** A new **Health** page in the
  Platform Console shows each background billing job — closing each month,
  billing it, chasing what is unpaid, keeping the figures current — with
  when it last succeeded, when it runs next, how long it took, how many
  companies it processed, how many invoices it generated, and anything it
  could not process.

  This exists because of a real failure: three of those jobs were failing on
  roughly every other run for months. Nothing looked wrong, because every
  one of them is safe to repeat — a failed run simply left its work for the
  next one. The only evidence was in the logs.

  A job is flagged as **failing** when it has not succeeded within three of
  its scheduled runs, not merely when one errors. A single missed run is
  normal — a deployment, a restart — and an alert that fires on one is an
  alert people learn to ignore. A job that succeeded but could not process
  some of what it found is shown as **needs attention**, because "thirty
  companies billed and one not" is a real problem the word "succeeded" would
  otherwise hide.

  The installation's overall state is the worst of its jobs, never an
  average.

- **Services can now be created and edited from a new Services screen.**
  A service is a thing customers can be helped with — Billing, Technical
  Support, Sales — and it decides which queue a conversation goes to, which
  response times are measured, and whether AI may answer.

  **Editing a service never changes conversations already in progress.**
  When you change something a live conversation depends on — a response
  time, the queue, the AI setting, or the name — the platform keeps the
  previous settings and starts using the new ones for conversations that
  begin afterwards. The screen tells you which it did: "Saved as version 3.
  Conversations already in progress keep the settings they started with."
  Purely administrative changes — reordering the list, switching a service
  off, editing its description — do not create a version, because no live
  conversation depends on them.

  You can add a note explaining any change, and see the history of earlier
  settings, which are kept because conversations are still running on them.

  Archiving a service removes it from the directory and stops new
  conversations reaching it. Conversations already running keep working and
  can still say which service they belong to.

  Response-time targets can be left blank for anything you do not want
  measured. Blank is not the same as 0 — 0 means the target is missed the
  moment the clock starts.

- **Business rules now explain themselves in the conversation's history.**
  Whenever the platform decides whether something is allowed — may AI answer
  this, may this be routed, may an agent take it — the decision is written
  into the same record as the routing and service decisions, with what was
  decided, why, and which setting produced the answer.

  Permissions are recorded as well as refusals. A record holding only
  refusals answers "why was this blocked?" and not "why was this allowed?",
  and the second is the question asked after something reaches a customer
  that should not have.

  Simply *viewing* what the platform would currently allow does not add to
  the record — otherwise opening a conversation to understand it would
  change its history.

- **A service now decides which queue its conversations go to.** If a
  service names a queue, conversations for that service go there, and the
  record says so: "Routed to Billing queue because the service sends its
  conversations there."

  The service directory is where you say which team handles what, so a
  routing rule pointing somewhere else would be a second answer to the same
  question. Routing rules still apply everywhere a service has not
  answered — companies with no services, and services that deliberately
  name no queue of their own — and are unchanged for everybody who has not
  set services up.

- **Conversations are now matched to a service, and the platform records
  why.** A *service* is a thing a customer can be helped with — Billing,
  Technical Support, Sales. When a message arrives, the platform works out
  which one it belongs to and writes down how it decided.

  It tries, in order: what the customer chose themselves, then the
  company's own rules (by channel, or by words in the first message), then
  the company's only service if there is just one, and finally a fallback
  so that no conversation is ever left belonging to nothing.

  **Every step is kept, not only the one that decided.** "Why did this go
  to Billing?" is answered as much by what the earlier steps did not do —
  the customer was never offered a choice, no keyword matched — as by the
  step that did. The decision also records *which version* of the service
  was used, so a conversation can still be explained after the service has
  been edited.

  Keyword rules match whole words. A service set up for "count" does not
  swallow "I can't access my account" — a misroute that arrives somewhere
  and so never gets reported.

  Companies that have not set up any services are entirely unaffected: no
  extra records are written and conversations are handled exactly as
  before.

- **Groundwork for the Service Directory.** New storage for *services* — the
  things a customer can be helped with — and for the frozen configuration a
  conversation runs inside.

  A conversation now has somewhere to record which rules it started under.
  When an administrator edits a service, the old settings are kept rather
  than overwritten, so a change made at noon cannot rewrite the deadline of
  a conversation opened that morning — an agent watching a countdown would
  otherwise see it jump. The same applies to the customer: their tier,
  language and contract are captured as they were when the conversation
  began.

  Customer details are only re-captured when something that actually changes
  how a conversation is handled changes. Correcting a customer's name does
  not create a new record; promoting them to VIP does.

  A conversation moved from one service to another keeps its full history,
  so "why did this end up with the wrong team?" remains answerable
  afterwards.

  Nothing is switched on yet: existing conversations are unaffected and
  behave exactly as before. The routing engine starts using this in a
  following release.

- **Payment providers can now be set up from the Platform Console.** A new
  **Payments** screen lists every scheme the product supports, including
  the Jordanian ones — **eFAWATEERcom, CliQ, MEPS and Network
  International** — alongside PayPal and manual entry. Credentials are
  stored encrypted and each provider is saved on its own, so setting up one
  can never disturb another.

  Each scheme is described by how it is *actually* paid, not lumped
  together as "a gateway": a hosted checkout, a bill you publish and the
  customer pays at any bank channel, a transfer the customer pushes to your
  alias, or a payment finance records by hand. Getting that wrong is how a
  customer ends up at a checkout page a scheme does not have.

  Jordanian schemes are offered only to Jordanian customers, and PayPal is
  not offered to them — showing somebody a payment route they cannot use is
  worse than showing nothing.

  Each provider says plainly where it stands: **active**, **not set up**,
  or **awaiting integration**. eFAWATEERcom, CliQ, MEPS and Network
  International are at *awaiting integration* — their credentials can be
  entered and stored now, and they are deliberately not offered to
  customers as a payment option until the integration with each scheme is
  built, so nobody meets a payment button that cannot complete.

  Settings entered here take precedence over the deployment's environment
  variables, and an installation that has never opened the screen keeps
  working exactly as before.

### Security

- **A saved payment credential is never sent back to the browser.** The
  settings screen is told that a secret exists, not what it is, and a
  credential the operator does not retype is left untouched rather than
  overwritten with a blank. Without that, opening the payments screen and
  pressing Save would have quietly unconfigured every merchant account on
  the installation.

### Fixed

- **Invoices are now generated automatically at the start of each month.**
  Closing a billing period and invoicing it were separate steps, and only
  the first one was scheduled. A month would close by itself just after
  midnight on the 1st and then sit there — correctly closed and never
  billed — until somebody opened the Billing Console and pressed Generate
  for each company in turn.

  An hourly run now bills every closed period that has no invoice yet. It
  looks for *periods without an invoice* rather than *periods closed
  recently*, so a month missed during an outage is picked up on the next
  run instead of staying unbilled until somebody notices. A backlog is
  cleared oldest month first, and one company's problem no longer stops
  everybody else's invoices — the failure is logged with the company's
  name and the run carries on.

  Invoices come out **issued**, with their number, not as drafts. A draft
  is an unfinished invoice: it has no number, so a customer has nothing to
  quote and nothing to pay against, and the payment clock never starts. A
  draft left behind by an interrupted run is picked up and issued on the
  next one rather than sitting there forever.

- **Customers who used nothing now get an invoice too.** Billing periods
  were only created when a company first did something billable, so a
  company that was quiet all month had no period — and therefore no
  invoice, no record, and nothing to show for the month. They now receive
  a proper zero invoice like everybody else. Somebody looking for last
  month's invoice can now tell "you owed nothing" apart from "we forgot
  you".

  Two groups are deliberately left out: closed accounts, and customers who
  signed up after the month ended — a July bill arriving for somebody who
  joined in August would be alarming rather than reassuring.

- **Three billing jobs were failing roughly every other run.** Period
  closing, the collections and dunning sweep, and the daily billing
  figures each hit a database-connection fault on alternate runs — 132
  failures in the last two days alone. Nothing looked broken, because
  every one of those jobs is safe to repeat: a failed run simply left its
  work for the next successful one. Months still closed and overdue
  notices still went out, but late and unpredictably.

  All three are fixed, and the platform now checks for the mistake
  automatically — it is the kind that only shows up on a job's *second*
  run inside a worker, which is why it survived three separate times.

### Added

- **Business rules now live in one place — the Policy Engine.** Questions
  like "may AI answer this?", "may this conversation be routed?", "may an
  agent pick it up?" and "may it skip the queue?" used to be answered
  wherever they happened to be needed. A rule written in one module and
  forgotten in another means the platform behaves differently depending on
  which door a conversation came through. Now every module asks the same
  engine, and gets the same answer.

  **Every answer explains itself.** Not a yes or no — a decision with a
  reason and, crucially, a **source**: the Customer Context, the service's
  configuration, the company's settings, the state of the conversation.
  "Denied" sends an administrator hunting; "denied, from the Customer
  Context" tells them which screen to open. Reasons come from a fixed list
  so the Routing Inspector can group and filter them.

  When more than one rule would say no, the reason shown is the one that
  stays true after the others are fixed. If a customer has asked for no
  automated messages *and* the company has AI switched off, the platform
  reports the customer's request — because switching AI back on will not
  make AI reply to that customer, and saying otherwise promises a fix that
  never arrives.

  Rules belonging to features that have not shipped yet — SLA pausing,
  automation, auto-close — are present and say so, reporting "this policy
  is not yet enforced" rather than inventing a rationale that reads like a
  real decision. They are there so future modules ask the engine instead of
  growing their own copy of a rule.

- **A conversation now runs inside an Execution Context.** One object
  carrying how the business behaves for this conversation, how this
  customer is treated, what is true of the conversation right now, and what
  the company permits. Resolved once at the start and passed to every
  module, so two modules can no longer disagree about the same customer.

  The service and customer contexts are **frozen at the version the
  conversation started with**. An administrator halving a response target
  at noon no longer rewrites the deadline of every conversation opened that
  morning — an agent watching a countdown would have seen it jump. Existing
  conversations continue as they began unless an administrator explicitly
  re-routes them; the console shows when a conversation is running on an
  older version, so a supervisor wondering why two conversations in one
  queue have different deadlines gets an answer.

  Customer versions are minted only when something that actually changes
  how a conversation is handled changes — tier, VIP status, language,
  contract, contact preference. Renaming a customer does not fork their
  history; promoting them to VIP does.

### Security

- **The company-wide AI switch can no longer be lost by omission.** It is
  the switch a compliance officer uses to guarantee no AI-generated content
  reaches customers. The AI policy refuses when it cannot confirm what a
  company allows, rather than treating silence as permission — so a module
  that forgets to supply it gets a refusal, not an unintended AI reply.
  "Switched off" and "switched on but never set up" are also reported as
  different answers, because they are different problems with different
  fixes.

- **Every issued invoice now has a proper PDF.** Download it, open it for
  printing, or send it to the customer by email — from the Billing Console,
  or by the customer themselves from their own billing page.

  It carries the Blink Engage mark, the invoice number, issue and due
  dates, the billing period, who it is billed to, the currency, every line
  with what was used, what was included, what was billable, the unit price
  and the tier that set it where one applies, then the subtotal, credits,
  payments and the outstanding balance. Credit notes issued against it and
  payments applied to it are listed. At the foot is our registered legal
  entity in English and Arabic, and beside the totals a QR code that
  identifies the document.

  It is A4, black on white, and made to be printed and filed.

  **Nothing on it is recalculated.** Every figure is read from what was
  written when the invoice was issued, so the same invoice reprinted years
  later says exactly what it said the day it was sent — even if the price
  has changed three times since.

  A draft has no PDF: it carries no number and has been sent to nobody. An
  invoice that was withdrawn or written off says so plainly at the top, so
  it can never be mistaken for one that is still payable.

- **Invoices in Arabic now read as Arabic.** The document is set in a font
  that carries the script, and Arabic is joined and laid out right to left
  rather than printed as disconnected letters. Company names in Arabic
  appear as names.

- **Credit notes are now made from invoice lines.** Choose the lines that
  were billed wrongly and how much of each to credit; the price comes from
  the line that was billed. The totals are shown before anything is
  issued, and they are worked out by the same code that writes the
  document — so what you approve is what the credit note says.

  You can no longer type an arbitrary amount. Every figure on a credit
  note traces back to a charge, which is what makes one explainable to an
  auditor six months later. Each line shows what was billed, what has
  already been credited and what is left, and a quantity larger than that
  is refused with the reason.

### Fixed

- **Two credit notes issued at the same moment could credit the same
  money twice.** A double-clicked button, or a client retrying, could put
  several credit notes through against one invoice — in testing, eight
  simultaneous requests credited $4,000 against a $500 invoice. Issuing a
  credit note now holds the invoice while it checks and writes, so only
  what genuinely fits can land.

- **Emailing an invoice to several people no longer fails silently.** If
  the mail server refused one address, the whole request failed, some
  people had already received it, and nothing was recorded. Each address
  is now attempted on its own, and what was sent and what failed are both
  reported and both written to the audit trail.

### Added

- **The Billing Console is now a finance workspace, not a settings page.**
  It opens on what the business earned rather than on a rate editor, and
  it has six sections that follow the way a finance day actually runs:

  - **Revenue** — billed, collected, outstanding, credit held and written
    off, for the period you choose, with a monthly run rate beside each.
  - **Invoices** — search every document across every company, filter by
    company, status, number or date, open one to see its lines, and export
    the result to a spreadsheet.
  - **Payments** — record money that arrived outside the payment
    providers, see where every amount was applied, reverse an application
    that went to the wrong document, and issue a refund.
  - **Ledger** — run one company's account down movement by movement with
    the balance carried alongside, and see the books for each currency
    with the proof they balance.
  - **Collections** — how overdue everything is, who is behind, and what
    happens to them next. Run the notice sweep by hand, reinstate a
    company, or mark one that must never be suspended automatically.
  - **Company billing** — one customer's standing, what they owe, what
    they are running up this month and every invoice they have had.

  Every action that changes money is recorded permanently with who did it
  and why. Withdrawing an invoice, crediting one, writing one off,
  reversing a payment and refunding all ask for a reason first — six
  months later that sentence is the only explanation anybody has.

  **Dollars and dinars are never added together.** Each currency gets its
  own figures, its own totals and its own set of books, because nothing
  converts between them and a combined number would mean nothing. The
  console is built so that such a number has nowhere to appear.

  The monthly figure always says how it was worked out. Blink Engage bills
  for what you use and sells no subscriptions, so there is no fixed
  monthly revenue to report — the figure is what was earned over a window,
  scaled to thirty days, and it says so. With less than a week of history
  it says that instead of guessing.

- **The whole Billing Console is available in Arabic**, right to left,
  including every explanation of what a figure means and why an action is
  or is not available.

- **Invoices can be exported to a spreadsheet.** The export follows what
  you searched for rather than what fits on the page, and if the result is
  larger than one file can hold it tells you before you download — and
  again in the file's own name, so a short file is never mistaken for a
  complete one.

### Fixed

- **A dinar invoice is no longer rounded to two decimal places.** The
  dinar settles in fils — three places — and totals were being rounded as
  though they were dollars. A charge of 1.775 JOD was billed as 1.780.
  Every dinar invoice and credit note now rounds to the dinar.

- **Withdrawing an invoice now withdraws its money too.** Cancelling an
  issued invoice marked the document withdrawn but left the amount
  standing in the books as still owed and still earned — permanently, with
  nothing able to clear it. Cancelling now reverses both, and the books
  reconcile afterwards.

- **"Outstanding" now means the same thing everywhere.** Invoice search
  counted drafts, withdrawn documents and written-off debts as money still
  owed, so its headline figure disagreed with collections, with the aging
  report and with the ledger. A draft was never billed, a withdrawn
  invoice does not exist and a written-off debt is not being chased —
  none of them is outstanding.

- **A customer's own name can no longer run as a formula in a
  spreadsheet.** A company name beginning with `=` was written into the
  invoice export unchanged, where Excel would execute it. Names are now
  neutralised — still readable, no longer executable. Amounts and dates
  are untouched, so the figures the export exists to carry are unchanged.

- **A statement for a company that does not exist now says so**, instead
  of showing a page of zeroes that reads as "they owe nothing".

- **The financial audit trail now tells you how many records matched.**
  It offered paging but returned no total, so a reader could not tell
  "that is all of them" from "there are four hundred more" — on the one
  screen whose entire purpose is completeness.

### Added

- **Connecting a channel is now a guided flow you can finish in a couple
  of minutes.** Press Connect channel, pick what you want to connect, and
  follow the steps. Blink Engage asks only for what it actually needs,
  checks it before saving, and tells you plainly what is wrong if
  something is.

  Where you have to do something outside Blink Engage — send `/newbot` to
  BotFather, for instance — the exact text is on screen with a copy
  button. That is the moment setup usually loses people, and it is the
  moment nobody should need a provider's documentation.

  You can also connect several at once: approving Meta once connects
  WhatsApp, Messenger and Instagram together.

  Each channel shows how finished it is before you connect it, and one
  that is being retired or is temporarily unavailable says so rather
  than failing halfway through.

  The old credential form is still there under **Advanced setup**. It is
  the only path on an installation with no provider app, and the fallback
  when a sign-in cannot be completed.

- **Everything the setup flow says is now available in Arabic**, including
  every check, every fix and every explanation — 374 pieces of copy in
  both languages.

- **Connecting a channel is now a guided flow, not a settings form.** Pick
  what you want to connect, follow the steps, done — no provider
  documentation, no hunting for an id in someone else's dashboard. Web
  Chat connects in one click; Telegram asks for one value and tells you
  the command to get it; Email checks your mail server before saving and
  says plainly if it will send but never receive.

  Before saving anything, the flow runs a **check** and shows what it
  found in your terms — what is wrong, how serious, and what to press.
  A wrong value sends you back to the field, not to a support article.
  Problems that would stop the channel working block it; things merely
  worth knowing do not.

- **Channels can now certify themselves.** One command runs a channel
  through every behaviour its connector claims — sign in, send, receive,
  media, read receipts, typing, webhook delivery, reconnect — and scores
  what actually happened. Each step reports pass, fail, warning, skipped
  or not supported, with how long it took and what came back.

  **The score cannot be given out; it is only ever earned.** There is no
  field to set it. Three rules keep it meaningful: something a channel
  never claimed to do is not held against it, so an honest connector
  never scores worse than a boastful one; something that did not actually
  run does not count in its favour, and a run that covered too little is
  reported as inconclusive rather than as a high score; and a single real
  failure keeps a channel out of "production ready" however good the
  arithmetic looks.

  **Nothing in a certification run messages a real customer.** Anything
  that would put a message in front of somebody is skipped unless you say
  explicitly where to send it. Steps that would disconnect or reconnect
  the channel are off unless you ask for them by name.

  Alongside it: which platform, connector and provider API version a
  channel is on, when it was last verified, and when its provider
  retires that API version — so a channel drifting out of date is visible
  months before it stops working, rather than the week it does.

- **Every channel now says how finished it is, what version it is, and
  exactly what it can carry.** A channel in preview or beta says so; one
  being deprecated warns before you connect a new one; one an
  administrator has switched off or put into maintenance says that
  instead — and existing channels keep working through all of it, because
  taking a channel away from someone receiving messages on it is a
  decision somebody makes on purpose, not a side effect.

  The **feature list is now exact, including which direction each
  feature works in**. SMS receives photos and cannot send them, so it
  says so rather than showing one tick that would be wrong whichever way
  you read it. WhatsApp does not claim typing indicators, because it
  does not have them. Nothing claims voice or video calls, because
  nothing does them yet.

  And a connector that needs a newer Blink Engage than you are running
  is not offered at all — with a note explaining that, so an
  administrator finds out before a customer meets a setup flow that
  cannot finish.

- **Channel diagnostics for support.** One screen answering "why is this
  not working" — whether the credentials still work, whether the
  provider is sending us anything, which permissions are granted, what
  last succeeded, what last failed, how much is waiting to retry — with
  a one-click fix beside anything fixable.

  Anything that has not actually been measured says so, rather than
  showing a reassuring tick. That distinction is the whole point: a
  green light nobody earned sends support looking in the wrong place
  with more confidence than they started with.

- **Every channel now describes itself, and the setup screen is generated
  from that description.** A connector declares its name, icon, category,
  what it needs, what it will find, what it will check, what it can
  repair and what it can carry — and the connection flow is built from
  the declaration. Nothing about connecting a channel is written into
  the screen.

  Which means adding a channel adds a screen. A developer implements the
  connector, its description, its validation and its repairs; the picker
  entry, the form, the account list, the checks and the repair buttons
  all appear on their own.

  Problems found while connecting are reported as **structured results**
  rather than messages — missing permission, invalid token, expired
  credentials, webhook not registered, unsupported API version, business
  verification required — so each is explained in the customer's own
  language, and whether something blocks setup is decided once for every
  channel rather than per channel.

- **Channels are now built on a connector framework.** Every channel
  declares what it can do — sign in with the provider, discover your
  accounts automatically, register its own webhook, check its own health
  — and the flow is *built from those answers*. One flow, every channel.

  This is why WhatsApp, Messenger and Instagram share a single sign-in:
  they are one provider, so approving once connects all three. And it is
  why adding Slack, Teams, RCS or WhatsApp's successors later is one new
  file rather than a new screen — nothing above the connector layer knows
  what a WhatsApp is.

  Where a provider sign-in is not available — a self-hosted installation
  without provider credentials — the same flow falls back to a guided
  manual path and explains why, rather than hiding the channel. Every
  channel stays connectable everywhere.

- **A separate Billing Console.** Pricing has moved out of the Platform
  Console into its own area at `/platform/billing`. Running the
  installation and running the revenue system need the same authority
  but are not the same job, and each now has its own screen and its own
  navigation instead of sharing one crowded bar. A link in each header
  crosses to the other. A company's billing page moved with it; the
  **Billing** button on the company list goes to the new address.

  Invoices and collections will land here as they get screens — the
  engine behind them already exists.

- **Prices are now edited in the console.** The pricing screen has a
  Usage Metric Pricing Editor: pick a metric, choose how it charges,
  build its tier table, set what is included free and any minimum, and
  see what a sample month would cost before saving. Changing a rate no
  longer needs a database migration.

  The editor is generic — it takes the metric as a parameter and builds
  every field from what the server says. The day a token or a
  phone-minute meter ships, it prices there with no change. Models that
  are built but not yet offered are shown greyed out with a "coming"
  label, so an operator can see what is arriving without configuring a
  price that would never charge.

  Two rules are enforced by the shape of the form rather than by an error
  after the fact: the top tier step has no upper bound and cannot be
  deleted, so no customer can ever exceed the table and find no price;
  and switching a metric from flat to tiered carries its current rate
  into the first step, so changing how a price is *structured* never
  silently changes what it *charges*.

  **The preview is calculated by the billing engine, not the browser** —
  the same calculation that produces the invoice. A second
  implementation in the console is how a preview ends up disagreeing with
  a bill.

  Metric names and pricing model names are now translated, so the Arabic
  console reads as Arabic rather than showing English names in a
  right-to-left page.

- **Pricing simulation.** A new endpoint prices terms that were never
  saved, writing nothing. It answers both "what would this rate charge?"
  — which is what the editor's preview asks — and "what would last month
  have cost under this table?", given a closed month's own recorded
  usage. Comparing pricing scenarios no longer means changing a price to
  find out.

### Fixed

- **Writing off a bad debt now ends the pursuit of it.** Abandoning a
  receivable used to change only the books: the invoice stayed overdue —
  correctly, it genuinely was never paid — and overdue is what the
  reminder sequence runs on. So a written-off invoice kept sending the
  customer reminders on the same schedule as a live one, and kept their
  account suspended, indefinitely. There was no way out but editing the
  database.

  A written-off invoice is now skipped by reminders and by suspension,
  and a company suspended over a debt that has been written off is
  released. It stays unpaid and overdue on the record, because that is
  what happened. And a customer who later pays it can still pay it —
  writing a debt off decides whether we chase it, not whether we accept
  the money.

- **Prices could not be set in a second currency, and the pricing screen
  broke once one existed.** Blink Engage bills in dollars and dinars, and
  a price in each is normal — nothing converts between them. But the
  system treated a metric as having one price rather than one per
  currency, so setting a dinar price was refused because a dollar price
  existed, and the pricing screen refused to load at all, reporting the
  two as a contradiction.

  Prices are now set, read and checked per currency throughout. The
  pricing screen has a currency selector, and a company's own page always
  shows the currency they are actually billed in.

- **A metric priced in only one currency was reported as fully priced.**
  The coverage check called a metric covered when it had any price at
  all, so a metric priced only in dollars looked healthy while a
  Jordanian customer could not be billed for it — a gap that would have
  surfaced as an unpriced month. It now checks each currency that a real
  company bills in, and stays quiet about currencies nobody uses.

### Changed

- **Metering and pricing are now formally separate.** Measuring what
  happened and deciding what it costs are different jobs, and they no
  longer share anything. A usage record holds the company, the metric,
  how much, when, and what it refers to — and no amount, no currency and
  no rate. The meter is built without a pricing engine at all: billing
  could be re-priced from scratch and every measurement would still
  stand.

  This is what makes it possible to re-price history without touching a
  single record, to try out a rate before committing to it, and to give
  one customer negotiated terms later without rewriting what was already
  measured.

  **Measurements are now immutable in the database itself**, not only in
  the code. Usage records join billable events in refusing to be edited
  or deleted at all. A correction is a new, attributed entry — never a
  quiet change to what was recorded. And a month that has been closed
  records the exact instant its prices were resolved, so re-running it
  years later reaches the same numbers.

- **Pricing is now generic across usage metrics.** Blink Engage will bill
  more than messages — AI tokens, generated images, transcription and
  speech minutes, storage, bandwidth, API requests, webhook events, phone
  minutes, SMS, email, push notifications, agent and bot seats, and a
  custom dimension. All twenty are now declared in the catalogue with
  their unit and their **billing type**, which decides how a period is
  totalled: counted events, continuous amounts, sampled levels, or seats.
  That last distinction is written down before any of them ships because
  getting it wrong is not a rounding error — a seat totalled like a
  message bills thirty times the seats.

  Declaring a metric does not make it chargeable. Each still needs its
  meter before a price can be set on it, so nobody can configure a rate
  that quietly charges nothing.

  **How a price charges is now part of the price.** A rate carries its
  pricing model, its tier table, the quantity included free and any
  minimum charge — so the same metric can be flat on one plan and tiered
  on another, in each currency, effective-dated independently. Flat and
  volume tiers are available today; graduated tiers and fixed monthly
  fees are built and tested but not yet offered; packages, committed
  usage and subscription plans are designed into the schema and refused
  until the terms behind them are decided. Everything that charges — the
  invoice, the dashboard estimate, an operator's preview — now goes
  through a single calculation, so they cannot disagree.

  The free allowance moved from code onto the price, where it belongs: it
  varies by plan and by negotiation. Nothing changes today — the message
  metric keeps its 100 free messages a month, now recorded on its rate,
  and a price that sets no allowance still gets the metric's own.

  **Nothing changes functionally in this release.** Billable messages
  remain the metric, the tiers and totals are identical to the last
  release, and every existing price keeps charging exactly as it did.
  This is the architecture the pricing editor will be built on.

- **Billing now counts messages, not conversations.** The unit is a
  **billable message**: any customer-facing message on any channel —
  inbound or outbound, written by a person, the AI or an automation, in
  any medium. A photo is one message. Internal notes, system messages,
  assignment changes, tags, read and delivery receipts and typing
  indicators are never charged, because none of them deliver anything to
  a customer.

  Billing is **channel-agnostic**: a message costs the same on WhatsApp,
  Telegram, web chat, email, SMS or Instagram. Channels remain a
  dimension for analytics — the billing page shows a period's messages
  broken down by channel, by who sent them (customer, agent, AI
  Autopilot, AI-assisted, automation) and by direction — but those are
  counts, never per-channel prices. The rate card also shows the volume
  table itself, so "why am I paying this rate?" is answerable on the
  page rather than by asking.

  **Pricing is now tiered by volume.** The first 100 messages each month
  are free; beyond that the rate is chosen by the month's own total —
  0.002 up to 200 messages, 0.0015 up to 500, 0.001 above that (JOD at
  the same ratio as the existing rates). One rate applies to every
  chargeable message, so a busier month makes *every* message cheaper
  rather than only the ones past a boundary. Operators can still override
  the price per company or per plan. Note the arithmetic: crossing a
  boundary can lower the bill outright — a 501-message month costs less
  than a 500-message one — which is inherent to volume pricing and always
  in the customer's favour.

  The dashboard charges exactly the way the invoice does, so the estimate
  a customer watches all month and the bill they receive agree to the last
  decimal, including which tier applied.

  **Charging per conversation, per AI-assisted reply and per Autopilot
  reply has been retired.** An AI reply is one billable message; the AI's
  involvement is recorded for analytics instead of charged twice. Nothing
  historical changes: those metrics, their prices, their closed periods
  and their issued invoices all stay exactly as they were and still
  reprint, because an invoice that cannot be reprinted cannot be
  defended.

- **Every billable message now has an immutable record behind it.** One
  event per message, saying which message, on which channel, in which
  conversation and from whom — so a question about an invoice can be
  answered message by message rather than with a total. A message is
  charged exactly once even when the system sees it several times, and the
  database enforces that rather than trusting the code to. Messages that
  arrive after a month has closed are recorded and reported rather than
  billed into the wrong month.

- **Jordanian companies are now billed in dinars.** Signup asks for a
  country and tells you which currency you'll be billed in before you
  commit — Jordan means JOD, everywhere else USD — and it can't change
  afterwards, because re-denominating an invoice that has already been
  sent isn't something anyone should be able to do. **JOD is handled at
  three decimal places**, not two, so a price of 0.035 dinars stays
  0.035 rather than rounding to 0.04 and overcharging by 14% on every
  conversation. Prices, invoices, payments and the ledger all stay in the
  company's own currency throughout, nothing is converted, and the trial
  balance is reported as one set of books per currency — because adding
  dinars to dollars produces a number that means nothing. Existing
  companies are unchanged and stay on USD.

- **Every financial movement is now recorded in a double-entry ledger**,
  and balances are answered from it rather than from a column on an
  invoice. Issuing an invoice, crediting one, receiving a payment,
  applying it, reversing it, refunding, a chargeback, a write-off and
  manual adjustments each post a balanced entry naming both accounts it
  moved value between. Entries can never be edited or deleted — a
  mistake is corrected by posting the opposite entry — and the database
  itself refuses any attempt. New reports show the **trial balance**
  (proof the books balance), each company's position, and a
  **reconciliation** confirming the figures on invoices still match the
  ledger. Existing invoices and payments were reconstructed into entries
  so the ledger is correct from its first day, and every reconstructed
  row is labelled as such.

- **The navigation sidebar now sizes itself to its labels** instead of a
  fixed width, so nothing is clipped and no space is wasted. This matters
  most in Arabic, where the same menu needs a different amount of room —
  "أداة اتفاقيات مستوى الخدمة" no longer runs out of space where the
  English "SLA Builder" left the column half empty. The dividing line
  runs the full height of the page in both languages and both themes.

### Added

- **Push notifications reach agents on their phones**, including when the
  app is closed. Until now the only live delivery was a browser
  connection, which a phone drops within seconds of the screen going
  dark — so a new conversation could sit unanswered with nothing to show
  for it. An agent's device is registered when they sign in on it and
  forgotten when they sign out, several devices per person are fine, and
  a phone that no longer accepts notifications is dropped automatically
  rather than being pushed at forever. **Push is its own switch** in
  notification preferences, per notification type, separate from email
  and from browser alerts: wanting an alert on screen while you work but
  not on your phone at 3am is a setting, not a compromise. Notifications
  older than fifteen minutes are never pushed — a "customer is waiting"
  alert arriving three-quarters of an hour late is worse than none, and
  the same rule means switching push on for the first time never floods
  anybody with history. One transport covers both Android and iOS.
  Delivery requires Firebase credentials; without them nothing changes
  and nothing breaks — devices still register, notifications still arrive
  everywhere they did before, and filling the credentials in starts
  delivery with no redeploy.

- **A billing dashboard for every company**, so an invoice at the end of
  the month is never a surprise. Within a few seconds it answers what you
  spent today, what you have spent this period, what is driving the cost,
  what your invoice is expected to be, and whether you need to do
  anything. Estimated charges refresh by themselves every 45 seconds while
  the page is open — no reloading to find out whether a number moved.

  The projected invoice is **never shown without saying how it was
  calculated**. Three methods are available — a rolling 7-day average
  (the default), the current daily average, and the current pace including
  today — and you can switch between them and see what each one predicts.
  When a period is too young for the rolling average to mean anything,
  the projection falls back to the daily average and says so rather than
  claiming a method it did not use. Early in a period, when there is
  genuinely nothing to extrapolate from, it says that too instead of
  showing a misleading zero.

  Daily cost and usage charts (7 days, 30 days, or the current period)
  read from a new immutable daily summary rather than being recomputed
  from raw events on every page load. **A day that has closed never
  changes again**: today's figures update as usage arrives, and once the
  day is over its row is frozen — so a price change tomorrow cannot
  silently rewrite what you were shown last Tuesday. Each day is priced at
  the price that applied *on that day*, exactly as the invoice will show
  it. Every day's projection is recorded as it stood, so "what was I told
  on the 12th?" has an answer.

  Estimates are net of your **free monthly allowance**, so what you watch
  all month is what you will be charged — the first 100 conversations
  each month show up as used but cost nothing, with the free and
  chargeable amounts side by side so a small bill is explainable rather
  than merely surprising.

  Estimated charges and issued invoices are kept visibly apart. Everything
  derived from usage is labelled an estimate; below a clear divider,
  issued invoices remain the only official statement of what is owed, with
  their frozen lines available on demand. Draft invoices are not shown at
  all. The page also shows your rates and where each comes from (a
  negotiated rate, your plan, or the standard rate), your free monthly
  allowance and how much of it is left, the payment methods actually
  available to you, the terms you are billed under, and a timeline through
  to the date service would be suspended if an invoice went unpaid —
  the one date that is hardest to work out and worst to discover by
  surprise. Available to owners and administrators.

- **We can now tell how long each request actually took, and which
  database queries are responsible.** Until now the access log recorded
  that a request happened but not how slow it was, and the database kept
  no per-query statistics — so "the application feels slow" could only be
  answered by guesswork. Every request is now logged with two timings: the
  total time the user waited, and the time the backend alone spent. Those
  two numbers separate a slow application from a slow connection, which a
  single number cannot. Alongside them, PostgreSQL now keeps per-query
  execution statistics, so the slowest queries can be listed directly
  instead of inferred. This is measurement only — no behaviour changes,
  and nothing about how requests are served is affected.

- **Facebook Messenger and Instagram conversations now show the person's
  name instead of a long number.** These two channels are unlike WhatsApp:
  Meta's webhook tells us only an internal sender id, never a name, so
  every new contact arrived in the inbox labelled with a seventeen-digit
  number and stayed that way. Their name is now looked up and used for the
  customer record. Where the name genuinely can't be read — Meta refuses
  it for people whose profile the app has no access to, and for nearly
  everyone while an app is still in development mode — the conversation
  still arrives exactly as before, just labelled with the id; a missing
  name is never allowed to cost a customer's message. Existing
  conversations keep whatever name they were created with; this applies to
  contacts seen from now on.

- **Images, video and audio now play inside the conversation.** A photo a
  customer sends appears in the thread rather than as a file to download;
  video and voice notes play in place. Clicking any of them opens a
  full-screen viewer where the arrow keys move between everything in the
  conversation, Escape closes, and Download and Open-in-new-tab are always
  one click away. Media loads only as you scroll near it, so opening a
  conversation with dozens of photos no longer downloads all of them at
  once — and each one reserves its exact shape beforehand, so the thread
  never jumps under your cursor as pictures arrive. Formats your browser
  can't display say so and offer to open them in a new tab, instead of
  showing a broken image that looks like the customer sent a corrupt file.

- **A data-reset script for a single company's billing records.**
  `scripts/reset_company_billing.sql` clears one company's invoices, credit
  notes, payments, ledger entries, usage snapshot and billing periods while
  keeping the company itself, its people and its conversations — a narrower
  tool than the company purge below it. It exists because a company's
  billing currency is fixed once it has been billed: correcting a
  development tenant that was set up in the wrong currency means removing
  the documents in the old currency first, so that nothing is ever
  re-denominated. Like the purge it is deliberately a separate, named
  script rather than anything reachable from the product, it runs as a
  single transaction, it restores the database's immutability protections
  before committing, and it refuses to finish — changing nothing — if it
  finds it has touched a row belonging to any other company.

- **A script that puts real names on Messenger and Instagram contacts
  saved before names were looked up.**
  `scripts/backfill_meta_customer_names.py` finds every contact on those
  channels still labelled with the raw sender id and replaces it with the
  person's name. It only touches a record whose name is still *exactly*
  that id, so a name an agent corrected by hand is never overwritten, and
  it reports what it would do until run with `--apply`. Contacts whose
  profile Meta won't disclose are listed and left as they are.

- **Two data-reset scripts for development installations.**
  `scripts/purge_companies.sql` removes every company except one, and
  `scripts/purge_stale_cache.sh` clears the sessions and tokens left
  behind pointing at things that no longer exist. Both are deliberately
  separate, named scripts rather than anything reachable from the product:
  the first genuinely deletes invoices and ledger entries, which the
  database is otherwise built to refuse. The purge runs as a single
  transaction and verifies itself before committing, so it either
  completes cleanly or changes nothing, and it refuses to run at all if
  the company you asked to keep doesn't exist.

- **A Billing screen for each company** in the platform console, reached
  from the Companies list. It shows what the company is charged, **where
  each price comes from** — global default, pricing profile, or a
  company-specific override — the dates each price applies between, and
  any prices that were overridden. You can set a company's own price,
  move it onto a different pricing profile, and **ask the pricing engine
  what it would charge at any moment in time**, getting back the same
  answer a closing month will use. Every change is listed with who made
  it, when it took effect and why, and nothing in that list is ever
  deleted. Prices are shown in the company's own currency at its own
  number of decimal places.

- **Read-only platform accounts.** A platform operator can now be given
  access to look without the ability to change: they see every screen and
  the full history, including the pricing preview, but the controls are
  disabled and the server refuses the change even if something got past
  the screen. Useful for anyone reviewing what customers are charged who
  shouldn't be able to alter it. Existing operators are unaffected.

- **New workspaces now confirm their email address**, and get **100
  free conversations every month**. After signing up you can sign in and
  look around straight away, but sending messages, connecting channels
  and inviting people wait until you follow the link we email you — with
  a banner across the top that resends it if it never arrived. Clicking
  the link twice is fine; it says so rather than claiming the link is
  broken. Every company then gets its first 100 conversations each month
  at no charge, and pays its normal rate beyond that. Invoices show all
  three numbers — what you used, what was included, and what was
  actually billed — so a bill for 50 conversations out of 150 explains
  itself. Existing companies and existing invoices are untouched.

- **The email server is now configurable from the platform console**,
  under a new **Email** tab. Previously the mail server could only be
  changed by editing the server's configuration files and redeploying.
  Set the address, port, encryption, sender name and credentials, and
  **send a test message** to confirm it works — a real email, not just a
  connection check, because a server can accept a connection and still
  refuse to send. If it fails you are shown exactly what the mail server
  said, so "the password is wrong" doesn't look the same as "the address
  is wrong". The password is stored encrypted and never shown again.
  Existing installations are unaffected: settings entered here override
  the server configuration, and **Reset to server configuration** always
  puts it back.

- **Customers can now pay their invoices, and unpaid invoices are chased
  automatically.** Invoices can be paid by **PayPal** or recorded as
  **bank transfers**, and the two are treated identically everywhere
  afterwards — an enterprise customer paying by wire gets the same
  receipt, the same allocation and the same audit trail as one paying by
  card. Paying twice is impossible: if PayPal delivers the same
  notification more than once, or a customer double-clicks "Pay", the
  money is taken exactly once. If a notification from PayPal goes
  missing entirely, the system asks PayPal directly within twenty
  minutes rather than waiting to be told — a customer who has paid never
  drifts towards a suspension because a message was dropped in transit.
  If a card is declined, the customer is told what PayPal said
  ("instrument declined") rather than a bare "payment failed".

- **Overdue invoices now follow a published reminder sequence.** A
  courtesy note three days before the due date, one on the day, then
  reminders at three, seven and fourteen days late, and suspension at
  twenty-one — which is the full Net 21 payment window *plus* the entire
  sequence of warnings before anything is cut off. Each reminder is sent
  **once**, no matter how often the system checks; and if the system is
  down for a week, the reminders it missed still go out in order rather
  than being skipped, so a suspension is never the first thing a
  customer hears about.

- **Billing suspension is now separate from compliance suspension.** A
  company behind on payment and a company suspended by an operator are
  different situations with different remedies, and they are now tracked
  separately: paying an invoice can no longer quietly lift a suspension
  an operator imposed for another reason. Anyone who can see the bill
  keeps access to a workspace suspended for non-payment — locking out
  the people who can pay leaves nobody able to pay — and the message
  they see says exactly that, rather than sending them to their
  administrator, who is usually the person reading it. Enterprise and
  government accounts on long payment cycles can be **exempted from
  automatic suspension**; they still receive every reminder, and each
  time enforcement is withheld it is recorded.

- **Payments can be reversed and refunded.** A payment matched to the
  wrong invoice, a bounced transfer or a chargeback can be reversed with
  a stated reason — the record is kept, never deleted, and the invoice
  correctly goes back to being unpaid (still marked overdue if it
  already was; a reversal doesn't make a late invoice punctual).
  Refunding money that is still settling an invoice is refused outright,
  so an invoice can never be left marked "paid" with no money behind it.
  Every reversal, refund and failed refund attempt is recorded.

- **Billing standing at a glance** for the platform operator: which
  companies are behind, how much is outstanding, and the date the next
  reminder — or the suspension — is due.

- **The installation now runs under a real domain name with a trusted
  HTTPS certificate** (`engage.blinkconnected.com`), replacing the
  self-signed certificate tied to the server's bare IP address. This is
  what unblocks the Meta-platform channels — Facebook Messenger,
  Instagram and WhatsApp all refuse to deliver webhooks to an address
  whose certificate isn't signed by a recognised authority, so none of
  them could be connected before. The certificate is issued by Let's
  Encrypt and **renews itself automatically** roughly every 60 days,
  with no interruption to the running site: renewal is proved over
  plain HTTP through a dedicated path nginx serves straight from disk,
  and nginx is then reloaded gracefully rather than restarted, so
  in-flight requests are never dropped. The previous self-signed
  certificate is left in place as the fallback for a local checkout
  that has no domain.

- **Super administrator.** A platform operator account that manages the
  whole installation: see every company with its user, agent and
  conversation counts, search and filter them, and **suspend or
  reactivate** any company. Suspending blocks that company's people from
  signing in immediately — including anyone already signed in — with a
  clear "this workspace has been suspended" message rather than a
  misleading password error. Their customers' messages keep arriving
  while suspended, so nothing is lost when the account is reactivated.
  Super administrators deliberately **cannot read any company's
  conversations, messages or customers**; they manage accounts, not
  content. They are created from the server command line, never through
  the app.
- **Super administrators can now control which features each company
  gets.** Features (AI, ERP, Workflows, Knowledge Base, SLA, and report
  downloads) can be turned on or off for any individual company — useful
  for a pilot or a negotiated contract. Anything a company isn't
  entitled to disappears from their navigation instead of failing when
  opened. **Nothing changes for existing companies:** with no overrides
  set, every feature stays on exactly as before.
- **Financial audit trail.** Every invoice, credit note, payment and
  allocation now records an immutable history: what happened, to which
  document, what state it moved from and to, who did it, when, and why.
  Actions taken automatically by the system are marked as such rather
  than appearing to have no author. The record can't be edited or
  deleted, and it's the single place to look when investigating a
  charge.
- **Related changes are linked together.** Everything that happens
  because of one action — allocating a payment settles an invoice, for
  example — shares a correlation ID, so "what else did that change?" is
  one lookup instead of guesswork from timestamps. Callers can supply
  their own ID and it's echoed back on every response.
- **Invoice engine.** A closed billing month can now be turned into an
  invoice, with a human-readable number (`INV-2026-000001`) assigned
  when it is issued. Invoice lines are copied from the frozen usage
  snapshot, so an invoice shows exactly what was measured and what it
  cost at the time — changing a price afterwards never alters it.
- **An issued invoice can never be edited.** Corrections are made by
  issuing a **credit note** against it, so both the original document
  and the correction exist for anyone reconciling them later. A reason
  is always required, and a credit can never exceed the invoice.
- **Payments are recorded independently of invoices**, then allocated,
  so one bank transfer can settle several invoices and an overpayment
  simply stays as a credit balance.
- Invoices move through a strict lifecycle — Draft, Issued, Paid,
  Overdue, Cancelled — and anything that lifecycle doesn't allow is
  refused with a clear explanation rather than silently accepted. An
  invoice with a payment against it can't be cancelled; it gets a credit
  note instead.
- **Usage engine.** Conversations are now metered automatically as they
  happen, and each company's usage accrues into a monthly billing
  period. At the end of the month the period is closed and **frozen**:
  the quantity, the price at the time, the subtotal and which price was
  used are all recorded permanently. A later price change can never
  alter a closed month — an invoice built from a closed period shows
  exactly what was charged, however many times the price changes
  afterwards.
- **A conversation is never billed twice**, even when the system retries
  delivering the same event, which it does routinely.
- **Usage never moves between months.** It is counted against the month
  it actually happened in, and usage arriving after a month has closed
  is refused and flagged rather than quietly added to the current month.
- Usage with no price set is still recorded and shown as unpriced,
  rather than silently disappearing from the bill.
- Billable metrics now carry a version, so if what a metric counts ever
  changes, everything already measured and billed keeps the definition
  that produced it.
- **Pricing engine.** Super administrators can now set what companies
  pay per unit of usage, from a new **Pricing** page in the platform
  console. A price can be set globally, for a reusable tier (Startup,
  SMB, Enterprise, Government, Partner), or for one individual company —
  and the most specific one always wins, automatically. The page shows
  which of the three a price came from, and what it overrode.
- **Changing a price never re-prices the past.** Every price carries the
  date it takes effect, and the old one is kept rather than overwritten,
  so usage is always charged at the price that applied when it happened.
  A previously issued bill can never change because somebody edited a
  price today.
- **Every pricing change is recorded permanently** — the old value, the
  new value, who changed it, when, from what date, and why. This history
  is never deleted, and includes the very first price the system was set
  up with, so there is no gap at the beginning.
- Prices are kept to six decimal places, so genuinely small per-unit
  prices (a conversation at $0.0005) are exact rather than rounded away.
  A metric with no price set shows as "Not set" rather than "$0.00", and
  the page warns when something measurable has no price at all.
- Two administrators editing the same price at once no longer silently
  overwrite each other — the second is told the price changed and asked
  to re-read it.
- **All money is handled to six decimal places and rounded only once, at
  the end of a calculation.** Usage prices are genuinely sub-cent — a
  conversation might cost $0.0005 — and rounding those to cents along the
  way would bill nothing at all for ten thousand of them. Amounts are
  never stored or calculated as floating-point numbers, so a total can
  never disagree with the lines that make it up.
- Prices and totals are shown consistently across the product from a
  single currency setting (US dollars for this release). A price that
  hasn't been set shows as "—" rather than "$0.00", so "not set" is
  never mistaken for "free".
- **Platform console.** A super administrator signs in at the normal
  sign-in page and is taken straight to a console listing every company
  with its user, agent and conversation counts, where each can be
  suspended or reactivated in one click (with a confirmation explaining
  exactly what that does). Previously signing in as a super
  administrator showed a blank page, because the app had no screen for
  someone who belongs to no company.

### Changed

- **The conversation workspace now gives the chat the whole width.**
  Customer details used to sit in a permanent panel on the right, taking
  up space at all times for information agents only need occasionally.
  They now open on demand from the **⋮** menu in the conversation header
  ("Conversation details") and slide in over the conversation, so
  opening or closing them never resizes or re-wraps the messages. On a
  1440px screen the message thread goes from 420px to 700px wide.
- The main navigation sidebar is now narrower (200px), leaving more room
  for the page beside it.

### Removed

- **Subscription plans and recurring PayPal billing.** Blink Engage is
  moving to usage-based pricing: you pay for what you actually use, with
  no monthly plan, no seat licensing, and no limits on agents,
  departments or channels. The subscription model built earlier in this
  unreleased cycle has been removed rather than left running alongside
  the new one. No installation ever had it released, and which features
  each company gets is unaffected.

### Fixed

- **The Inbox now names the channel a conversation came in on**, instead
  of showing only a coloured icon. The icon told you it was WhatsApp; it
  didn't tell you *which* WhatsApp — and a company running a support
  number and a sales number, or two Telegram bots, couldn't tell the two
  apart without opening the conversation. The Channel column now shows
  the channel's own name next to its icon, the same name it's given on
  the Channels page. If a channel has since been deleted, its past
  conversations say "Unknown channel" rather than showing a bare icon.

- **Voice notes from customers were being silently thrown away.** Audio and
  video weren't on the list of accepted file types, and inbound messages
  are checked against that same list — so when a WhatsApp customer sent a
  voice note, the agent simply never saw the message. Audio and video are
  now accepted, including the exact formats WhatsApp and iPhones send.
  Note that the 25 MB attachment limit still applies, and phone video
  often exceeds it.

- **The pricing history showed the wrong currency.** A change to a
  Jordanian company's price was recorded as US dollars — the amount was
  right, the currency label was not, which reads like somebody made a
  currency mistake. It now records the currency the price was actually
  set in. Entries written before this fix still show the old label.

- **Connecting WhatsApp, Messenger or Instagram no longer fails
  silently.** The "Webhook secret" field said *"leave blank to
  auto-generate a secure one"* — but Meta signs every message with **your
  app's App Secret**, so a generated value meant setup succeeded,
  verification went green, the channel reported itself healthy, and then
  every single incoming message was rejected and thrown away with nothing
  on screen to explain it. The field is now called **App Secret**, is
  required, and says exactly where to find it in your Meta app and why it
  has to match. Anyone who connected a Meta channel before this should
  re-enter their App Secret from Meta → Settings → Basic.

- **Facebook Messenger and Instagram now have proper setup forms.** They
  previously required hand-writing JSON with no guidance and no
  validation, so a single mistyped field name produced a channel that
  saved cleanly and never delivered a message. They now have the same
  guided form as WhatsApp, and their settings are validated before saving.

- **The app is now reachable through its domain in a browser.** The
  development front-end server rejects requests arriving under a host
  name it hasn't been told about — a deliberate safety check against
  DNS rebinding — which made every page return "Blocked request" once
  traffic started arriving through the new domain. The deployment's host
  name is now listed explicitly, rather than switching the check off
  altogether.
- The Release Notes page no longer breaks when a release removes
  something. "Removed" is a standard changelog section, but the parser
  didn't recognise it — and an unrecognised section failed the whole
  file, so one such entry would have taken down the entire Release Notes
  page and the version banner with it.
- Closing a company now actually blocks its people from signing in.
  Nothing checked whether a company had been closed, so its users could
  keep signing in indefinitely.
- **You can now take a conversation back from AI Autopilot.** When an
  agent handed a chat to AI (or AI stepped in on its own), there was no
  way to resume it — the conversation showed "AI is currently replying…
  pick it up to take over", but the button to do that was hidden exactly
  when AI was in control. A **"Take over from AI"** button now appears
  whenever AI holds the conversation. It keeps the conversation with
  whoever it was already assigned to, and assigns it to you if nobody
  held it.

## [1.0.0-beta.5] - 2026-07-28

### Added

- **AI Autopilot can now step in three different ways, and you choose
  which.** Alongside the existing behaviour (AI handles a brand-new
  conversation in an AI-enabled queue, still on by default), you can now
  also let AI step in automatically when a conversation is close to
  missing — or has already missed — its response target, and/or let
  agents hand a conversation to AI themselves with a new "Ask AI to
  reply" button. Turn on any combination in Settings → AI; AI still
  always hands back to a person whenever it isn't confident enough.
- **AI usage is now tracked per agent.** A new "AI usage by agent"
  breakdown in Reports shows how much each agent uses AI, how many times
  they asked AI to take over a conversation, and how often AI stepped in
  on their conversations on its own because a response target was
  slipping. Usage over time can be viewed daily, weekly or monthly.
- **Every AI Autopilot reply is recorded in the activity log**, including
  what triggered it (an agent's request or an automatic response-target
  trigger), who asked for it, when, and which conversation it belongs to.
- Replies an agent wrote with AI's help are now recorded separately from
  both fully automatic AI replies and replies written entirely by hand,
  so reporting can tell the three apart.
- The conversation workspace now has a dedicated **Filters & Queues**
  column, so filtering by status or queue no longer sits stacked on top
  of the conversation list. Your chosen filter is kept in the page
  address, so it survives opening a conversation and coming back.
- The Dashboard now shows a live "SLA breached" count: how many
  conversations are open or pending right now and have already missed a
  service-level agreement target. It turns red the moment that number is
  above zero, so supervisors can see at a glance whether anything needs
  attention — separate from the SLA report, which looks back over a date
  range rather than showing the current moment.

### Fixed

- Deleting an agent and then adding a new agent with the same email
  address no longer fails with "already exists." Deleting an agent
  previously removed their agent profile but left their sign-in account
  in place forever, permanently reserving that email address. Deleting
  an agent now also closes their sign-in account, which additionally
  means a deleted agent is immediately signed out everywhere and can no
  longer log back in — previously their existing session kept working.
  Email addresses belonging to agents deleted *before* this fix are
  released automatically on upgrade, so they can be re-used too.
- The reply box in a conversation now always stays visible at the bottom
  of the screen while you scroll back through the message history,
  instead of being able to get squeezed out of view when it grows (for
  example when it's showing attachments or an error message).
- The conversation workspace now behaves like an enterprise application
  rather than a long web page: it fills the screen edge to edge, and the
  conversation list, the message history and the customer details panel
  each scroll on their own. Scrolling one no longer moves the others,
  and the page as a whole no longer scrolls at all.
- Opening a conversation now always jumps to its newest message. If you
  had scrolled up to read history in a previous conversation, the next
  one you opened could previously open stranded part-way up the thread.
- Scrolling a conversation no longer moves the whole page. When the
  "finish setting up your company" banner was showing, the conversation
  workspace was sized as if the banner weren't there, making the page
  slightly too tall — so scrolling dragged the conversation list and the
  customer panel along with the messages instead of scrolling only the
  message history.
- The customer information panel on the right of a conversation now
  lines up properly with the rest of the page: it shares one rounded
  border with the message area instead of sitting in its own
  mismatched box, has a consistent width and background, and no longer
  looks visually disconnected from the conversation beside it.

## [1.0.0-beta.4] - 2026-07-28

### Added

- Conversations can now be given a priority — Low, Normal, High, or
  Urgent — so agents and supervisors can flag what needs attention
  first. Higher-priority conversations now sort to the top of the Inbox
  automatically, ahead of how recently they were last active.
- The Inbox now shows, at a glance, how many unread customer messages
  are waiting in each conversation — the count disappears the instant an
  agent opens the conversation and reads them.
- The Inbox now shows a clear warning badge on any conversation that's
  approaching its service-level agreement (SLA) target, and a distinct
  "breached" badge once it's actually missed — separate from each
  other, so agents can act before a deadline is missed, not just after.

### Changed

- The Inbox has been redesigned from the ground up for faster triage:
  each row now shows a color-coded channel icon, a customer avatar with
  an unread-message badge attached directly to it, a priority badge, and
  an SLA warning/breach badge — all in one glance, without needing to
  read column labels. Rows for on-track, normal-priority conversations
  (the common case) stay visually quiet; badges only appear where
  something genuinely needs attention. Conversations being handled by AI
  Autopilot are now clearly marked in the Inbox itself, not only inside
  the conversation.
- The Inbox can now be navigated entirely from the keyboard: press `j`/
  `k` to move between conversations without touching the mouse, in
  addition to the existing arrow-key and Enter support.
- If the Inbox fails to load conversations (e.g. a lost connection), it
  now shows a clear error message with a "Retry" button instead of
  silently displaying an empty list.
- The Public Release Notes page has been redesigned as a searchable,
  collapsible list: only the newest release is expanded by default,
  each release's header now shows its type (Major/Minor/Patch), channel
  (Beta/Release Candidate/Stable), and how many new features,
  improvements, and bug fixes it contains, and a search box filters the
  whole release history instantly. Every release can now be linked to
  and shared directly.

## [1.0.0-beta.3] - 2026-07-28

### Added

- The Provider & Service Status page now tells you whose problem a
  degraded channel is: a clear message distinguishes "the provider's own
  servers aren't responding" (not a BlinkEngage issue) from "your
  credentials or setup need attention" (yours to fix), instead of a
  single red "Unhealthy" chip that looked the same either way.
- The language icon in the top bar now opens an actual language menu
  (English / Arabic) — selecting one immediately switches every screen's
  text and text direction for you, on this device, with no page reload
  and no permission needed. Previously this icon only flipped left-to-
  right vs. right-to-left layout and never changed the language at all.

### Changed

- In a conversation, only the message history scrolls now — the
  customer info panel on the right used to be able to grow past the
  screen and drag the conversation list and message thread into
  scrolling along with it. It now scrolls independently, exactly like
  the message thread already did.
- The message thread no longer jumps you back to the newest message the
  instant a new one arrives while you're scrolled up reading earlier
  messages — it only jumps to the bottom automatically when you were
  already there, the same way most chat apps behave.

## [1.0.0-beta.2] - 2026-07-28

The Enterprise Readiness & UX milestone: SLA management, realtime
messaging fixes, an expanded AI Provider lineup with AI Autopilot, full
Arabic localization, agent lifecycle management, global search, and a
final cross-cutting product review that fixed every high-severity
accessibility, responsiveness, and security/compliance finding it
surfaced.

### Added

- A "Pick up" button now appears in the conversation sidebar whenever a
  conversation is unassigned — an agent who arrives via a notification
  (an AI Autopilot handoff, an SLA breach) can now claim it directly
  instead of having to go back to the Inbox and hunt for the row.
- Replies sent automatically by AI Autopilot are now labeled "AI" in the
  conversation transcript, so agents, supervisors, and anyone reviewing
  the conversation can always tell which messages had no human in the
  loop.
- Every message bubble in a conversation now shows who sent it ("You" or
  "Customer") as visible text, not just its side of the thread and its
  background color — clearer for everyone, and no longer relies on color
  alone to convey who's speaking.
- Global search: press Ctrl+K (or the search icon in the top bar) from
  anywhere to search conversations, customers, agents, knowledge base
  articles and categories, quick replies, teams, queues, and workflows
  all at once. You only ever see results from things you already have
  permission to open. Results for parts of the product that don't have
  their own page yet are shown too, marked as such, so search never
  quietly hides a real match.
- AI Autopilot: AI can now handle conversations end to end on queues you
  choose, replying to customers automatically and handing the
  conversation to a human the moment it isn't confident enough — the
  full conversation history stays intact, so whoever takes over sees
  everything that was already said. Turn it on in Settings → AI (with a
  confidence threshold you control), then enable it per queue in Queues
  & Routing; both switches must be on, so a single toggle can pause it
  everywhere. Agents in the queue's department get a notification the
  instant a handoff happens, and picking the conversation up takes it
  back from AI the same way picking up any other conversation works.
- Owners and admins can now connect Google Gemini, Microsoft Azure
  OpenAI, Mistral, Groq, or DeepSeek for AI features, alongside the
  existing OpenAI, Claude, and self-hosted Ollama options (Settings →
  AI). Azure OpenAI additionally asks for your deployment name (and
  optionally an API version), since Azure selects the model that way
  instead of by name. Whichever provider is configured — a company's
  own, or the platform's shared default — every AI feature keeps working
  exactly as before.
- Opening a conversation now shows a persistent conversation list next to
  it (on desktop), so you can switch between conversations without
  losing your place — only the message history scrolls; the list, the
  reply box, and the customer info panel all stay put. The full Inbox
  (with its filters, queue view, and Pick action) is still there, one
  click away via the back button. On mobile, opening a conversation
  still takes over the full screen as before.
- Every page's navigation sidebar and top bar now stay visible while you
  scroll a long page, instead of scrolling away with the content.
- Agents and supervisors can now rate customers internally, 1-5 stars
  with an optional note (e.g. "Polite, pays on time" or "Frequently
  disputes charges") — visible on the customer's profile page (a new
  "Internal rating" tab) and as a compact summary in the conversation
  workspace's customer sidebar. Every rating is kept as its own entry, so
  a history of ratings from different team members builds up over time
  instead of one person's rating overwriting another's. Never shown to
  the customer on any channel or survey.
- The Queue Dashboard now shows exactly where every conversation stands:
  a new company-wide flow chart totals waiting, picked (assigned, no
  reply yet), active (assigned and replied to), resolved, and closed
  conversations across every queue, and each queue's own row gets a
  compact visual bar plus new Picked/Active/Resolved (24h)/Closed (24h)
  columns, grouped under "Pipeline" and "Last 24h" headers so throughput
  is never confused with what's still waiting.
- Full Arabic translation of the entire signed-in application — every
  page, dialog, menu, table, and form across the app now renders in
  Arabic, with the interface laid out right-to-left to match. Set it in
  Settings → Language (applies to everyone signed in to the company);
  English remains the default. The sign-in/registration pages, the
  public Changelog, and the customer-facing satisfaction survey page
  aren't translated yet and stay in English for this release.
- You can now upload your company logo directly from your computer in
  Settings → Branding, instead of pasting a link to an image hosted
  elsewhere.
- Every PDF and Excel report export (and the audit log export) now
  automatically includes your company logo at the top, once you've
  uploaded one.
- Removing an agent now asks what to do with any conversations still
  assigned to them: transfer every one of them to another agent, or
  permanently delete the agent together with those conversations.
  Permanent deletion requires two separate confirmation steps, including
  typing the agent's name, since it can't be undone the way a transfer
  can.
- Basic offline support: if your connection drops, a banner lets you
  know, and you can keep typing — a reply you send while offline is
  queued and delivered automatically the moment you're back online (even
  if you close and reopen the tab in the meantime), instead of failing
  or getting lost.
- Manual pickup and release for queued conversations, so agents can claim
  or hand back work directly from the Inbox, with a new "Busy" status
  agents can set for themselves.
- A live queue dashboard showing waiting and assigned counts, average and
  longest wait times, average pickup time, SLA breaches, abandoned
  conversations, and throughput for every queue.
- A system logo and favicon across the app, and a footer showing the
  current year automatically.
- A public Changelog page (linked from the sign-in page) showing what's
  new in each release — no sign-in required.
- AI-assisted replies: agents can now ask AI to draft a reply based on the
  conversation so far, reviewing and editing it before sending. Agents can
  also generate a quick AI summary of a conversation from the sidebar.
- A Queues & Routing page for owners and admins: create and edit queues
  (assignment method, response/resolution time targets) and author the
  rules that decide which queue a new conversation lands in — previously
  only possible by calling the API directly.
- Owners and admins can now connect their own OpenAI, Claude, or
  self-hosted Ollama account for AI features, instead of relying on the
  platform's shared default provider (Settings → AI).
- A new Roles & Permissions page: define custom roles alongside the
  built-in Owner, Admin, and Agent roles, choose exactly which
  permissions each one grants, and see (and manage) who holds each role.
  Admin and Agent's own default permissions can now be customized too. A
  new "Change role" action on the Agents page reassigns any agent to any
  role.
- A new SLA Builder: define reusable SLA policies (response/resolution
  targets, a warning threshold before breach, and automatic escalation —
  reassign or notify someone) and assign them to any queue. Policies can
  be business-hours-aware, honoring your company's configured Business
  Hours and a new Holidays list. A preview tool shows exactly when a
  policy's warnings and deadlines would land before you assign it to a
  real queue.
- A live "Customer is typing…" indicator in the conversation view, for
  channels that support it (Web Chat today).
- Customer satisfaction surveys are now sent automatically the moment a
  conversation is resolved, right on the same channel the conversation
  happened on (WhatsApp, Web Chat, email, and so on) — no more relying
  on an agent to generate and share the link by hand. If a customer
  doesn't have an email or phone number on file, the survey page
  politely asks for one before showing the rating form, so support can
  follow up with them later.
- The Dashboard now shows total, active, and unassigned conversation
  counts, plus a Team Workload table with each agent's current open and
  pending conversation count (including agents with none, so you can see
  who's free) — alongside the existing per-status counts and Queue
  depth table.
- A new Status page (Platform navigation) shows live connectivity for
  every messaging channel type — WhatsApp, Facebook Messenger,
  Instagram, Telegram, Email, SMS, and Web Chat — grouped by type with
  an at-a-glance Operational/Degraded/Not configured badge, individual
  and "Check all now" bulk connection testing, extensible to any future
  channel type automatically.
- A search box on the Agents and Departments pages, matching the one
  already on Customers (matches by name, email, or title for Agents; by
  name or description for Departments).
- You can now edit an already-connected business system (ERP) connection
  — including updating the site URL, rotating credentials, or switching
  it back on if it had been turned off — instead of only being able to
  disconnect and set it up again from scratch.
- Deleting a queue that a routing rule still points to is now blocked
  with an explanation, instead of silently breaking that rule.
- The onboarding wizard now remembers which step you were on if you
  reload the page or come back later to finish it, and the Team Setup
  step's invited-agent and created-department lists no longer reset to
  empty when you go Back or Next (the invites and departments were
  always saved — only the on-screen list was forgetting them).

### Changed

- The Branding tab in Settings has moved to the bottom of the tab list.
- Settings → Language now only offers languages with a complete
  translation (English and Arabic) rather than listing French and
  Spanish alongside them with no actual translated text behind them.
- The "+ New" button for Queues, Routing Rules, SLA Policies, and
  Holidays now lives in the page header instead of inside each tab, so
  it stays put as you switch tabs.
- The Inbox now keeps your filters (status, "My conversations", queue,
  unassigned) and page position in the page's address, so they survive
  opening a conversation and coming back, refreshing the page, or
  sharing a link.
- Report channel names (e.g. "whatsapp") now display using the same
  friendly names used everywhere else in the app (e.g. "WhatsApp
  Business").
- A failed message's error reason is now always shown under the
  message, instead of only on hover — easier to see on phones and
  tablets.
- The conversation workspace's 3-pane layout (conversation list, message
  thread, customer panel) now only switches on once the window is
  genuinely wide enough for all three to stay usable, instead of at a
  fixed width that used to squeeze the message thread down to almost
  nothing on mid-size laptop and tablet screens.
- The Sign in and Create account cards no longer overflow the screen on
  narrow phones.
- The conversation page's tabs (Messages / Internal Notes / Transfer
  History) and the Inbox's status tabs (All / Open / Pending / Resolved
  / Closed) now scroll horizontally with arrow buttons on narrow
  screens, instead of clipping off-screen with no way to reach them.
- Pages load noticeably faster, especially the first time and right
  after an update: each page (Inbox, Reports, Settings, etc.) now loads
  its own code only when you actually visit it, instead of the whole
  app downloading everything up front. This also means the Sign in page
  and the customer-facing feedback survey page (the one linked from CSAT
  emails) no longer download the entire internal agent console just to
  show a small form.
- The Dashboard — the page every signed-in user lands on — now shows a
  simple "Go to Inbox" landing page instead of an error for any custom
  role that doesn't include report-viewing permission, rather than
  presenting a broken first screen.
- A large number of smaller consistency and accessibility improvements
  across nearly every page: clearer error messages and a retry option
  on tables that fail to load, consistent "unsaved changes" behavior
- A large number of smaller consistency and accessibility improvements
  across nearly every page: clearer error messages and a retry option
  on tables that fail to load, consistent "unsaved changes" behavior
  across every Settings tab, corrected heading order and keyboard
  navigation for screen reader and keyboard users (notifications,
  permissions, conversation and customer pages), and mobile layout
  fixes on narrow screens (Escalation Rules editor, notification
  pop-ups, the notification bell menu).

### Fixed

- "Company Settings" is now simply called "Settings" throughout the app
  (sidebar, page title, and onboarding) — nothing about what it does or
  where it lives has changed.
- The permission-sync mechanism that keeps every company's roles up to
  date with the platform's permission catalog no longer overwrites a
  role's permissions once an Owner has customized them by hand.
- SLA breach detection now honors a queue's assigned SLA policy
  (business hours, holidays, warning threshold) instead of always using
  plain wall-clock time — queues with no policy assigned are unaffected.
- A manually generated customer satisfaction survey link (Conversations
  → generate CSAT link) now opens a proper feedback page in the app
  instead of a raw API address.
- The live queue dashboard was missing two of its numbers (assigned count
  and throughput), even though the underlying data was already being
  calculated correctly.
- The company logo on the sign-in and company-creation pages was
  stretched out of proportion.
- Changelog entries with a bolded label (for example, "**Conversations**:
  ...") were showing the literal `**` characters instead of real bold
  text.
- The AI provider dropdown in Company Settings showed a blank box
  instead of "Platform default" when no company-specific provider was
  configured.
- A customer's new message on a conversation an agent already had open
  didn't appear until the page was refreshed or the agent sent their own
  reply — it now appears instantly, matching what was already promised
  for this release.
- The Status page's connection badges didn't refresh after using "Test
  Connection" until the page was reloaded.
- The sidebar's active-page highlight went blank on nested pages such as
  a specific conversation or customer profile, instead of staying on the
  right section.
- The Dashboard's summary cards weren't aligned to a consistent grid,
  causing rows to look uneven.
- Navigating to an unknown web address while signed in showed a blank
  screen instead of the "Page not found" screen.
- The Agents page's action-column width didn't account for the "Change
  role" action, clipping it for some users.
- The department agents dialog showed "No agents" while the agent list
  was still loading, and permanently claimed a department had no agents
  if the request failed, with no way to retry.
- The account menu (top right) and the notifications menu could put
  screen readers into a state where the availability picker,
  "Mark all read", and "View all" were skipped entirely by keyboard/
  screen-reader navigation.
- A conversation's message thread on a phone could squeeze the sidebar
  (Status, Transfer, Release, Queue) down until it was unreachable,
  with no way to scroll to it.
- Removing an agent and choosing to permanently delete their
  conversations now requires the same permission deleting a single
  conversation already requires, instead of being reachable through
  agent-management permission alone.

### Security

- A company's own AI provider API key is encrypted at rest and never
  sent back to the browser after saving — only whether one is set.
- Turning off "Enable AI Engine features" (Settings → AI) now also stops
  AI Autopilot from auto-replying to customers, matching what that
  switch's own description already promised. Previously it only stopped
  the agent-facing AI tools (Suggest reply, Summary); Autopilot kept
  running on any queue that had it enabled.
- Switching a company's AI provider (e.g. from OpenAI to Claude) without
  entering a new API key no longer forwards the previous provider's key
  to the new one. A key now only ever carries over when the provider is
  unchanged.
- Message bodies, transfer notes, and other free-text content are no
  longer copied into the audit log verbatim — the audit log now records
  that an event happened (who, when, what type) without duplicating the
  actual conversation content into a second place with different
  retention rules than the conversation itself.
- The customer satisfaction survey's "add your contact info" step no
  longer echoes the customer's stored email and phone number back in
  its response — someone who obtains a forwarded survey link could
  previously retrieve those details without ever having entered them.

## [1.0.0-beta.1] - 2026-07-26

These are the first public release notes for Blink Engage, shared ahead of
our pilot testing. This entry covers everything built so far in one place;
from here on, new changes will first appear above under "Unreleased" as
they're completed, then get moved down to a new dated entry like this one
once they officially ship.

### Added

- **Sign-In, Access & Company Setup**: secure sign-in for your team that
  keeps people logged in without constant hassle, different access levels
  for owners, admins, and agents, and complete separation between different
  companies' data. New companies are guided through a simple 4-step setup
  wizard (company details, team setup, channels, business system
  connection), and company settings cover everything from branding,
  language, and time zone to business hours, notifications, messaging,
  security, AI, and business system connection.
- **Companies, Departments, Teams & Agents**: create, view, update, and
  remove companies, departments, teams, and agents, see whether each agent
  is available, busy, or offline, and organize agents into departments and
  teams.
- **Customers**: a searchable directory of your customers with a detailed
  profile for each one, automatically linked to their matching record in
  your business system when that connection is turned on.
- **Messaging Channels**: talk to customers across seven different
  channels — WhatsApp Business, Facebook Messenger, Instagram, Telegram,
  SMS, Email, and a built-in Web Chat widget for your website — all from
  one place, with a guided, step-by-step setup for connecting each one.
- **Conversations**: send messages and file attachments, hand a
  conversation off to another agent or department while keeping its full
  history, add private notes only your team can see, and track each
  conversation's status (open, pending, resolved, or closed).
- **Queues & Assignment**: each department has its own queue of waiting
  conversations, new conversations are routed to the right queue
  automatically based on rules you set, and conversations can then be
  shared out evenly among agents, given to whoever has the lightest
  workload, or picked up manually.
- **Automation (Workflows)**: set up simple "if this happens, then do this"
  rules so routine actions take place automatically whenever something
  changes in a conversation, customer record, or elsewhere.
- **Knowledge Base, Quick Replies & Internal Notes** for faster, more
  consistent agent responses.
- **Notifications**: get alerted in the app, by email, or through your
  browser, with each person choosing which alerts they want to receive,
  plus instant pop-up alerts while you're using the app.
- **AI Assistant**: suggested replies, automatic conversation summaries,
  translation, language detection, and sentiment detection (is the
  customer happy or upset), plus automatic tagging, smart search of your
  help articles, grammar and tone improvement for outgoing messages, and a
  recommendation for the best next action to take — you can choose which
  AI provider powers this, including OpenAI and Claude.
- **Reports & Analytics**: dashboards for executives, for individual
  agents, and for watching activity live; reports on conversations, agent
  performance, queues, and how quickly customers are served; customer
  satisfaction surveys; and the ability to export any report to PDF or
  Excel.
- **Business System Sync**: automatically keep customer records, invoices,
  sales orders, quotes, and support tickets in sync with your existing
  business management system, with updates arriving instantly whenever
  something changes there — and completely hidden from view for companies
  that choose not to use it.
- **Administration**: a complete activity log recording important
  security- and data-related actions taken across the platform, so you
  always know who did what and when.
- **Live Updates**: agents see new messages, typing indicators, and each
  other's online/offline status update instantly, with no need to refresh
  the page.
- **Modern, Easy-to-Use Interface**: a polished web application that works
  well on any screen size, supports right-to-left languages (such as
  Arabic and Hebrew), and offers both light and dark mode, covering
  everything agents and administrators need.

### Known Issues

- Queue management — agents manually picking up or releasing conversations,
  marking themselves as Busy, and the live queue stats and dashboard — is
  still being finished and isn't fully complete in this release.

### Breaking Changes

- None yet (this is our first tracked release).
