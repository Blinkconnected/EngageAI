const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 60 * 60],
  ['month', 30 * 24 * 60 * 60],
  ['day', 24 * 60 * 60],
  ['hour', 60 * 60],
  ['minute', 60],
]

const relativeFormatter = new Intl.RelativeTimeFormat('en', { numeric: 'auto', style: 'short' })

/** "5 min ago", "3 hr ago", "2 days ago", falling back to "just now" for
 * anything under a minute — used anywhere a timestamp needs to read
 * naturally in a list (Inbox, message thread) without a date library. */
export function formatRelativeTime(isoTimestamp: string): string {
  const deltaSeconds = (new Date(isoTimestamp).getTime() - Date.now()) / 1000

  for (const [unit, secondsInUnit] of UNITS) {
    if (Math.abs(deltaSeconds) >= secondsInUnit) {
      return relativeFormatter.format(Math.round(deltaSeconds / secondsInUnit), unit)
    }
  }
  return 'just now'
}
