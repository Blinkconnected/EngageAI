import { describe, expect, it } from 'vitest'
import { BILLING_CURRENCY, formatMoney, formatUnitPrice } from './money'

describe('money', () => {
  it('bills in USD in v1', () => {
    expect(BILLING_CURRENCY.code).toBe('USD')
    expect(BILLING_CURRENCY.symbol).toBe('$')
  })

  it('formats a total at the currency display scale', () => {
    expect(formatMoney('1234.5')).toBe('$1,234.50')
    expect(formatMoney('0')).toBe('$0.00')
  })

  it('shows a sub-cent unit price instead of rounding it away', () => {
    // The failure this prevents: $0.05 and $0.0005 are a hundredfold
    // apart, and at display scale they render as "$0.05" and "$0.00" —
    // making one look free and the other look identical to it in an
    // admin pricing table.
    expect(formatUnitPrice('0.000500')).toBe('$0.0005')
    expect(formatUnitPrice('0.050000')).toBe('$0.05')
  })

  it('never renders NaN at a customer', () => {
    expect(formatMoney('not-a-number')).toBe('$—')
    expect(formatUnitPrice('')).toBe('$—')
  })

  it('accepts the string amounts the API actually sends', () => {
    // Amounts cross the wire as strings precisely so they are never a
    // JS float; this asserts the formatter takes them as-is.
    expect(formatMoney('19.99')).toBe('$19.99')
  })
})
