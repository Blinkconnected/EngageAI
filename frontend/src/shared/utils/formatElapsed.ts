/** How long something has been true, said the way an agent says it.
 *
 * "42m", "2h 15m", "3d 4h" — deliberately not `formatRelativeTime`'s
 * "42 min ago". A duration and a point in time answer different
 * questions, and the Inbox asks the first one: how long has this been
 * waiting, not when did it start.
 *
 * Formatted in the browser rather than on the server, because "42m" is
 * not "٤٢ د" and the server has no business choosing which one the
 * reader gets.
 *
 * @param iso - the moment the clock started. `null` for "never
 *   happened", which has no duration and must not render as "0m".
 * @param now - epoch milliseconds to measure against. Passed in rather
 *   than read here so a ticking caller re-renders and a test can pin it.
 * @returns the duration, or `null` when there is nothing to measure.
 */
export function formatElapsed(iso: string | null | undefined, now: number = Date.now()) {
  if (!iso) return null
  const started = new Date(iso).getTime()
  if (Number.isNaN(started)) return null

  // Clamped at zero: clock skew between the server and the browser can
  // put a timestamp a few seconds in the future, and "-3s" on an
  // operations screen reads as a bug in the platform.
  const seconds = Math.max(0, Math.round((now - started) / 1000))
  if (seconds < 60) return `${seconds}s`

  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`

  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ${minutes % 60}m`

  return `${Math.floor(hours / 24)}d ${hours % 24}h`
}
