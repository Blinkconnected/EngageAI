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

### Security

- A company's own AI provider API key is encrypted at rest and never
  sent back to the browser after saving — only whether one is set.

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
