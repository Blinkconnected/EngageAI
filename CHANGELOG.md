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

### Fixed

- The live queue dashboard was missing two of its numbers (assigned count
  and throughput), even though the underlying data was already being
  calculated correctly.
- The company logo on the sign-in and company-creation pages was
  stretched out of proportion.
- Changelog entries with a bolded label (for example, "**Conversations**:
  ...") were showing the literal `**` characters instead of real bold
  text.

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
