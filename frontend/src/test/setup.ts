import '@testing-library/jest-dom/vitest'
import i18n, { LANGUAGE_STORAGE_KEY } from '../i18n'
import { configure } from '@testing-library/dom'
import { afterAll, afterEach, beforeAll, expect } from 'vitest'
import * as axeMatchers from 'vitest-axe/matchers'
import { server } from '../mocks/server'
import { resetAgentsMock } from '../mocks/handlers/agents'
import { resetChannelsMock } from '../mocks/handlers/channels'
import { resetConversationsMock } from '../mocks/handlers/conversations'
import { resetNotificationsMock } from '../mocks/handlers/notifications'
import { resetErpMock } from '../mocks/handlers/erp'
import { resetCustomersMock } from '../mocks/handlers/customers'
import { resetDepartmentsMock } from '../mocks/handlers/departments'
import { resetCompanyMock } from '../mocks/handlers/company'
import { resetQueuesMock } from '../mocks/handlers/queues'
import { resetRolesMock } from '../mocks/handlers/roles'
import { resetSlaMock } from '../mocks/handlers/sla'
import { resetCsatMock } from '../mocks/handlers/csat'
import { resetConversationDeletionMock } from '../mocks/handlers/conversationDeletion'
import { installMatchMedia, resetViewport } from './viewport'

// vitest-axe@0.1.0's own "vitest-axe/extend-expect" side-effect import ships
// with an empty build output (confirmed: dist/extend-expect.js is 0 bytes),
// so it registers the type augmentation but not the runtime matcher. Extend
// explicitly instead; the type augmentation still comes from
// `test/vitest-axe.d.ts`.
expect.extend(axeMatchers)

// RTL's findBy*/waitFor utilities default to a 1000ms internal timeout —
// separate from (and not covered by) Vitest's own per-test timeout bumped
// in vite.config.ts. Pages like ConversationViewPage fire several
// sequential/parallel queries (conversation, customer, messages, agents,
// channels, queues) that can outrun 1000ms under this sandbox's CPU
// contention (see vite.config.ts's testTimeout comment) without being
// slow in any real environment. Raised once here rather than annotating
// every findBy call across a growing test suite.
configure({ asyncUtilTimeout: 5000 })

// Before any component renders: jsdom ships no matchMedia, so every MUI
// breakpoint would read false and every responsive layout would be
// tested in its narrowest form only.
installMatchMedia()

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(async () => {
  server.resetHandlers()
  resetAgentsMock()
  resetChannelsMock()
  resetConversationsMock()
  resetNotificationsMock()
  resetErpMock()
  resetCustomersMock()
  resetDepartmentsMock()
  resetCompanyMock()
  resetQueuesMock()
  resetRolesMock()
  resetSlaMock()
  resetCsatMock()
  resetConversationDeletionMock()
  resetViewport()
  // Some panels (e.g. company Language settings) call `i18n.changeLanguage`
  // as a real side effect of saving. i18next is a module-level singleton,
  // so without resetting it here that language leaks into every later test
  // in the run — reset it back to the app's default so each test starts
  // from the same baseline regardless of what a previous test saved.
  if (i18n.language !== 'en') {
    await i18n.changeLanguage('en')
  }
  // AppLayout's language menu persists a manual per-browser choice here
  // (see i18n/index.ts) — jsdom's localStorage is shared across every
  // test in this run, so a test that opens the menu must not leak its
  // choice into unrelated later tests (which would otherwise start
  // seeing useLanguageSync's company-default sync silently suppressed).
  localStorage.removeItem(LANGUAGE_STORAGE_KEY)
})
afterAll(() => server.close())
