import type { DateRange } from './types'

export function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10)
}

export function daysAgo(days: number): Date {
  const date = new Date()
  date.setDate(date.getDate() - days)
  return date
}

/** Last 30 days (inclusive of today), the default range every report tab opens with. */
export function defaultDateRange(): DateRange {
  return { date_from: isoDate(daysAgo(29)), date_to: isoDate(daysAgo(0)) }
}

export function isValidDateRange(range: DateRange): boolean {
  return range.date_from <= range.date_to
}
