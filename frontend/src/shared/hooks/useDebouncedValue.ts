import { useEffect, useState } from 'react'

/** Returns `value` only after it has stopped changing for `delayMs`.
 *
 * Used by global search so a typeahead doesn't fire one request per
 * keystroke against an endpoint that fans out across nine tables (see
 * `docs/architecture/global-search.md`). The backend rate-limits the
 * same endpoint per user regardless — this is the polite half of that
 * pair, not the enforcement. */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])

  return debounced
}
