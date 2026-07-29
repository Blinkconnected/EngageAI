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

## [1.0.0] - TBD

The finished, stable release, planned once pilot testing wraps up.
