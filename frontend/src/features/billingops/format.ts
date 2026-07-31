/**
 * Rendering figures that arrive as strings.
 *
 * Formatting only. Nothing here adds, subtracts or compares amounts — every
 * total, balance and ratio was computed server-side in `Decimal`, and a
 * console that does its own arithmetic eventually disagrees with the invoice.
 * At that point neither number is believable, which is the one thing a
 * finance tool cannot survive.
 *
 * How many decimals a currency has is asked of `Intl` rather than kept in a
 * map here: ICU already knows the dinar has three and the dollar two, and a
 * hand-maintained list is a place for them to drift apart.
 */

/** The currency's own resolution — 2 for USD, 3 for JOD. */
export function currencyDecimals(currency: string, locale = 'en'): number {
  try {
    return (
      new Intl.NumberFormat(locale, { style: 'currency', currency }).resolvedOptions()
        .minimumFractionDigits ?? 2
    )
  } catch {
    return 2
  }
}

/** How many decimals the value actually carries, ignoring trailing zeros.
 *
 * Storage scale is six places, so an invoice total arrives as `0.200000`.
 * Rendering all six is noise; rendering two would hide a rate of `0.000500`.
 * The answer is to show what is *there*. */
function significantDecimals(value: string): number {
  const fraction = value.split('.')[1]
  if (!fraction) return 0
  return fraction.replace(/0+$/, '').length
}

/**
 * An amount, at the currency's resolution or finer if the value needs it.
 *
 * Never coarser: a figure is never rounded to the point of changing what it
 * says. `0.0005 USD` renders as `$0.0005`, not `$0.00`, because telling an
 * operator that a charge was nothing when it was not is the exact failure
 * this console exists to prevent.
 */
export function formatAmount(
  value: string | null | undefined,
  currency: string,
  locale = 'en',
): string {
  if (value === null || value === undefined || value === '') return '—'
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return value
  const floor = currencyDecimals(currency, locale)
  const decimals = Math.min(Math.max(significantDecimals(value), floor), 8)
  try {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency,
      minimumFractionDigits: floor,
      maximumFractionDigits: decimals,
    }).format(numeric)
  } catch {
    return `${value} ${currency}`
  }
}

/** A count. */
export function formatCount(value: number, locale = 'en'): string {
  return new Intl.NumberFormat(locale).format(value)
}

/**
 * A metered quantity, which is a count and not money.
 *
 * Quantities arrive at storage scale like everything else, so 8,900 messages
 * reach the browser as `8900.000000`. Six trailing zeros on a message count
 * are noise in a column somebody is scanning — but the decimals are dropped
 * only when they are zero, because a metric billed per megabyte or per minute
 * genuinely has a fractional quantity and rounding it away would misstate
 * what was used.
 */
export function formatQuantity(value: string | null | undefined, locale = 'en'): string {
  if (value === null || value === undefined || value === '') return '—'
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return value
  return new Intl.NumberFormat(locale, {
    maximumFractionDigits: Math.min(significantDecimals(value), 6),
  }).format(numeric)
}

/**
 * A ratio the server sent as a decimal string, rendered as a percentage.
 *
 * `null` becomes an em dash rather than 0%: a collection ratio with no
 * billing behind it is undefined, and 0% would read as a collections failure
 * in a month that simply had no invoices.
 */
export function formatRatio(value: string | null | undefined, locale = 'en'): string {
  if (value === null || value === undefined) return '—'
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '—'
  return new Intl.NumberFormat(locale, {
    style: 'percent',
    maximumFractionDigits: 1,
  }).format(numeric)
}

/**
 * A day, in the viewer's locale.
 *
 * Takes either shape the API sends, because both land in the same column: a
 * date-only `due_date` (`2026-07-30`) and a full `issued_at` timestamp
 * (`2026-07-31T16:11:31.482914Z`). Handling only the first renders the second
 * as raw ISO text in the middle of a finance table.
 *
 * A date-only value is parsed as UTC deliberately: `new Date('2026-07-30')`
 * is midnight UTC, and letting it drift into local time shows yesterday's
 * date to anyone west of Greenwich — which on a due date is a real
 * difference. A timestamp already names its own instant, so it is rendered in
 * the viewer's zone, where "the day it was issued" is the day they mean.
 */
export function formatDay(value: string | null | undefined, locale = 'en'): string {
  if (!value) return '—'
  const dateOnly = !value.includes('T')
  const parsed = new Date(dateOnly ? `${value}T00:00:00Z` : value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    ...(dateOnly ? { timeZone: 'UTC' } : {}),
  }).format(parsed)
}

/** A timestamp, to the minute. */
export function formatMoment(value: string | null | undefined, locale = 'en'): string {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '—'
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(parsed)
}

/** `2026-07-30`, for a date input or a query parameter. */
export function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10)
}

/** A window ending tomorrow, so today's activity is inside it — `until` is
 * exclusive everywhere in the billing engine. */
export function windowOfDays(days: number): { since: string; until: string } {
  const end = new Date()
  end.setUTCDate(end.getUTCDate() + 1)
  const start = new Date(end)
  start.setUTCDate(start.getUTCDate() - days)
  return { since: isoDay(start), until: isoDay(end) }
}
