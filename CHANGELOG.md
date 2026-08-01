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

## [1.0.0] - TBD

The finished, stable release, planned once pilot testing wraps up.
