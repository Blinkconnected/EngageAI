/**
 * Formatting money and quantities that arrive as strings.
 *
 * Formatting only. Nothing here adds, multiplies or compares amounts: every
 * total, share and projection was computed server-side in `Decimal` and the
 * UI's job is to render it. A page that does its own arithmetic eventually
 * disagrees with the invoice, and then neither number is believable.
 *
 * `Intl.NumberFormat` takes a string safely — it parses to a double only for
 * *display*, which is exactly what a rounded 2- or 3-decimal figure is for.
 * The unrounded value stays available in the `title` attribute wherever the
 * difference could matter.
 */

export interface CurrencyFormat {
  currency: string
  /** 2 for USD, 3 for JOD (fils). A property of the currency, sent by the
   * API rather than guessed here. */
  decimals: number
}

export function formatMoney(
  amount: string | null | undefined,
  { currency, decimals }: CurrencyFormat,
  locale = 'en',
): string {
  if (amount === null || amount === undefined) return '—'
  const numeric = Number(amount)
  if (!Number.isFinite(numeric)) return '—'
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(numeric)
}

/**
 * A small estimate rounded to the currency can read as exactly zero — a
 * customer who has spent a third of a cent should not be told "$0.00" as
 * though nothing happened. Below the currency's own resolution the figure is
 * shown at higher precision instead.
 */
export function formatEstimate(
  amount: string | null | undefined,
  format: CurrencyFormat,
  locale = 'en',
): string {
  if (amount === null || amount === undefined) return '—'
  const numeric = Number(amount)
  if (!Number.isFinite(numeric)) return '—'
  const smallest = Math.pow(10, -format.decimals)
  if (numeric > 0 && numeric < smallest) {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: format.currency,
      minimumFractionDigits: format.decimals,
      maximumFractionDigits: format.decimals + 2,
    }).format(numeric)
  }
  return formatMoney(amount, format, locale)
}

/** Quantities are counts, not money: trailing zeros on "12.000000
 * conversations" are noise. */
export function formatQuantity(quantity: string | null | undefined, locale = 'en'): string {
  if (quantity === null || quantity === undefined) return '—'
  const numeric = Number(quantity)
  if (!Number.isFinite(numeric)) return '—'
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(numeric)
}

/** A unit price needs its own precision: 0.05 and 0.055 are different rates,
 * and rounding to the currency's 2 places would show them as the same. */
export function formatUnitPrice(
  amount: string | null | undefined,
  { currency }: CurrencyFormat,
  locale = 'en',
): string {
  if (amount === null || amount === undefined) return '—'
  const numeric = Number(amount)
  if (!Number.isFinite(numeric)) return '—'
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  }).format(numeric)
}

export function formatPercent(share: string | null | undefined, locale = 'en'): string {
  if (share === null || share === undefined) return '—'
  const numeric = Number(share)
  if (!Number.isFinite(numeric)) return '—'
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(numeric)}%`
}

/** A date-only string (`2026-07-30`) rendered in the viewer's locale. Parsed
 * as UTC deliberately: `new Date('2026-07-30')` is midnight UTC, and letting
 * it drift into the local timezone can show yesterday's date to anyone west
 * of Greenwich. */
export function formatDay(day: string, locale = 'en'): string {
  const parsed = new Date(`${day}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return day
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(parsed)
}

/** Short axis label — "30 Jul". A 30-day chart cannot fit the year 30 times. */
export function formatDayShort(day: string, locale = 'en'): string {
  const parsed = new Date(`${day}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return day
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  }).format(parsed)
}

export function formatTime(timestamp: string | null, locale = 'en'): string {
  if (!timestamp) return '—'
  const parsed = new Date(timestamp)
  if (Number.isNaN(parsed.getTime())) return '—'
  return new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(parsed)
}
