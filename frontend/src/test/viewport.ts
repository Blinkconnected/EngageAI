/**
 * A `matchMedia` jsdom does not have.
 *
 * jsdom implements none, so MUI's `useMediaQuery` sees every breakpoint
 * as unmatched and every responsive component renders its narrowest
 * layout. That is not a neutral default — it silently tested the phone
 * version of a workspace designed for a desk, and a regression in the
 * two-pane layout could never have failed a test.
 *
 * Defaults to a laptop, because that is where this product is used all
 * day. `setViewportWidth` moves it for the tests that are specifically
 * about small screens.
 */

/** A 13" laptop: wide enough for `md`, not for `xl`. */
export const DEFAULT_VIEWPORT_WIDTH = 1280

let viewportWidth = DEFAULT_VIEWPORT_WIDTH
const listeners = new Set<() => void>()

/** Handles the `(min-width:900px)` / `(max-width:899.95px)` forms MUI
 * emits. Anything else — `prefers-color-scheme`, `print` — is reported
 * unmatched, which is what jsdom effectively did before and what the
 * theme code already expects. */
function evaluate(query: string): boolean {
  const min = /\(min-width:\s*([\d.]+)px\)/.exec(query)
  const max = /\(max-width:\s*([\d.]+)px\)/.exec(query)
  if (!min && !max) return false
  if (min && viewportWidth < Number(min[1])) return false
  if (max && viewportWidth > Number(max[1])) return false
  return true
}

export function installMatchMedia(): void {
  window.matchMedia = (query: string): MediaQueryList => {
    const list: MediaQueryList = {
      media: query,
      get matches() {
        return evaluate(query)
      },
      onchange: null,
      addEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => {
        listeners.add(listener as () => void)
      },
      removeEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => {
        listeners.delete(listener as () => void)
      },
      // Deprecated pair, still called by some libraries.
      addListener: (listener: () => void) => listeners.add(listener),
      removeListener: (listener: () => void) => listeners.delete(listener),
      dispatchEvent: () => true,
    }
    return list
  }
}

/** Widens or narrows the window for one test. Notifies subscribers, so a
 * component already on screen re-renders the way it would on a real
 * resize. */
export function setViewportWidth(width: number): void {
  viewportWidth = width
  for (const listener of listeners) listener()
}

export function resetViewport(): void {
  viewportWidth = DEFAULT_VIEWPORT_WIDTH
  listeners.clear()
}
