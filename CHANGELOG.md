# Changelog

All notable changes to Blink Engage are documented in this file. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this
project adheres to [Semantic Versioning](https://semver.org/). A release's
channel is derived automatically from its version's SemVer pre-release
identifier — no suffix → `stable`; `-beta.N` → `beta`; `-rc.N` →
`release-candidate`; `-dev.N`/`-alpha.N` → `development` — see
[`docs/architecture/release-changelog.md`](docs/architecture/release-changelog.md)
for the full parsing/release procedure.

## [Unreleased]

### Added
- (nothing yet)

## [1.0.0-beta.1] - 2026-07-26

First public release notes for Blink Engage, published ahead of pilot
validation. This entry retroactively documents the full feature set built
to date; going forward, changes are appended above under `Unreleased` as
they merge, then promoted to a new dated heading when a release is cut.

### Added

- **Identity & RBAC**: JWT authentication with refresh tokens, role- and
  permission-based access control, multi-tenant company isolation, a
  4-step Company Onboarding wizard (company info, team setup, channels,
  ERP), and expanded Company Settings (general, branding, language,
  timezone, business hours, notifications, messaging, security, AI, ERP).
- **Companies, Departments, Teams & Agents**: full CRUD, agent
  availability status, department/team membership.
- **Customers**: a searchable customer directory and profile view, with
  ERPNext customer linkage where enabled.
- **Omnichannel messaging** across seven channel types — WhatsApp
  Business, Facebook Messenger, Instagram, Telegram, SMS, Email, and a
  built-in Web Chat widget — behind a common channel-provider plugin
  architecture, with guided setup (placeholders and credential-source
  links) for each channel type.
- **Conversations**: messages, file attachments, agent-to-agent and
  agent-to-department transfer with full history, internal notes, and
  conversation status tracking (open/pending/resolved/closed).
- **Queues, Routing & Assignment**: department-owned queues, rule-based
  routing of new conversations, and a pluggable assignment-strategy engine
  (round robin, least load, and manual pickup).
- **Workflow Engine**: condition/action automation triggered off domain
  events.
- **Knowledge Base, Quick Replies & Internal Notes** for faster, more
  consistent agent responses.
- **Notifications**: in-app, email, and browser delivery with per-user,
  per-notification-type preferences, plus live in-app toast pop-ups.
- **AI Engine**: reply suggestions, conversation summarization,
  translation, language detection, sentiment analysis, auto-tagging,
  knowledge search, grammar/professional rewrite assistance, and a
  next-best-action recommendation, pluggable across OpenAI, Claude, and
  Ollama.
- **Reports & Analytics**: executive, agent, and live operational
  dashboards; conversation, performance, queue, and SLA reports; customer
  satisfaction (CSAT) surveys; PDF/Excel export.
- **ERPNext Integration**: customer sync, invoices, sales orders,
  quotations, support tickets, and inbound webhooks — fully hidden from
  the UI for companies that don't enable it.
- **Administration**: an audit log of security- and data-relevant actions
  across the platform.
- **Real-time layer**: a WebSocket agent gateway powering live
  notifications, typing indicators, and presence.
- **Enterprise frontend**: a responsive, RTL-capable, light/dark-mode
  React application covering the full agent and administrator experience.

### Known Issues

- Queue Operations (manual pickup/release, agent Busy status, live queue
  metrics and dashboard) is still in active development and not yet
  feature-complete in this release.

### Breaking Changes

- N/A (first tracked release).

## [1.0.0] - TBD

Stable release, planned after pilot validation completes.
