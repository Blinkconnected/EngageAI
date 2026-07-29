/**
 * The one place money is formatted in the UI.
 *
 * Mirrors the backend's `domain/money.py`. Blink Engage v1 bills in a
 * single currency, USD — but "single currency" and "currency hardcoded
 * in forty components" are different things, and only the first is
 * intended. Every amount rendered anywhere goes through here, so adding
 * a second currency later is a change to this file rather than a hunt
 * for stray `$` signs and `toFixed(2)` calls.
 *
 * Amounts arrive from the API as **strings**, not numbers, and must stay
 * that way until the moment they are displayed. A JS `number` is a
 * float: `0.1 + 0.2 !== 0.3`, so parsing a monetary value into one and
 * doing arithmetic on it reintroduces exactly the drift the backend's
 * `Decimal` exists to prevent. Nothing here does arithmetic — the server
 * is the only thing allowed to compute money.
 */

export interface Currency {
  code: string
  symbol: string
  /** Decimal places shown to a user. Storage is far more precise (the
   * backend keeps NUMERIC(18, 6)) because unit prices are sub-cent. */
  displayScale: number
}

export const USD: Currency = { code: 'USD', symbol: '$', displayScale: 2 }

/** The billing currency for this build — the seam multi-currency would widen. */
export const BILLING_CURRENCY: Currency = USD

/**
 * Parses an API amount, returning `null` for anything that isn't a real
 * number.
 *
 * Deliberately rejects the empty string, which `Number('')` maps to `0`.
 * An unset or missing amount rendering as "$0.00" tells the reader the
 * thing is *free*, when in fact its price is unknown — the two must not
 * look the same in a pricing table.
 */
function toNumber(amount: string | number): number | null {
  if (typeof amount === 'number') return Number.isFinite(amount) ? amount : null
  if (amount.trim() === '') return null
  const value = Number(amount)
  return Number.isFinite(value) ? value : null
}

/**
 * Formats an amount for display.
 *
 * Takes a string (as the API sends it) or a number, and rounds to the
 * currency's display scale — so a rate stored as `0.050000` shows as
 * `$0.05`, the way it will actually be charged.
 */
export function formatMoney(
  amount: string | number,
  currency: Currency = BILLING_CURRENCY,
): string {
  const value = toNumber(amount)
  if (value === null) return `${currency.symbol}—`
  return `${currency.symbol}${value.toLocaleString(undefined, {
    minimumFractionDigits: currency.displayScale,
    maximumFractionDigits: currency.displayScale,
  })}`
}

/**
 * Formats a *unit price*, which is often sub-cent and must not be
 * rounded away.
 *
 * `$0.05` and `$0.0005` both round to `$0.05` and `$0.00` at display
 * scale, which would make two very different prices look identical (or
 * free) in an admin table. Unit prices therefore show their significant
 * digits, up to the backend's storage scale, with trailing zeros
 * trimmed so `0.050000` reads as `$0.05` rather than `$0.050000`.
 */
export function formatUnitPrice(
  amount: string | number,
  currency: Currency = BILLING_CURRENCY,
): string {
  const raw = typeof amount === 'string' ? amount.trim() : String(amount)
  const value = toNumber(raw)
  if (value === null) return `${currency.symbol}—`
  const trimmed = raw.includes('.') ? raw.replace(/0+$/, '').replace(/\.$/, '') : raw
  const decimals = trimmed.split('.')[1]?.length ?? 0
  return `${currency.symbol}${value.toLocaleString(undefined, {
    minimumFractionDigits: Math.max(currency.displayScale, decimals),
    maximumFractionDigits: Math.max(currency.displayScale, decimals),
  })}`
}
