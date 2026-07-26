import '@testing-library/jest-dom/vitest'
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

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  resetAgentsMock()
  resetChannelsMock()
  resetConversationsMock()
  resetNotificationsMock()
  resetErpMock()
  resetCustomersMock()
  resetDepartmentsMock()
  resetCompanyMock()
})
afterAll(() => server.close())
