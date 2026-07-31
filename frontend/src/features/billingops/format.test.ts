import { describe, expect, it } from 'vitest'

import { formatAmount, formatDay, formatQuantity, formatRatio } from './format'

/** ICU separates a currency code from its number with a non-breaking space,
 * which is correct typography and a trap for an equality assertion. */
const spaces = (text: string) => text.replace(/\s/g, ' ')

/**
 * Rendering the figures a finance team reads.
 *
 * Small functions, but each of these three has a failure mode that reaches a
 * screen as something worse than a blank: a raw ISO timestamp in a date
 * column, a dinar rounded to the dollar's two places, or an undefined ratio
 * rendered as a collections failure.
 */

describe('formatDay', () => {
  it('renders a date-only value', () => {
    expect(formatDay('2026-07-30', 'en')).toBe('Jul 30, 2026')
  })

  it('renders a full timestamp as a day rather than as raw ISO text', () => {
    // The regression this exists for: `issued_at` is a timestamp while
    // `due_date` is a date, and both land in the same table column. Handling
    // only the second put `2026-07-31T16:11:31.482914Z` on screen.
    expect(formatDay('2026-07-31T16:11:31.482914Z', 'en')).toMatch(/Jul 31, 2026/)
  })

  it('does not drift a date-only value into the previous day', () => {
    // Parsed as UTC on purpose. Local-time parsing shows yesterday to
    // everyone west of Greenwich, which on a due date is a real difference.
    expect(formatDay('2026-01-01', 'en')).toBe('Jan 1, 2026')
  })

  it('shows an em dash for nothing at all', () => {
    expect(formatDay(null)).toBe('—')
    expect(formatDay(undefined)).toBe('—')
  })

  it('returns an unparseable value unchanged rather than inventing a date', () => {
    expect(formatDay('not-a-date', 'en')).toBe('not-a-date')
  })
})

describe('formatAmount', () => {
  it('renders a dollar at two places', () => {
    expect(formatAmount('445.000000', 'USD', 'en')).toBe('$445.00')
  })

  it('renders a dinar at three, because the fils is real money', () => {
    expect(spaces(formatAmount('173.950000', 'JOD', 'en'))).toBe('JOD 173.950')
  })

  it('never rounds a figure away to nothing', () => {
    // A third of a cent is not zero. Telling an operator a charge was
    // nothing when it was not is the failure this console exists to avoid.
    expect(formatAmount('0.000500', 'USD', 'en')).not.toBe('$0.00')
    expect(formatAmount('0.000500', 'USD', 'en')).toContain('0.0005')
  })

  it('keeps trailing precision out of ordinary amounts', () => {
    // Storage scale is six places. Rendering all six on every cell is noise.
    expect(formatAmount('12.500000', 'USD', 'en')).toBe('$12.50')
  })

  it('shows an em dash rather than a zero for a missing value', () => {
    expect(formatAmount(null, 'USD')).toBe('—')
  })
})

describe('formatQuantity', () => {
  it('drops the trailing zeros a count does not need', () => {
    // 8,900 messages arrive as `8900.000000`. Six zeros on a count is noise
    // in a column somebody is scanning.
    expect(formatQuantity('8900.000000', 'en')).toBe('8,900')
  })

  it('keeps a genuinely fractional quantity', () => {
    // A metric billed per megabyte or per minute really does have one, and
    // rounding it away would misstate what was used.
    expect(formatQuantity('12.500000', 'en')).toBe('12.5')
  })

  it('shows an em dash for nothing at all', () => {
    expect(formatQuantity(null)).toBe('—')
  })
})

describe('formatRatio', () => {
  it('renders a proportion as a percentage', () => {
    expect(formatRatio('0.674157', 'en')).toBe('67.4%')
  })

  it('renders more than everything when arrears were collected', () => {
    expect(formatRatio('1.400000', 'en')).toBe('140%')
  })

  it('renders nothing at all when there is no ratio', () => {
    // `—`, not `0%`. A ratio with no denominator is undefined, and 0% reads
    // as a collections failure in a month that simply had no billing.
    expect(formatRatio(null, 'en')).toBe('—')
  })
})
