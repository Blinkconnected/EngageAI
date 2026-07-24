// vitest-axe's own type augmentation targets the pre-v4 global `Vi.Assertion`
// namespace; Vitest 4 moved custom-matcher augmentation to `@vitest/expect`'s
// `Matchers<T>` interface, so we bridge it here rather than patch the
// dependency.
import type { AxeMatchers } from 'vitest-axe'

declare module '@vitest/expect' {
  // eslint-disable-next-line @typescript-eslint/no-empty-object-type -- declaration merging, not an empty type
  interface Matchers extends AxeMatchers {}
}
