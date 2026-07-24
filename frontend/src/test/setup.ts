import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll, expect } from 'vitest'
import * as axeMatchers from 'vitest-axe/matchers'
import { server } from '../mocks/server'

// vitest-axe@0.1.0's own "vitest-axe/extend-expect" side-effect import ships
// with an empty build output (confirmed: dist/extend-expect.js is 0 bytes),
// so it registers the type augmentation but not the runtime matcher. Extend
// explicitly instead; the type augmentation still comes from
// `test/vitest-axe.d.ts`.
expect.extend(axeMatchers)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())
