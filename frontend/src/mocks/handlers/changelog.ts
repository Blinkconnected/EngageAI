import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type { Release, VersionInfo } from '../../features/changelog/types'

// Mirrors the real repo-root CHANGELOG.md's currently-topmost (non-TBD)
// entry (see backend/src/blinkengage/core/changelog.py's `current_release`
// — the first entry in file order) so this fixture reads as realistic
// product data rather than a synthetic placeholder.
export const MOCK_VERSION: VersionInfo = {
  product: 'Blink Engage',
  version: '1.0.0-beta.1',
  build: '2026.07.26-1',
  git_commit: 'a1b2c3d',
  release_date: '2026-07-26',
  release_channel: 'beta',
  docker_image_tag: 'blinkengage/backend:1.0.0-beta.1',
}

// Mirrors the real repo-root CHANGELOG.md's two published entries, in the
// same file order the backend returns them ("Unreleased" is excluded by
// the backend itself and never appears here). The second entry (`1.0.0`,
// still "TBD") exercises the null-release_date / all-empty-sections case.
export const MOCK_RELEASES: Release[] = [
  {
    version: '1.0.0-beta.1',
    release_date: '2026-07-26',
    channel: 'beta',
    summary:
      'First public release notes for Blink Engage, published ahead of pilot validation. This entry retroactively documents the full feature set built to date; going forward, changes are appended above under Unreleased as they merge, then promoted to a new dated heading when a release is cut.',
    added: [
      'Identity & RBAC: JWT authentication with refresh tokens, role- and permission-based access control, multi-tenant company isolation, a 4-step Company Onboarding wizard (company info, team setup, channels, ERP), and expanded Company Settings (general, branding, language, timezone, business hours, notifications, messaging, security, AI, ERP).',
      'Companies, Departments, Teams & Agents: full CRUD, agent availability status, department/team membership.',
      'Customers: a searchable customer directory and profile view, with ERPNext customer linkage where enabled.',
      'Omnichannel messaging across seven channel types — WhatsApp Business, Facebook Messenger, Instagram, Telegram, SMS, Email, and a built-in Web Chat widget — behind a common channel-provider plugin architecture, with guided setup (placeholders and credential-source links) for each channel type.',
      'Conversations: messages, file attachments, agent-to-agent and agent-to-department transfer with full history, internal notes, and conversation status tracking (open/pending/resolved/closed).',
      'Queues, Routing & Assignment: department-owned queues, rule-based routing of new conversations, and a pluggable assignment-strategy engine (round robin, least load, and manual pickup).',
      'Workflow Engine: condition/action automation triggered off domain events.',
      'Knowledge Base, Quick Replies & Internal Notes for faster, more consistent agent responses.',
      'Notifications: in-app, email, and browser delivery with per-user, per-notification-type preferences, plus live in-app toast pop-ups.',
      'AI Engine: reply suggestions, conversation summarization, translation, language detection, sentiment analysis, auto-tagging, knowledge search, grammar/professional rewrite assistance, and a next-best-action recommendation, pluggable across OpenAI, Claude, and Ollama.',
      'Reports & Analytics: executive, agent, and live operational dashboards; conversation, performance, queue, and SLA reports; customer satisfaction (CSAT) surveys; PDF/Excel export.',
      'ERPNext Integration: customer sync, invoices, sales orders, quotations, support tickets, and inbound webhooks — fully hidden from the UI for companies that do not enable it.',
      'Administration: an audit log of security- and data-relevant actions across the platform.',
      'Real-time layer: a WebSocket agent gateway powering live notifications, typing indicators, and presence.',
      'Enterprise frontend: a responsive, RTL-capable, light/dark-mode React application covering the full agent and administrator experience.',
    ],
    improved: [],
    fixed: [],
    security: [],
    breaking_changes: ['N/A (first tracked release).'],
    deprecated: [],
    known_issues: [
      'Queue Operations (manual pickup/release, agent Busy status, live queue metrics and dashboard) is still in active development and not yet feature-complete in this release.',
    ],
  },
  {
    version: '1.0.0',
    release_date: null,
    channel: 'stable',
    summary: 'Stable release, planned after pilot validation completes.',
    added: [],
    improved: [],
    fixed: [],
    security: [],
    breaking_changes: [],
    deprecated: [],
    known_issues: [],
  },
]

export const changelogHandlers = [
  http.get(`${API_BASE_URL}/version`, () => HttpResponse.json(MOCK_VERSION)),
  http.get(`${API_BASE_URL}/releases`, () => HttpResponse.json(MOCK_RELEASES)),
]
