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
      "These are the first public release notes for Blink Engage, shared ahead of our pilot testing. This entry covers everything built so far in one place; from here on, new changes will first appear above under \"Unreleased\" as they're completed, then get moved down to a new dated entry like this one once they officially ship.",
    added: [
      "**Sign-In, Access & Company Setup**: secure sign-in for your team that keeps people logged in without constant hassle, different access levels for owners, admins, and agents, and complete separation between different companies' data. New companies are guided through a simple 4-step setup wizard (company details, team setup, channels, business system connection), and company settings cover everything from branding, language, and time zone to business hours, notifications, messaging, security, AI, and business system connection.",
      '**Companies, Departments, Teams & Agents**: create, view, update, and remove companies, departments, teams, and agents, see whether each agent is available, busy, or offline, and organize agents into departments and teams.',
      '**Customers**: a searchable directory of your customers with a detailed profile for each one, automatically linked to their matching record in your business system when that connection is turned on.',
      '**Messaging Channels**: talk to customers across seven different channels — WhatsApp Business, Facebook Messenger, Instagram, Telegram, SMS, Email, and a built-in Web Chat widget for your website — all from one place, with a guided, step-by-step setup for connecting each one.',
      "**Conversations**: send messages and file attachments, hand a conversation off to another agent or department while keeping its full history, add private notes only your team can see, and track each conversation's status (open, pending, resolved, or closed).",
      '**Queues & Assignment**: each department has its own queue of waiting conversations, new conversations are routed to the right queue automatically based on rules you set, and conversations can then be shared out evenly among agents, given to whoever has the lightest workload, or picked up manually.',
      '**Automation (Workflows)**: set up simple "if this happens, then do this" rules so routine actions take place automatically whenever something changes in a conversation, customer record, or elsewhere.',
      '**Knowledge Base, Quick Replies & Internal Notes** for faster, more consistent agent responses.',
      '**Notifications**: get alerted in the app, by email, or through your browser, with each person choosing which alerts they want to receive, plus instant pop-up alerts while you are using the app.',
      '**AI Assistant**: suggested replies, automatic conversation summaries, translation, language detection, and sentiment detection (is the customer happy or upset), plus automatic tagging, smart search of your help articles, grammar and tone improvement for outgoing messages, and a recommendation for the best next action to take — you can choose which AI provider powers this, including OpenAI and Claude.',
      '**Reports & Analytics**: dashboards for executives, for individual agents, and for watching activity live; reports on conversations, agent performance, queues, and how quickly customers are served; customer satisfaction surveys; and the ability to export any report to PDF or Excel.',
      '**Business System Sync**: automatically keep customer records, invoices, sales orders, quotes, and support tickets in sync with your existing business management system, with updates arriving instantly whenever something changes there — and completely hidden from view for companies that choose not to use it.',
      '**Administration**: a complete activity log recording important security- and data-related actions taken across the platform, so you always know who did what and when.',
      "**Live Updates**: agents see new messages, typing indicators, and each other's online/offline status update instantly, with no need to refresh the page.",
      '**Modern, Easy-to-Use Interface**: a polished web application that works well on any screen size, supports right-to-left languages (such as Arabic and Hebrew), and offers both light and dark mode, covering everything agents and administrators need.',
    ],
    improved: [],
    fixed: [],
    security: [],
    breaking_changes: ['None yet (this is our first tracked release).'],
    deprecated: [],
    known_issues: [
      "Queue management — agents manually picking up or releasing conversations, marking themselves as Busy, and the live queue stats and dashboard — is still being finished and isn't fully complete in this release.",
    ],
  },
  {
    version: '1.0.0',
    release_date: null,
    channel: 'stable',
    summary: 'The finished, stable release, planned once pilot testing wraps up.',
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
